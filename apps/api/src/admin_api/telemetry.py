"""Cliente del contrato de telemetría del pipeline (§17.13 – §17.16).

La consola consume los agregados que publica el equipo dueño del pipeline y no
replica su lógica: cualquier discrepancia entre lo que muestra la consola y lo que
dice el pipeline se resuelve en el contrato, no con una corrección local. Es la
regla que evita que dos equipos acaben con dos definiciones de «agente caído».

Dos comportamientos que la especificación exige y que aquí son explícitos:

  · Se distingue «sin trabajo» de «sin telemetría». Son situaciones opuestas en la
    pantalla de guardia y confundirlas es el error clásico de este tipo de panel.
  · Un dato más viejo que la ventana admitida se trata como no disponible, no como
    último valor conocido.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime
from typing import Any

import httpx
from kallicode_core.logging import log
from kallicode_core.seguridad import emitir_svc_token

from .errors import telemetria_no_disponible
from .settings import AdminSettings, get_admin_settings

_AGENT_COUNTER_KEYS = (
    "agentes_total",
    "agentes_ocupados",
    "agentes_caidos",
    "jobs_completados",
    "duracion_p95_s",
    "lineas_activas",
)


class _TelemetryCircuitBreaker:
    """Circuito de degradación elegante para evitar saturar telemetría caída."""

    def __init__(self) -> None:
        self._consecutive_failures: int = 0
        self._open_until: float | None = None

    def before_request(self) -> None:
        if self._open_until is None:
            return
        if time.monotonic() < self._open_until:
            raise telemetria_no_disponible()
        # Ventana de enfriamiento agotada: permite una sonda de recuperación.
        self._open_until = None

    def record_success(self) -> None:
        self._consecutive_failures = 0
        self._open_until = None

    def record_failure(self, threshold: int, cooldown_s: float) -> None:
        self._consecutive_failures += 1
        if self._consecutive_failures >= max(1, threshold):
            self._open_until = time.monotonic() + max(0.0, cooldown_s)
            log.warning(
                "admin.ops.telemetria_circuito_abierto",
                fallos_consecutivos=self._consecutive_failures,
                cooldown_s=cooldown_s,
            )

    def reset(self) -> None:
        self._consecutive_failures = 0
        self._open_until = None


_breaker = _TelemetryCircuitBreaker()


def reset_circuit_breaker() -> None:
    """Reinicia el estado del circuit breaker de telemetría (útil en pruebas)."""
    _breaker.reset()


def _timeout_acotado(settings: AdminSettings) -> httpx.Timeout:
    """Construye timeouts estrictos: conexión <= 2 s y lectura <= 3 s."""
    connect_s = min(2.0, float(settings.telemetry_connect_timeout_s))
    read_s = min(3.0, float(settings.telemetry_read_timeout_s))
    return httpx.Timeout(timeout=max(connect_s, read_s), connect=connect_s, read=read_s)


async def _pedir(ruta: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    """Llama al contrato interno con JWT de servicio (typ=svc) y resiliencia acotada."""
    s = get_admin_settings()
    _breaker.before_request()

    token = emitir_svc_token("admin-console", tenant_id="plataforma")
    base_url = s.resolve_telemetry_base_url()
    timeout = _timeout_acotado(s)

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            r = await client.get(
                f"{base_url}{ruta}",
                params=params or {},
                headers={"Authorization": f"Bearer {token}"},
            )
    except httpx.HTTPError as exc:
        _breaker.record_failure(s.telemetry_cb_failure_threshold, s.telemetry_cb_cooldown_s)
        log.warning("admin.telemetria.inalcanzable", ruta=ruta, excepcion=type(exc).__name__)
        raise telemetria_no_disponible() from exc

    if r.status_code >= 500:
        _breaker.record_failure(s.telemetry_cb_failure_threshold, s.telemetry_cb_cooldown_s)
        log.warning("admin.telemetria.error_servidor", ruta=ruta, status=r.status_code)
        raise telemetria_no_disponible()
    if r.status_code >= 400:
        log.warning("admin.telemetria.rechazada", ruta=ruta, status=r.status_code)
        raise telemetria_no_disponible()

    try:
        raw_payload = r.json()
    except ValueError as exc:
        _breaker.record_failure(s.telemetry_cb_failure_threshold, s.telemetry_cb_cooldown_s)
        log.warning("admin.telemetria.payload_invalido", ruta=ruta)
        raise telemetria_no_disponible() from exc

    if not isinstance(raw_payload, dict):
        _breaker.record_failure(s.telemetry_cb_failure_threshold, s.telemetry_cb_cooldown_s)
        log.warning("admin.telemetria.payload_invalido", ruta=ruta)
        raise telemetria_no_disponible()

    _breaker.record_success()
    return dict(raw_payload)


def _comprobar_frescura(datos: dict[str, Any], campo: str) -> int | None:
    """Evalúa frescura de la señal: >5 min WARN, >15 min HTTP 503.

    Devuelve la antigüedad no negativa en segundos, o None si no existe marca temporal.
    """
    s = get_admin_settings()
    marca = datos.get(campo)
    if not marca:
        return None
    try:
        ts = datetime.fromisoformat(str(marca).replace("Z", "+00:00"))
    except ValueError:
        return None
    edad = max(0, int((datetime.now(UTC) - ts).total_seconds()))
    if edad > s.telemetry_max_age_s:
        log.warning("admin.telemetria.desactualizada", antiguedad_s=edad)
        raise telemetria_no_disponible(edad)
    if edad > s.telemetry_warn_age_s:
        log.warning("admin.ops.telemetria_desactualizada", antiguedad_s=edad)
    return edad


async def agentes(ventana: str = "1h", etapa: str | None = None) -> dict[str, Any]:
    """§17.14 · estado agregado de agentes y líneas."""
    params: dict[str, Any] = {"ventana": ventana}
    if etapa:
        params["etapa"] = etapa
    datos = await _pedir("/telemetry/agents", params)
    edad = _comprobar_frescura(datos, "telemetria_desde")
    sin_telemetria = datos.get("telemetria_desde") is None
    datos["_antiguedad_s"] = edad
    # Sin latidos en la ventana: es ausencia de telemetría, no ausencia de trabajo.
    datos["_sin_telemetria"] = sin_telemetria
    datos["disponible"] = not sin_telemetria
    if sin_telemetria:
        datos["etapas"] = None
        for clave in _AGENT_COUNTER_KEYS:
            datos[clave] = None
    return datos


async def colas(incluir_dlq: bool = True) -> dict[str, Any]:
    """§17.15 · profundidad y antigüedad de las colas."""
    datos = await _pedir("/telemetry/queues", {"incluir_dlq": incluir_dlq})
    edad = _comprobar_frescura(datos, "telemetria_desde")
    sin_telemetria = datos.get("telemetria_desde") is None
    datos["_antiguedad_s"] = edad
    datos["_sin_telemetria"] = sin_telemetria
    datos["disponible"] = not sin_telemetria
    return datos


async def proveedores(
    ventana: str = "24h",
    proveedor: str | None = None,
    tier: str | None = None,
) -> dict[str, Any]:
    """§17.16 · agregados de disponibilidad, latencia y error por proveedor."""
    params: dict[str, Any] = {"ventana": ventana}
    if proveedor:
        params["proveedor"] = proveedor
    if tier:
        params["tier"] = tier
    datos = await _pedir("/telemetry/providers", params)
    edad = _comprobar_frescura(datos, "telemetria_desde")
    sin_telemetria = datos.get("telemetria_desde") is None
    datos["_antiguedad_s"] = edad
    datos["_sin_telemetria"] = sin_telemetria
    datos["disponible"] = not sin_telemetria
    return datos
