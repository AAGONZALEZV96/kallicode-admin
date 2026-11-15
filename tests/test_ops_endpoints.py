"""Pruebas de contrato, RBAC y observabilidad para operaciones [KC-ADM-B5-05].

Valida `/admin/v1/ops/agents`, `/admin/v1/ops/queues` y `/admin/v1/ops/models`:
  1. Respuestas 200 OK con parámetros por defecto y filtros combinados.
  2. Rechazo HTTP 422 ante ventanas, etapas, proveedores, tiers o comparaciones inválidas.
  3. Respuesta 503 TELEMETRIA_NO_DISPONIBLE ante caída o señales > 15 min, y distinción
     estricta «sin trabajo» vs «sin telemetría» (contadores nulos, nunca ceros).
  4. Derivación de estado de colas (`normal`, `atencion`, `critico`) e `incluir_dlq`.
  5. Segregación estricta del tier `fable`, modelos canónicos v1.1, costes oficiales
     (`docs/decisiones-negocio.md`) y log WARN `admin.ops.proveedor_degradado` en ventana 1h.
  6. Matriz RBAC, cero PII y uso exclusivo de `read_session()` (`kallicode_admin_ro`).
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
import respx
from admin_api.settings import get_admin_settings

pytestmark = pytest.mark.integracion


def _payload_agentes_canonico() -> dict[str, Any]:
    return {
        "ventana": "1h",
        "telemetria_desde": datetime.now(UTC).isoformat(),
        "etapas": [
            {
                "etapa": "triage",
                "agentes_total": 4,
                "agentes_ocupados": 2,
                "agentes_caidos": 0,
                "jobs_completados": 40,
                "duracion_p95_s": 12.4,
            },
            {
                "etapa": "build",
                "agentes_total": 10,
                "agentes_ocupados": 8,
                "agentes_caidos": 1,
                "jobs_completados": 85,
                "duracion_p95_s": 44.2,
            },
        ],
    }


def _payload_colas_canonico() -> dict[str, Any]:
    return {
        "telemetria_desde": datetime.now(UTC).isoformat(),
        "colas": [
            {
                "nombre": "kc:inbox",
                "pendientes": 14,
                "reclamados": 2,
                "fallidos": 0,
                "antiguedad_max_s": 20,
                "umbral_atencion_s": 60,
            },
            {
                "nombre": "kc:build",
                "pendientes": 55,
                "reclamados": 9,
                "fallidos": 0,
                "antiguedad_max_s": 85,
                "umbral_atencion_s": 60,
            },
            {
                "nombre": "kc:dlq",
                "pendientes": 2,
                "reclamados": 0,
                "fallidos": 2,
                "antiguedad_max_s": 240,
                "umbral_atencion_s": 30,
            },
        ],
    }


def _payload_modelos_v11(disponibilidad_openai: float = 99.7) -> dict[str, Any]:
    return {
        "telemetria_desde": datetime.now(UTC).isoformat(),
        "ventana": "24h",
        "proveedores": [
            {
                "proveedor": "google",
                "modelo": "gemini-3-flash",
                "tier": "flash",
                "llamadas": 1500,
                "disponibilidad_pct": 99.95,
                "latencia_p50_ms": 140,
                "latencia_p95_ms": 380,
                "tasa_error_pct": 0.05,
                "tokens_in": 400_000,
                "tokens_out": 100_000,
            },
            {
                "proveedor": "google",
                "modelo": "gemini-3-pro",
                "tier": "pro",
                "llamadas": 420,
                "disponibilidad_pct": 99.80,
                "latencia_p50_ms": 520,
                "latencia_p95_ms": 1150,
                "tasa_error_pct": 0.15,
                "tokens_in": 200_000,
                "tokens_out": 50_000,
            },
            {
                "proveedor": "deepseek",
                "modelo": "deepseek-v4",
                "tier": "pro",
                "llamadas": 310,
                "disponibilidad_pct": 99.50,
                "latencia_p50_ms": 480,
                "latencia_p95_ms": 980,
                "tasa_error_pct": 0.25,
                "tokens_in": 100_000,
                "tokens_out": 20_000,
            },
            {
                "proveedor": "anthropic",
                "modelo": "claude-fable-5",
                "tier": "fable",
                "llamadas": 65,
                "disponibilidad_pct": 99.90,
                "latencia_p50_ms": 890,
                "latencia_p95_ms": 1760,
                "tasa_error_pct": 0.08,
                "tokens_in": 50_000,
                "tokens_out": 10_000,
            },
            {
                "proveedor": "openai",
                "modelo": "gpt-5-mini",
                "tier": "flash",
                "llamadas": 90,
                "disponibilidad_pct": disponibilidad_openai,
                "latencia_p50_ms": 210,
                "latencia_p95_ms": 620,
                "tasa_error_pct": 1.80 if disponibilidad_openai < 99.0 else 0.10,
                "tokens_in": 20_000,
                "tokens_out": 5_000,
            },
        ],
        "escalados": {
            "flash_a_pro": 98,
            "pro_a_fable": 14,
            "a_humano": 2,
        },
    }


async def test_ops_agents_200_filtros_y_sin_pii(
    cliente: Any, como: Any, sin_limite: None
) -> None:
    """GET /admin/v1/ops/agents devuelve etapas, líneas y alertas sin PII de tenants."""
    como("staff_operaciones")
    s = get_admin_settings()

    with respx.mock(base_url=s.telemetry_base_url) as mock:
        mock.get("/telemetry/agents").mock(
            return_value=httpx.Response(200, json=_payload_agentes_canonico())
        )
        r = await cliente.get("/admin/v1/ops/agents?ventana=5m&etapa=build")

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["telemetria"]["disponible"] is True
    assert len(body["etapas"]) == 1
    assert body["etapas"][0]["etapa"] == "build"
    assert body["etapas"][0]["agentes_caidos"] == 1
    assert body["etapas"][0]["jobs_completados"] == 85
    assert body["etapas"][0]["duracion_p95_s"] == pytest.approx(44.2)
    assert set(body["lineas"].keys()) == {"activas", "mantenimiento", "libres"}
    assert any(a["tipo"] == "agentes_caidos" and a["etapa"] == "build" for a in body["alertas"])
    texto = str(body).lower()
    assert "tenant_id" not in texto
    assert "org_acme" not in texto


async def test_ops_agents_sin_trabajo_vs_sin_telemetria(
    cliente: Any, como: Any, sin_limite: None
) -> None:
    """Distingue «sin trabajo» (disponible=true) de «sin telemetría» (etapas=null)."""
    como("staff_operaciones")
    s = get_admin_settings()
    ahora = datetime.now(UTC).isoformat()

    with respx.mock(base_url=s.telemetry_base_url) as mock:
        mock.get("/telemetry/agents").mock(
            return_value=httpx.Response(
                200,
                json={
                    "ventana": "1h",
                    "telemetria_desde": ahora,
                    "etapas": [
                        {
                            "etapa": "qa",
                            "agentes_total": 5,
                            "agentes_ocupados": 0,
                            "agentes_caidos": 0,
                            "jobs_completados": 0,
                            "duracion_p95_s": 0.0,
                        }
                    ],
                },
            )
        )
        r_idle = await cliente.get("/admin/v1/ops/agents")

    assert r_idle.status_code == 200
    assert r_idle.json()["telemetria"]["disponible"] is True
    assert r_idle.json()["etapas"][0]["agentes_ocupados"] == 0

    with respx.mock(base_url=s.telemetry_base_url) as mock:
        mock.get("/telemetry/agents").mock(
            return_value=httpx.Response(
                200,
                json={"ventana": "1h", "telemetria_desde": None, "etapas": None},
            )
        )
        r_null = await cliente.get("/admin/v1/ops/agents?etapa=qa")

    assert r_null.status_code == 200
    assert r_null.json()["telemetria"]["disponible"] is False
    assert r_null.json()["etapas"] is None


async def test_ops_queues_estados_y_filtro_dlq(
    cliente: Any, como: Any, sin_limite: None
) -> None:
    """GET /admin/v1/ops/queues clasifica normal/atencion/critico y filtra DLQ opcionalmente."""
    como("staff_operaciones")
    s = get_admin_settings()

    with respx.mock(base_url=s.telemetry_base_url) as mock:
        mock.get("/telemetry/queues").mock(
            return_value=httpx.Response(200, json=_payload_colas_canonico())
        )
        r_all = await cliente.get("/admin/v1/ops/queues")

    assert r_all.status_code == 200, r_all.text
    colas = {c["nombre"]: c for c in r_all.json()["colas"]}
    assert colas["kc:inbox"]["estado"] == "normal"
    assert colas["kc:build"]["estado"] == "atencion"
    assert colas["kc:dlq"]["estado"] == "critico"
    assert r_all.json()["resumen"]["criticas"] == 1
    assert r_all.json()["resumen"]["atencion"] == 1
    assert r_all.json()["resumen"]["fallidos_total"] == 2

    with respx.mock(base_url=s.telemetry_base_url) as mock:
        mock.get("/telemetry/queues").mock(
            return_value=httpx.Response(200, json=_payload_colas_canonico())
        )
        r_no_dlq = await cliente.get("/admin/v1/ops/queues?incluir_dlq=false")

    assert r_no_dlq.status_code == 200
    assert all("dlq" not in c["nombre"] for c in r_no_dlq.json()["colas"])


async def test_ops_models_fable_segregado_tarifas_y_comparacion(
    cliente: Any, como: Any, sin_limite: None
) -> None:
    """/ops/models reporta modelos v1.1, separa fable, aplica tarifas y soporta comparar_con."""
    como("staff_negocio")
    s = get_admin_settings()

    with respx.mock(base_url=s.telemetry_base_url) as mock:
        mock.get("/telemetry/providers").mock(
            return_value=httpx.Response(200, json=_payload_modelos_v11())
        )
        r = await cliente.get("/admin/v1/ops/models?ventana=24h&comparar_con=periodo_anterior")

    assert r.status_code == 200, r.text
    body = r.json()
    modelos_ids = {m["modelo"] for m in body["proveedores"]}
    assert {"gemini-3-flash", "gemini-3-pro", "deepseek-v4", "claude-fable-5"} <= modelos_ids

    tiers_por_modelo = {m["modelo"]: m["tier"] for m in body["proveedores"]}
    assert tiers_por_modelo["claude-fable-5"] == "fable"
    assert tiers_por_modelo["gemini-3-pro"] == "pro"
    assert tiers_por_modelo["gemini-3-flash"] == "flash"

    assert body["escalados"] == {"flash_a_pro": 98, "pro_a_fable": 14, "a_humano": 2}
    # Tarifas oficiales docs/decisiones-negocio.md para fable: 0.012/1k in + 0.060/1k out
    # (50_000/1000)*0.012 + (10_000/1000)*0.060 = 0.60 + 0.60 = 1.20 EUR
    assert "fable" in body["tokens_por_tier"]
    assert "pro" in body["tokens_por_tier"]
    assert body["tokens_por_tier"]["fable"] == 60_000
    assert body["coste_por_tier"]["fable"] == pytest.approx(1.2, abs=1e-4)
    assert body["comparacion"] is not None
    assert body["comparacion"]["periodo"] == "periodo_anterior"

    with respx.mock(base_url=s.telemetry_base_url) as mock:
        mock.get("/telemetry/providers").mock(
            return_value=httpx.Response(200, json=_payload_modelos_v11())
        )
        r_fable = await cliente.get("/admin/v1/ops/models?proveedor=anthropic&tier=fable")

    assert r_fable.status_code == 200
    assert len(r_fable.json()["proveedores"]) == 1
    assert r_fable.json()["proveedores"][0]["modelo"] == "claude-fable-5"
    assert set(r_fable.json()["tokens_por_tier"].keys()) <= {"fable"}


async def test_ops_models_log_warn_proveedor_degradado_en_1h(
    cliente: Any,
    como: Any,
    sin_limite: None,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Emite WARN admin.ops.proveedor_degradado si un proveedor baja del 99% en ventana 1h."""
    como("staff_operaciones")
    s = get_admin_settings()

    caplog.clear()
    with caplog.at_level(logging.WARNING), respx.mock(base_url=s.telemetry_base_url) as mock:
        mock.get("/telemetry/providers").mock(
            return_value=httpx.Response(
                200, json=_payload_modelos_v11(disponibilidad_openai=97.4)
            )
        )
        r = await cliente.get("/admin/v1/ops/models?ventana=1h")

    assert r.status_code == 200
    assert "openai" in (r.json()["degradados"] or [])
    assert any("admin.ops.proveedor_degradado" in rec.message for rec in caplog.records)


@pytest.mark.parametrize(
    "ruta",
    [
        "/admin/v1/ops/agents?ventana=99d",
        "/admin/v1/ops/agents?etapa=inexistente",
        "/admin/v1/ops/models?ventana=15m",
        "/admin/v1/ops/models?proveedor=desconocido",
        "/admin/v1/ops/models?tier=ultra",
        "/admin/v1/ops/models?comparar_con=ano_pasado",
    ],
)
async def test_ops_rechaza_parametros_invalidos_con_422(
    cliente: Any, como: Any, sin_limite: None, ruta: str
) -> None:
    """Ventanas o filtros fuera de catálogo producen HTTP 422."""
    como("staff_admin")
    r = await cliente.get(ruta)
    assert (
        r.status_code == 422
    ), f"Se esperaba 422 para {ruta}, obtuvo {r.status_code}: {r.text}"


@pytest.mark.parametrize(
    ("endpoint", "telemetria_path"),
    [
        ("/admin/v1/ops/agents", "/telemetry/agents"),
        ("/admin/v1/ops/queues", "/telemetry/queues"),
        ("/admin/v1/ops/models", "/telemetry/providers"),
    ],
)
async def test_ops_telemetria_caida_o_obsoleta_responde_503(
    cliente: Any,
    como: Any,
    sin_limite: None,
    endpoint: str,
    telemetria_path: str,
) -> None:
    """Los tres endpoints responden 503 TELEMETRIA_NO_DISPONIBLE ante caída o señal >15 min."""
    como("staff_operaciones")
    s = get_admin_settings()

    with respx.mock(base_url=s.telemetry_base_url) as mock:
        mock.get(telemetria_path).mock(return_value=httpx.Response(503))
        r_down = await cliente.get(endpoint)
    assert r_down.status_code == 503
    assert r_down.json()["error"]["codigo"] == "TELEMETRIA_NO_DISPONIBLE"

    viejo = (datetime.now(UTC) - timedelta(minutes=20)).isoformat()
    with respx.mock(base_url=s.telemetry_base_url) as mock:
        mock.get(telemetria_path).mock(
            return_value=httpx.Response(200, json={"telemetria_desde": viejo})
        )
        r_stale = await cliente.get(endpoint)
    assert r_stale.status_code == 503
    assert r_stale.json()["error"]["codigo"] == "TELEMETRIA_NO_DISPONIBLE"


@pytest.mark.parametrize(
    ("rol", "ruta", "esperado"),
    [
        ("staff_soporte", "/admin/v1/ops/agents", 403),
        ("staff_soporte", "/admin/v1/ops/queues", 403),
        ("staff_soporte", "/admin/v1/ops/models", 403),
        ("staff_negocio", "/admin/v1/ops/agents", 403),
        ("staff_negocio", "/admin/v1/ops/queues", 403),
        ("staff_negocio", "/admin/v1/ops/models", 200),
        ("staff_operaciones", "/admin/v1/ops/agents", 200),
        ("staff_operaciones", "/admin/v1/ops/queues", 200),
        ("staff_operaciones", "/admin/v1/ops/models", 200),
        ("staff_admin", "/admin/v1/ops/agents", 200),
        ("staff_admin", "/admin/v1/ops/queues", 200),
        ("staff_admin", "/admin/v1/ops/models", 200),
    ],
)
async def test_ops_matriz_rbac_completa(
    cliente: Any,
    como: Any,
    sin_limite: None,
    rol: str,
    ruta: str,
    esperado: int,
) -> None:
    """Valida la matriz RBAC estricta de los tres endpoints operativos."""
    como(rol)
    s = get_admin_settings()

    with respx.mock(base_url=s.telemetry_base_url, assert_all_called=False) as mock:
        mock.get("/telemetry/agents").mock(
            return_value=httpx.Response(200, json=_payload_agentes_canonico())
        )
        mock.get("/telemetry/queues").mock(
            return_value=httpx.Response(200, json=_payload_colas_canonico())
        )
        mock.get("/telemetry/providers").mock(
            return_value=httpx.Response(200, json=_payload_modelos_v11())
        )
        r = await cliente.get(ruta)

    assert r.status_code == esperado, f"{rol} en {ruta}: obtuvo {r.status_code} ({r.text})"


async def test_ops_usa_exclusivamente_read_session_ro(
    cliente: Any,
    como: Any,
    sin_limite: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verifica que /ops/agents y /ops/models solo usan read_session (kallicode_admin_ro)."""
    from admin_api.routers import ops as ops_router
    from sqlalchemy import text

    como("staff_operaciones")
    s = get_admin_settings()
    usuarios_sesion: list[str] = []
    real_read_session = ops_router.read_session

    class _SpySessionCtx:
        def __init__(self) -> None:
            self._inner = real_read_session()

        async def __aenter__(self) -> Any:
            db = await self._inner.__aenter__()
            res = await db.execute(text("SELECT current_user"))
            usuarios_sesion.append(str(res.scalar_one()))
            return db

        async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> Any:
            return await self._inner.__aexit__(exc_type, exc, tb)

    monkeypatch.setattr(ops_router, "read_session", lambda: _SpySessionCtx())

    with respx.mock(base_url=s.telemetry_base_url) as mock:
        mock.get("/telemetry/agents").mock(
            return_value=httpx.Response(200, json=_payload_agentes_canonico())
        )
        mock.get("/telemetry/providers").mock(
            return_value=httpx.Response(200, json=_payload_modelos_v11())
        )
        r1 = await cliente.get("/admin/v1/ops/agents")
        r2 = await cliente.get("/admin/v1/ops/models")

    assert r1.status_code == 200
    assert r2.status_code == 200
    assert usuarios_sesion == ["kallicode_admin_ro", "kallicode_admin_ro"]
