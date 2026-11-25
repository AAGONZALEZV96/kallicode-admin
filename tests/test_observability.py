"""Pruebas de observabilidad Prometheus y sonda de salud /admin/v1/health (KC-ADM-B6-08).

No requiere PostgreSQL ni Redis activos al simular las sondas de dependencias,
y valida:
  - Sonda /admin/v1/health (200 ok, 200 degradado, 503 no_disponible, cero fugas).
  - Endpoints /admin/v1/metrics y /metrics en formato text/plain Prometheus.
  - Presencia de las 5 métricas instrumentadas con baja cardinalidad y sin PII.
  - Protección de acceso en red privada (CIDRs permitidos y bearer token opcional).
"""

from __future__ import annotations

import httpx
import pytest
from admin_api import telemetry
from admin_api.metrics import (
    ADMIN_METRICS_REGISTRY,
    registrar_accion_personal_metrica,
    registrar_fallo_dependencia,
)
from admin_api.routers import health as health_router
from admin_api.settings import get_admin_settings
from fastapi.testclient import TestClient


def _cliente_local() -> TestClient:
    from admin_api.main import app

    return TestClient(app, base_url="http://localhost", raise_server_exceptions=False)


def _valor_muestra(nombre: str, labels: dict[str, str] | None = None) -> float:
    val = ADMIN_METRICS_REGISTRY.get_sample_value(nombre, labels or {})
    return float(val) if val is not None else 0.0


# =========================================================================
# 1. Sonda de salud /admin/v1/health (§18.31)
# =========================================================================
def test_health_ok_cuando_todas_dependencias_responden(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _ok_true() -> bool:
        return True

    async def _ok_frescura() -> int:
        return 12

    monkeypatch.setattr(health_router, "_postgres", _ok_true)
    monkeypatch.setattr(health_router, "_lectura", _ok_true)
    monkeypatch.setattr(health_router, "_redis", _ok_true)
    monkeypatch.setattr(health_router, "_blob", _ok_true)
    monkeypatch.setattr(health_router, "_telemetria", _ok_true)
    monkeypatch.setattr(health_router, "_frescura_agregados", _ok_frescura)

    cliente = _cliente_local()
    r = cliente.get("/admin/v1/health")
    assert r.status_code == 200, r.text
    cuerpo = r.json()
    assert cuerpo["estado"] == "ok"
    assert cuerpo["agregados_frescura_s"] == 12
    assert cuerpo["version"]
    assert cuerpo["dependencias"] == {
        "postgres": True,
        "lectura_analitica": True,
        "cache": True,
        "blob": True,
        "telemetria": True,
        "agregados": True,
    }
    assert _valor_muestra("admin_aggregates_freshness_seconds", {"vista": "global"}) == 12.0


def test_health_degradado_cuando_falla_telemetria_o_agregado_viejo(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _ok_true() -> bool:
        return True

    async def _fail_false() -> bool:
        return False

    async def _ok_frescura() -> int:
        return 30

    monkeypatch.setattr(health_router, "_postgres", _ok_true)
    monkeypatch.setattr(health_router, "_lectura", _ok_true)
    monkeypatch.setattr(health_router, "_redis", _ok_true)
    monkeypatch.setattr(health_router, "_blob", _ok_true)
    monkeypatch.setattr(health_router, "_telemetria", _fail_false)
    monkeypatch.setattr(health_router, "_frescura_agregados", _ok_frescura)

    antes_tel = _valor_muestra("admin_dependency_failures_total", {"dependency": "telemetria"})
    cliente = _cliente_local()
    r = cliente.get("/admin/v1/health")
    assert r.status_code == 200, r.text
    cuerpo = r.json()
    assert cuerpo["estado"] == "degradado"
    assert cuerpo["dependencias"]["postgres"] is True
    assert cuerpo["dependencias"]["blob"] is True
    assert cuerpo["dependencias"]["telemetria"] is False
    assert (
        _valor_muestra("admin_dependency_failures_total", {"dependency": "telemetria"})
        == antes_tel + 1.0
    )

    # Ahora telemetría OK pero agregados por encima de aggregate_stale_s -> 200 degradado
    async def _frescura_vieja() -> int:
        return get_admin_settings().aggregate_stale_s + 120

    monkeypatch.setattr(health_router, "_telemetria", _ok_true)
    monkeypatch.setattr(health_router, "_frescura_agregados", _frescura_vieja)
    antes_agg = _valor_muestra("admin_dependency_failures_total", {"dependency": "agregados"})
    r_agg = cliente.get("/admin/v1/health")
    assert r_agg.status_code == 200
    assert r_agg.json()["estado"] == "degradado"
    assert r_agg.json()["dependencias"]["agregados"] is False
    assert (
        _valor_muestra("admin_dependency_failures_total", {"dependency": "agregados"})
        == antes_agg + 1.0
    )


@pytest.mark.parametrize("dependencia_caida", ["_postgres", "_blob", "_redis"])
def test_health_503_no_disponible_cuando_falla_dependencia_critica(
    monkeypatch: pytest.MonkeyPatch,
    dependencia_caida: str,
) -> None:
    async def _ok_true() -> bool:
        return True

    async def _fail_false() -> bool:
        return False

    async def _ok_frescura() -> int:
        return 5

    for nombre in ("_postgres", "_lectura", "_redis", "_blob", "_telemetria"):
        monkeypatch.setattr(
            health_router,
            nombre,
            _fail_false if nombre == dependencia_caida else _ok_true,
        )
    monkeypatch.setattr(health_router, "_frescura_agregados", _ok_frescura)

    cliente = _cliente_local()
    r = cliente.get("/admin/v1/health")
    assert r.status_code == 503
    cuerpo = r.json()
    assert cuerpo["estado"] == "no_disponible"
    for clave_prohibida in ("postgresql://", "asyncpg", "traceback", "password", "5432"):
        assert clave_prohibida not in r.text.lower()


# =========================================================================
# 2. Métricas Prometheus (/admin/v1/metrics y /metrics)
# =========================================================================
def test_metrics_prometheus_expone_series_y_protege_confidencialidad(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _ok_true() -> bool:
        return True

    async def _ok_frescura() -> int:
        return 18

    monkeypatch.setattr(health_router, "_postgres", _ok_true)
    monkeypatch.setattr(health_router, "_lectura", _ok_true)
    monkeypatch.setattr(health_router, "_redis", _ok_true)
    monkeypatch.setattr(health_router, "_blob", _ok_true)
    monkeypatch.setattr(health_router, "_telemetria", _ok_true)
    monkeypatch.setattr(health_router, "_frescura_agregados", _ok_frescura)

    cliente = _cliente_local()
    # Tráfico representativo para poblar latencia, códigos HTTP, salud y acciones
    assert cliente.get("/admin/v1/health").status_code == 200
    assert cliente.get("/admin/v1/business/customers/org_secreto_123").status_code == 401
    assert cliente.get("/admin/v1/inexistente/org_secreto_456").status_code == 404
    registrar_accion_personal_metrica("staff_soporte", "reveal")
    registrar_fallo_dependencia("telemetria")

    for endpoint in ("/admin/v1/metrics", "/metrics"):
        r = cliente.get(endpoint)
        assert r.status_code == 200, r.text
        assert r.headers["content-type"].startswith("text/plain")
        texto = r.text

        for serie in (
            "admin_http_request_duration_seconds",
            "admin_http_requests_total",
            "admin_aggregates_freshness_seconds",
            "admin_staff_actions_total",
            "admin_dependency_failures_total",
        ):
            assert serie in texto, f"falta serie Prometheus {serie!r} en {endpoint}"

        # La ruta 404 desconocida y los path params nunca exponen tenant_id ni PII en etiquetas
        assert 'route="unmatched"' in texto
        assert 'route="/admin/v1/business/customers/{tenant_id}"' in texto
        assert 'route="/admin/v1/health"' in texto
        assert 'action="reveal"' in texto
        assert 'role="staff_soporte"' in texto
        assert 'dependency="telemetria"' in texto

        for fuga in (
            "org_secreto_123",
            "org_secreto_456",
            "@kallicode.com",
            "st_01",
            "st_prueba",
            "SELECT ",
            "password_hash",
            "postgresql://",
            "Bearer ",
        ):
            assert fuga not in texto


def test_metrics_protegido_en_red_privada_y_bearer_opcional(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cliente = _cliente_local()

    # IP pública simulada fuera de KC_ADMIN_METRICS_ALLOW_CIDRS -> 403
    r_publico = cliente.get(
        "/admin/v1/metrics",
        headers={"X-Forwarded-For": "203.0.113.10"},
    )
    assert r_publico.status_code == 403

    # Con KC_ADMIN_METRICS_BEARER_TOKEN configurado: sin token 403, con token válido 200
    monkeypatch.setenv("KC_ADMIN_METRICS_BEARER_TOKEN", "token-interno-prometheus-b608")
    get_admin_settings.cache_clear()
    try:
        r_sin_token = cliente.get("/admin/v1/metrics")
        assert r_sin_token.status_code == 403

        r_mal_token = cliente.get(
            "/admin/v1/metrics",
            headers={"Authorization": "Bearer incorrecto"},
        )
        assert r_mal_token.status_code == 403

        r_ok = cliente.get(
            "/admin/v1/metrics",
            headers={"Authorization": "Bearer token-interno-prometheus-b608"},
        )
        assert r_ok.status_code == 200
    finally:
        monkeypatch.delenv("KC_ADMIN_METRICS_BEARER_TOKEN", raising=False)
        get_admin_settings.cache_clear()


async def test_telemetry_incrementa_fallos_y_circuit_breaker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    telemetry.reset_circuit_breaker()

    class _ClientError:
        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

        async def __aenter__(self) -> _ClientError:
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

        async def get(self, *args: object, **kwargs: object) -> object:
            raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(telemetry.httpx, "AsyncClient", _ClientError)
    monkeypatch.setenv("KC_ADMIN_TELEMETRY_CB_FAILURE_THRESHOLD", "1")
    get_admin_settings.cache_clear()
    try:
        antes_tel = _valor_muestra(
            "admin_dependency_failures_total", {"dependency": "telemetria"}
        )
        antes_cb = _valor_muestra(
            "admin_dependency_failures_total", {"dependency": "telemetry_circuit_breaker"}
        )
        from kallicode_core.errors import AppError

        with pytest.raises(AppError):
            await telemetry.agentes()

        assert (
            _valor_muestra("admin_dependency_failures_total", {"dependency": "telemetria"})
            == antes_tel + 1.0
        )
        assert (
            _valor_muestra(
                "admin_dependency_failures_total",
                {"dependency": "telemetry_circuit_breaker"},
            )
            >= antes_cb + 1.0
        )
    finally:
        telemetry.reset_circuit_breaker()
        monkeypatch.delenv("KC_ADMIN_TELEMETRY_CB_FAILURE_THRESHOLD", raising=False)
        get_admin_settings.cache_clear()
