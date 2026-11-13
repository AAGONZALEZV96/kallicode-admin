"""Pruebas unitarias y de resiliencia del cliente de telemetría [KC-ADM-B5-08].

Cubre:
  1. Consumo exitoso de /telemetry/agents, /telemetry/queues y /telemetry/providers.
  2. Autenticación obligatoria mediante JWT de servicio (`typ="svc"`) y soporte
     de `KC_PIPELINE_TELEMETRY_URL`.
  3. Timeouts estrictos (`connect <= 2s`, `read <= 3s`) y traducción determinista a
     HTTP 503 TELEMETRIA_NO_DISPONIBLE ante errores de red, timeout o 5xx.
  4. Frescura: WARN `admin.ops.telemetria_desactualizada` (> 5 min), HTTP 503 (> 15 min)
     y antigüedad no negativa ante desfase de reloj.
  5. Diferenciación estricta sin-trabajo vs sin-telemetría (nulos, nunca ceros).
  6. Circuit breaker de degradación elegante y cero exposición de secretos/PII en logs.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
import respx
from admin_api import telemetry
from admin_api.settings import get_admin_settings
from kallicode_core.errors import AppError
from kallicode_core.seguridad import verificar_token


async def test_consumo_exitoso_agents_queues_y_providers() -> None:
    """Consume los tres endpoints de §17.14–§17.16 propagando parámetros exactos."""
    s = get_admin_settings()
    ahora = datetime.now(UTC).isoformat()

    with respx.mock(base_url=s.resolve_telemetry_base_url()) as mock:
        ruta_ag = mock.get("/telemetry/agents").mock(
            return_value=httpx.Response(
                200,
                json={
                    "ventana": "5m",
                    "telemetria_desde": ahora,
                    "agentes_total": 12,
                    "agentes_ocupados": 6,
                    "agentes_caidos": 0,
                    "etapas": [{"etapa": "build", "agentes_total": 6, "agentes_ocupados": 4}],
                },
            )
        )
        ruta_q = mock.get("/telemetry/queues").mock(
            return_value=httpx.Response(
                200,
                json={
                    "telemetria_desde": ahora,
                    "colas": [{"nombre": "kc:inbox", "profundidad": 4, "dlq": 0}],
                },
            )
        )
        ruta_p = mock.get("/telemetry/providers").mock(
            return_value=httpx.Response(
                200,
                json={
                    "ventana": "1h",
                    "telemetria_desde": ahora,
                    "proveedores": [
                        {
                            "proveedor": "anthropic",
                            "modelo": "claude-fable-5",
                            "tier": "fable",
                            "disponibilidad_pct": 99.95,
                        }
                    ],
                    "escalados": {"flash_a_pro": 10, "pro_a_fable": 2, "a_humano": 0},
                },
            )
        )

        res_ag = await telemetry.agentes(ventana="5m", etapa="build")
        res_q = await telemetry.colas(incluir_dlq=False)
        res_p = await telemetry.proveedores(ventana="1h", proveedor="anthropic", tier="fable")

    assert ruta_ag.calls[0].request.url.params["ventana"] == "5m"
    assert ruta_ag.calls[0].request.url.params["etapa"] == "build"
    assert ruta_q.calls[0].request.url.params["incluir_dlq"] == "false"
    assert ruta_p.calls[0].request.url.params["proveedor"] == "anthropic"
    assert ruta_p.calls[0].request.url.params["tier"] == "fable"

    assert res_ag["disponible"] is True
    assert res_ag["agentes_total"] == 12
    assert res_q["disponible"] is True
    assert res_p["proveedores"][0]["tier"] == "fable"


async def test_propagacion_jwt_servicio_y_variable_kc_pipeline_telemetry_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Autentica cada llamada con JWT typ=svc y prioriza KC_PIPELINE_TELEMETRY_URL."""
    monkeypatch.setenv("KC_PIPELINE_TELEMETRY_URL", "http://pipeline-e2.internal:8000")
    ahora = datetime.now(UTC).isoformat()

    with respx.mock(base_url="http://pipeline-e2.internal:8000/internal/v1") as mock:
        ruta = mock.get("/telemetry/agents").mock(
            return_value=httpx.Response(
                200,
                json={"telemetria_desde": ahora, "agentes_total": 4, "etapas": []},
            )
        )
        datos = await telemetry.agentes("1h")

    assert datos["disponible"] is True
    auth = ruta.calls[0].request.headers["authorization"]
    assert auth.startswith("Bearer ")
    token = auth.split(" ", 1)[1]
    claims = verificar_token(token, tipo_esperado="svc")
    assert claims["typ"] == "svc"
    assert claims["svc"] == "admin-console"
    assert claims["iss"] == "kc-internal"
    assert claims["aud"] == "kc-internal-api"


@pytest.mark.parametrize(
    "efecto",
    [
        httpx.ConnectTimeout("connect timeout"),
        httpx.ReadTimeout("read timeout"),
        httpx.ConnectError("connection refused"),
        httpx.Response(500),
        httpx.Response(503),
        httpx.Response(401),
        httpx.Response(200, text="no-json"),
    ],
)
async def test_errores_red_timeout_y_http_traducen_a_503_telemetria_no_disponible(
    efecto: Any,
) -> None:
    """Timeout, error de conexión, 5xx/4xx o payload corrupto elevan 503 determinista."""
    s = get_admin_settings()
    with respx.mock(base_url=s.resolve_telemetry_base_url()) as mock:
        if isinstance(efecto, httpx.Response):
            mock.get("/telemetry/queues").mock(return_value=efecto)
        else:
            mock.get("/telemetry/queues").mock(side_effect=efecto)

        with pytest.raises(AppError) as exc_info:
            await telemetry.colas()

    assert exc_info.value.http == 503
    assert exc_info.value.codigo == "TELEMETRIA_NO_DISPONIBLE"


def test_timeout_acotado_connect_y_read() -> None:
    """Los timeouts de conexión y lectura quedan estrictamente acotados (<=2s y <=3s)."""
    s = get_admin_settings()
    timeout = telemetry._timeout_acotado(s)
    assert timeout.connect is not None and timeout.connect <= 2.0
    assert timeout.read is not None and timeout.read <= 3.0


async def test_frescura_warn_5m_error_15m_y_antiguedad_no_negativa(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Emite WARN >5 min, lanza 503 >15 min y evita antigüedades negativas."""
    s = get_admin_settings()
    hace_7_min = (datetime.now(UTC) - timedelta(minutes=7)).isoformat()
    hace_16_min = (datetime.now(UTC) - timedelta(minutes=16)).isoformat()
    futuro_2_min = (datetime.now(UTC) + timedelta(minutes=2)).isoformat()

    caplog.clear()
    with (
        caplog.at_level(logging.WARNING),
        respx.mock(base_url=s.resolve_telemetry_base_url()) as mock,
    ):
        mock.get("/telemetry/agents").mock(
            return_value=httpx.Response(
                200, json={"telemetria_desde": hace_7_min, "etapas": []}
            )
        )
        datos_warn = await telemetry.agentes()

    assert 400 <= datos_warn["_antiguedad_s"] <= 460
    assert any("admin.ops.telemetria_desactualizada" in rec.message for rec in caplog.records)

    with respx.mock(base_url=s.resolve_telemetry_base_url()) as mock:
        mock.get("/telemetry/providers").mock(
            return_value=httpx.Response(200, json={"telemetria_desde": hace_16_min})
        )
        with pytest.raises(AppError) as exc_info:
            await telemetry.proveedores()
    assert exc_info.value.http == 503
    assert exc_info.value.codigo == "TELEMETRIA_NO_DISPONIBLE"

    with respx.mock(base_url=s.resolve_telemetry_base_url()) as mock:
        mock.get("/telemetry/agents").mock(
            return_value=httpx.Response(
                200, json={"telemetria_desde": futuro_2_min, "etapas": []}
            )
        )
        datos_fut = await telemetry.agentes()
    assert datos_fut["_antiguedad_s"] == 0


async def test_sin_telemetria_anula_contadores_y_distingue_de_sin_trabajo() -> None:
    """Sin latidos fuerza disponible=False y contadores None; sin trabajo conserva ceros."""
    s = get_admin_settings()
    ahora = datetime.now(UTC).isoformat()

    with respx.mock(base_url=s.resolve_telemetry_base_url()) as mock:
        mock.get("/telemetry/agents").mock(
            return_value=httpx.Response(
                200,
                json={
                    "telemetria_desde": None,
                    "agentes_total": 0,
                    "agentes_ocupados": 0,
                    "etapas": [],
                },
            )
        )
        sin_tel = await telemetry.agentes()

    assert sin_tel["disponible"] is False
    assert sin_tel["_sin_telemetria"] is True
    assert sin_tel["etapas"] is None
    assert sin_tel["agentes_total"] is None
    assert sin_tel["agentes_ocupados"] is None

    with respx.mock(base_url=s.resolve_telemetry_base_url()) as mock:
        mock.get("/telemetry/agents").mock(
            return_value=httpx.Response(
                200,
                json={
                    "telemetria_desde": ahora,
                    "agentes_total": 10,
                    "agentes_ocupados": 0,
                    "etapas": [],
                },
            )
        )
        sin_trab = await telemetry.agentes()

    assert sin_trab["disponible"] is True
    assert sin_trab["_sin_telemetria"] is False
    assert sin_trab["agentes_total"] == 10
    assert sin_trab["agentes_ocupados"] == 0


async def test_circuit_breaker_evita_bombardeo_y_recupera_tras_cooldown(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Tras fallos consecutivos abre el circuito y luego permite sonda al expirar cooldown."""
    s = get_admin_settings()
    reloj = {"t": 1000.0}
    monkeypatch.setattr(telemetry.time, "monotonic", lambda: reloj["t"])

    caplog.clear()
    with (
        caplog.at_level(logging.WARNING),
        respx.mock(base_url=s.resolve_telemetry_base_url()) as mock,
    ):
        ruta = mock.get("/telemetry/agents").mock(return_value=httpx.Response(503))

        for _ in range(s.telemetry_cb_failure_threshold):
            with pytest.raises(AppError):
                await telemetry.agentes()

        llamadas_al_abrir = ruta.call_count
        assert llamadas_al_abrir == s.telemetry_cb_failure_threshold
        assert any("admin.ops.telemetria_circuito_abierto" in r.message for r in caplog.records)

        # Durante cooldown no debe emitir nueva petición HTTP al servicio caído.
        with pytest.raises(AppError) as exc_abierto:
            await telemetry.agentes()
        assert exc_abierto.value.http == 503
        assert ruta.call_count == llamadas_al_abrir

    # Expirado el cooldown, permite sonda de recuperación y cierra circuito si responde 200.
    reloj["t"] += s.telemetry_cb_cooldown_s + 1.0
    ahora = datetime.now(UTC).isoformat()
    with respx.mock(base_url=s.resolve_telemetry_base_url()) as mock:
        ruta_ok = mock.get("/telemetry/agents").mock(
            return_value=httpx.Response(200, json={"telemetria_desde": ahora, "etapas": []})
        )
        recuperado = await telemetry.agentes()

    assert ruta_ok.call_count == 1
    assert recuperado["disponible"] is True


async def test_logs_no_exponen_secretos_jwt_ni_pii_clientes(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Ninguna traza emitida por errores o desactualización filtra tokens ni PII."""
    s = get_admin_settings()
    caplog.clear()

    with (
        caplog.at_level(logging.DEBUG),
        respx.mock(base_url=s.resolve_telemetry_base_url()) as mock,
    ):
        mock.get("/telemetry/providers").mock(side_effect=httpx.ConnectError("red caída"))
        with pytest.raises(AppError):
            await telemetry.proveedores()

    logs_texto = "\n".join(rec.getMessage() for rec in caplog.records).lower()
    assert "bearer" not in logs_texto
    assert "eyj" not in logs_texto
    assert "org_" not in logs_texto
    assert "tenant_id" not in logs_texto
