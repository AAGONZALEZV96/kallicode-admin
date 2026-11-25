"""Pruebas unitarias de endurecimiento HTTP, CORS estricto y sanidad de salida (KC-ADM-B6-03).

No requiere PostgreSQL ni Redis: opera directamente sobre `app` mediante
`TestClient` de FastAPI validando cabeceras de seguridad en 2xx/4xx/5xx,
supresión de `Server`/`X-Powered-By`, rechazo de orígenes CORS no autorizados y
sanitización estricta de excepciones no controladas.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from unittest.mock import patch

import pytest
from admin_api.deps import Staff, staff_actual
from admin_api.main import MAX_BODY_BYTES, SECURITY_HEADERS, construir_cors_kwargs
from admin_api.settings import AdminSettings
from fastapi.testclient import TestClient
from pydantic import ValidationError

_CABECERAS_ESPERADAS: dict[str, str] = {
    nombre.lower(): valor for nombre, valor in SECURITY_HEADERS
}


def _assert_cabeceras_seguridad(resp: Any) -> None:
    cabeceras = {k.lower(): v for k, v in resp.headers.items()}
    for clave, valor_esperado in _CABECERAS_ESPERADAS.items():
        assert cabeceras.get(clave) == valor_esperado, (
            f"cabecera {clave!r}: se esperaba {valor_esperado!r}, "
            f"obtenido {cabeceras.get(clave)!r}"
        )
    assert "server" not in cabeceras, f"cabecera reveladora 'server' presente: {cabeceras}"
    assert (
        "x-powered-by" not in cabeceras
    ), f"cabecera reveladora 'x-powered-by' presente: {cabeceras}"


def _cliente_local() -> TestClient:
    from admin_api.main import app

    return TestClient(app, base_url="http://localhost", raise_server_exceptions=False)


# =========================================================================
# 1. Cabeceras HTTP de seguridad en 2xx, 4xx y 5xx + supresión de Server
# =========================================================================
def test_cabeceras_seguridad_y_supresion_en_200_404_413() -> None:
    """Valida las 7 cabeceras y ausencia de Server/X-Powered-By en 200, 404 y 413."""
    cliente = _cliente_local()
    # 200 OK
    r_ok = cliente.get("/admin/v1/openapi.json")
    assert r_ok.status_code == 200
    _assert_cabeceras_seguridad(r_ok)
    assert r_ok.headers.get("x-trace-id")

    # 404 Not Found
    r_404 = cliente.get("/admin/v1/ruta-inexistente-kc-b603")
    assert r_404.status_code == 404
    _assert_cabeceras_seguridad(r_404)
    assert r_404.headers.get("x-trace-id")

    # 413 Payload Too Large (rechazo temprano antes del enrutado)
    r_413 = cliente.post(
        "/admin/v1/auth/login",
        content=b"x" * (MAX_BODY_BYTES + 128),
        headers={"content-type": "application/json"},
    )
    assert r_413.status_code == 413
    _assert_cabeceras_seguridad(r_413)
    assert r_413.headers.get("x-trace-id")


def test_cabeceras_seguridad_en_403_forbidden() -> None:
    """Valida cabeceras de seguridad completas ante denegación de acceso 403."""
    from admin_api.main import app

    async def _staff_soporte() -> Staff:
        return Staff(
            id="st_b603_403",
            role="staff_soporte",
            full_name="Soporte B603",
            email="soporte.b603@kallicode.com",
            mfa_at=datetime.now(UTC),
            jti="jti_b603",
            ip="127.0.0.1",
            user_agent="pytest",
            request_id="tr_b603",
        )

    app.dependency_overrides[staff_actual] = _staff_soporte
    try:
        cliente = _cliente_local()
        r_403 = cliente.get("/admin/v1/business/overview")
        assert r_403.status_code == 403
        _assert_cabeceras_seguridad(r_403)
        assert r_403.headers.get("x-trace-id")
    finally:
        app.dependency_overrides.pop(staff_actual, None)


def test_cabeceras_seguridad_en_rechazo_de_host_invalido() -> None:
    """TrustedHostMiddleware (400) también sale envuelto con cabeceras endurecidas."""
    from admin_api.main import app

    cliente = TestClient(app, base_url="http://host-no-autorizado.invalid")
    r_400 = cliente.get("/admin/v1/openapi.json")
    assert r_400.status_code == 400
    _assert_cabeceras_seguridad(r_400)


# =========================================================================
# 2. CORS restringido sin comodines (KC_ADMIN_CORS_ORIGINS)
# =========================================================================
@pytest.mark.parametrize(
    "origen_invalido",
    [
        "",
        "   ",
        "*",
        "http://localhost:5173,*",
        "https://*.kallicode.com",
        "ftp://admin.kallicode.com",
        "sin-esquema.kallicode.com",
        '["*"]',
    ],
)
def test_cors_rechaza_comodines_y_origenes_invalidos(origen_invalido: str) -> None:
    """AdminSettings falla de forma segura si KC_ADMIN_CORS_ORIGINS usa * o es inválido."""
    with pytest.raises(ValidationError):
        AdminSettings(cors_origins=origen_invalido)


def test_cors_acepta_lista_explicita_y_json() -> None:
    """Parsea orígenes separados por coma o JSON normalizando barras finales."""
    s1 = AdminSettings(
        cors_origins="https://admin.kallicode.com/, https://staging.kallicode.com"
    )
    assert s1.origenes_cors == [
        "https://admin.kallicode.com",
        "https://staging.kallicode.com",
    ]
    cfg = construir_cors_kwargs(s1)
    assert cfg["allow_origins"] == s1.origenes_cors
    assert cfg["allow_credentials"] is True
    assert "*" not in cfg["allow_origins"]
    assert "*" not in cfg["allow_methods"]
    assert "*" not in cfg["allow_headers"]

    s2 = AdminSettings(cors_origins=json.dumps(["https://console.kallicode.com/"]))
    assert s2.origenes_cors == ["https://console.kallicode.com"]


def test_cors_permite_origen_autorizado_y_rechaza_arbitrario() -> None:
    """Valida preflight y GET para origen autorizado frente a origen arbitrario."""
    cliente = _cliente_local()
    # Origen autorizado (default local http://localhost:5173)
    r_preflight_ok = cliente.options(
        "/admin/v1/openapi.json",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "Authorization,Content-Type",
        },
    )
    assert r_preflight_ok.status_code == 200
    assert r_preflight_ok.headers.get("access-control-allow-origin") == "http://localhost:5173"
    assert r_preflight_ok.headers.get("access-control-allow-credentials") == "true"
    assert r_preflight_ok.headers.get("access-control-allow-origin") != "*"
    _assert_cabeceras_seguridad(r_preflight_ok)

    # Origen no autorizado en preflight -> 400 sin Access-Control-Allow-Origin
    r_preflight_bad = cliente.options(
        "/admin/v1/openapi.json",
        headers={
            "Origin": "https://atacante.evil.example",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert r_preflight_bad.status_code == 400
    assert "access-control-allow-origin" not in {k.lower() for k in r_preflight_bad.headers}
    _assert_cabeceras_seguridad(r_preflight_bad)

    # Petición simple con Origin arbitrario -> jamás refleja Access-Control-Allow-Origin
    r_get_bad = cliente.get(
        "/admin/v1/openapi.json",
        headers={"Origin": "https://atacante.evil.example"},
    )
    assert r_get_bad.status_code == 200
    assert "access-control-allow-origin" not in {k.lower() for k in r_get_bad.headers}
    _assert_cabeceras_seguridad(r_get_bad)


def test_cors_usa_variable_entorno_kc_admin_cors_origins(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Al cambiar KC_ADMIN_CORS_ORIGINS, solo el origen configurado es permitido."""
    from admin_api.settings import get_admin_settings

    monkeypatch.setenv("KC_ADMIN_CORS_ORIGINS", "https://admin.kallicode.com")
    get_admin_settings.cache_clear()
    try:
        cliente = _cliente_local()
        r_ok = cliente.options(
            "/admin/v1/openapi.json",
            headers={
                "Origin": "https://admin.kallicode.com",
                "Access-Control-Request-Method": "GET",
            },
        )
        assert r_ok.status_code == 200
        assert r_ok.headers.get("access-control-allow-origin") == "https://admin.kallicode.com"

        r_bad = cliente.options(
            "/admin/v1/openapi.json",
            headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "GET",
            },
        )
        assert r_bad.status_code == 400
    finally:
        monkeypatch.delenv("KC_ADMIN_CORS_ORIGINS", raising=False)
        get_admin_settings.cache_clear()


# =========================================================================
# 3. Sanidad de salida y supresión total de stack traces en HTTP 500
# =========================================================================
def test_error_500_no_filtra_trazas_sql_rutas_ni_credenciales() -> None:
    """Una excepción no controlada devuelve JSON 500 sanitizado y registra traceback interno."""
    from admin_api import main as main_mod
    from admin_api.main import app

    mensaje_secreto = (
        "SELECT id, password_hash FROM admin.staff WHERE email='root@kallicode.com' "
        '-- File "/app/apps/api/src/admin_api/secreto.py", line 88, token=sk-live-12345'
    )

    async def _fallo_imprevisto() -> Staff:
        raise RuntimeError(mensaje_secreto)

    app.dependency_overrides[staff_actual] = _fallo_imprevisto
    try:
        cliente = _cliente_local()
        with patch.object(main_mod.log, "error") as spy_log_err:
            r_500 = cliente.get(
                "/admin/v1/staff/me",
                headers={"X-Trace-Id": "tr_sanidad_500_prueba"},
            )

        assert r_500.status_code == 500
        _assert_cabeceras_seguridad(r_500)
        assert r_500.headers.get("x-trace-id") == "tr_sanidad_500_prueba"

        cuerpo = r_500.json()
        assert set(cuerpo) == {"error"}
        err = cuerpo["error"]
        assert err["codigo"] == "ERROR_INTERNO"
        assert err["code"] == "error_interno"
        assert err["mensaje"] == "Ha ocurrido un error interno del servidor."
        assert err["message"] == "Ha ocurrido un error interno del servidor."
        assert err["detalle"] is None
        assert err["trace_id"] == "tr_sanidad_500_prueba"

        texto_crudo = r_500.text
        for fragmento_prohibido in (
            "Traceback",
            "RuntimeError",
            "SELECT id",
            "password_hash",
            "admin.staff",
            "/app/",
            "secreto.py",
            "sk-live-12345",
        ):
            assert fragmento_prohibido not in texto_crudo

        # El servidor sí registró el stack trace interno correlacionado con trace_id
        spy_log_err.assert_called_once()
        _, kwargs_log = spy_log_err.call_args
        assert kwargs_log["exc_info"] is True
        assert kwargs_log["trace_id"] == "tr_sanidad_500_prueba"
        assert kwargs_log["excepcion"] == "RuntimeError"
        assert kwargs_log["ruta"] == "/admin/v1/staff/me"
    finally:
        app.dependency_overrides.pop(staff_actual, None)
