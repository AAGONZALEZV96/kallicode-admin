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

from typing import Any

import httpx
from kallicode_core.logging import log
from kallicode_core.seguridad import emitir_svc_token

from .errors import telemetria_no_disponible
from .settings import get_admin_settings


async def _pedir(ruta: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    """Llama al contrato interno con token de servicio y tiempo límite acotado."""
    s = get_admin_settings()
    token = emitir_svc_token("admin-console", tenant_id="plataforma")
    try:
        async with httpx.AsyncClient(timeout=s.telemetry_timeout_s) as c:
            r = await c.get(
                f"{s.telemetry_base_url}{ruta}",
                params=params or {},
                headers={"Authorization": f"Bearer {token}"},
            )
    except httpx.HTTPError as exc:
        log.warning("admin.telemetria.inalcanzable", ruta=ruta, excepcion=type(exc).__name__)
        raise telemetria_no_disponible() from exc

    if r.status_code >= 500:
        raise telemetria_no_disponible()
    if r.status_code >= 400:
        log.warning("admin.telemetria.rechazada", ruta=ruta, status=r.status_code)
        raise telemetria_no_disponible()
    datos: dict[str, Any] = r.json()
    return datos


def _comprobar_frescura(datos: dict[str, Any], campo: str) -> int | None:
    """Convierte un dato demasiado viejo en error explícito.

    Devuelve la antigüedad en segundos, o None si el contrato no la declara.
    """
    from datetime import UTC, datetime

    s = get_admin_settings()
    marca = datos.get(campo)
    if not marca:
        return None
    try:
        ts = datetime.fromisoformat(str(marca).replace("Z", "+00:00"))
    except ValueError:
        return None
    edad = int((datetime.now(UTC) - ts).total_seconds())
    if edad > s.telemetry_max_age_s:
        log.warning("admin.telemetria.desactualizada", antiguedad_s=edad)
        raise telemetria_no_disponible(edad)
    return edad


async def agentes(ventana: str = "1h", etapa: str | None = None) -> dict[str, Any]:
    """§17.14 · estado agregado de agentes y líneas."""
    datos = await _pedir(
        "/telemetry/agents", {"ventana": ventana, **({"etapa": etapa} if etapa else {})}
    )
    edad = _comprobar_frescura(datos, "telemetria_desde")
    datos["_antiguedad_s"] = edad
    # Sin latidos en la ventana: es ausencia de telemetría, no ausencia de trabajo.
    datos["_sin_telemetria"] = datos.get("telemetria_desde") is None
    return datos


async def colas(incluir_dlq: bool = True) -> dict[str, Any]:
    """§17.15 · profundidad y antigüedad de las colas."""
    return await _pedir("/telemetry/queues", {"incluir_dlq": incluir_dlq})


async def proveedores(ventana: str = "24h", proveedor: str | None = None) -> dict[str, Any]:
    """§17.16 · agregados de disponibilidad, latencia y error por proveedor."""
    return await _pedir(
        "/telemetry/providers",
        {"ventana": ventana, **({"proveedor": proveedor} if proveedor else {})},
    )
