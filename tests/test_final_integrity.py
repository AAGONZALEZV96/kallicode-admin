"""Suite de certificación final de integridad y no-fuga cross-tenant (KC-ADM-B6-12).

Consolida la validación integral para el corte Release Candidate (Hito M6):
1. Consistencia estricta de `docs/seguridad/informe_final_integridad_m6.md` frente al
   código real (cero rutas locales `file://`, pantallas `AppRouter.tsx`, endpoints
   FastAPI/OpenAPI, roles `STAFF_ROLES`, alcances `JERARQUIA` y reglas `V1`..`V6`).
2. Perímetro de red, sanidad HTTP 500 y ausencia de PII en `/metrics`.
3. Certificación integrada punta a punta sobre PostgreSQL 16 + Redis real:
   - Seis reglas de `admin.validate_read_role()` y consistencia de `admin.access_inventory`.
   - Enmascarado por defecto, rechazo de motivo inválido y revelación acotada por grant.
   - Integridad criptográfica local (`admin.verify_staff_action_chain()`) y central
     (`audit.verify_chain()` / `verificar_cadena_central_tenant()`) con 0 huérfanos.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
import yaml
from admin_api.audit import verificar_cadena_central_tenant
from admin_api.main import app
from admin_api.masking import JERARQUIA
from admin_api.metrics import ADMIN_METRICS_REGISTRY
from admin_api.security import STAFF_ROLES, emitir_tokens_staff
from fastapi.testclient import TestClient
from kallicode_core.ids import nuevo
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, ProgrammingError
from starlette.routing import Route

REPO_ROOT = Path(__file__).resolve().parent.parent
INFORME_FINAL = REPO_ROOT / "docs" / "seguridad" / "informe_final_integridad_m6.md"
OPENAPI_FILE = REPO_ROOT / "docs" / "openapi-admin-v1.yaml"
APP_ROUTER_FILE = REPO_ROOT / "apps" / "web" / "src" / "router" / "AppRouter.tsx"
CONTAINERAPPS_BICEP = REPO_ROOT / "infra" / "containerapps.bicep"
READ_ROLE_SQL = REPO_ROOT / "db" / "002_read_role.sql"

REGLAS_VALIDATE_READ_ROLE = (
    "V1_sin_bypassrls",
    "V2_solo_lectura",
    "V3_fuera_de_inventario",
    "V4_inventario_no_concedido",
    "V5_auditoria_append_only",
    "V6_cadena_integra",
)


def _normalizar_ruta_api(ruta: str) -> str:
    limpia = ruta.split("?", 1)[0].rstrip(".,:;)`'\"*")
    return re.sub(r"\$\{[^}]+\}|\{[^}]+\}", "{param}", limpia)


def _rutas_fastapi_normalizadas() -> set[str]:
    rutas: set[str] = set()
    for route in app.routes:
        if isinstance(route, Route) and route.path:
            rutas.add(_normalizar_ruta_api(route.path))
    return rutas


def _rutas_openapi_normalizadas() -> set[str]:
    spec = yaml.safe_load(OPENAPI_FILE.read_text(encoding="utf-8"))
    return {_normalizar_ruta_api(p) for p in spec.get("paths", {})}


# =============================================================================
# 1. Validación estática del informe de certificación frente al código real
# =============================================================================
def test_informe_final_integridad_consistente_con_codigo() -> None:
    """El informe M6 debe usar enlaces portables y referencias 100% reales."""
    assert INFORME_FINAL.exists(), f"Falta el informe final M6: {INFORME_FINAL}"
    texto = INFORME_FINAL.read_text(encoding="utf-8")

    # Cero rutas locales no portables
    assert "file://" not in texto, "El informe no debe incluir enlaces file:// locales"
    assert "/home/" not in texto, "El informe no debe incluir rutas /home/ locales"

    # Enlaces relativos válidos dentro del repositorio
    for destino in re.findall(r"\]\(([^)]+)\)", texto):
        if destino.startswith(("http://", "https://", "#")):
            continue
        resuelto = (INFORME_FINAL.parent / destino.split("#", 1)[0]).resolve()
        assert resuelto.exists(), f"Enlace relativo roto en informe M6: {destino!r}"
        assert resuelto.is_relative_to(REPO_ROOT)

    # Endpoints reales en FastAPI y OpenAPI
    rutas_app = _rutas_fastapi_normalizadas()
    rutas_spec = _rutas_openapi_normalizadas()
    patron_ep = re.compile(r"(?:/admin/v1/[A-Za-z0-9_{}/-]+|/metrics)")
    eps = {_normalizar_ruta_api(m) for m in patron_ep.findall(texto)}
    assert "/admin/v1/business/customers" in eps
    assert "/admin/v1/ops/sla" in eps
    for ep in eps:
        assert ep in rutas_app, f"Endpoint inexistente {ep!r} en informe M6"
        if ep.startswith("/admin/v1/") and ep != "/admin/v1/metrics":
            assert ep in rutas_spec, f"Endpoint {ep!r} fuera de openapi-admin-v1.yaml"

    # Roles, alcances y las 6 comprobaciones reales de 002_read_role.sql
    for rol in STAFF_ROLES:
        assert rol in texto, f"Falta rol canónico {rol!r} en informe M6"
    for alcance in ("datos_negocio", "expediente"):
        assert alcance in texto
    assert set(JERARQUIA) == {"datos_negocio", "expediente", "contenido_codigo"}

    sql_002 = READ_ROLE_SQL.read_text(encoding="utf-8")
    for regla in REGLAS_VALIDATE_READ_ROLE:
        assert regla in sql_002
        assert regla in texto, f"Falta regla {regla!r} en informe M6"

    # Pantallas cubiertas presentes en AppRouter.tsx
    router_src = APP_ROUTER_FILE.read_text(encoding="utf-8")
    for ruta_spa in (
        "/overview",
        "/business/customers",
        "/business/subscriptions",
        "/business/tokens",
        "/ops/agents",
        "/ops/models",
        "/ops/sla",
    ):
        assert f'path="{ruta_spa}"' in router_src
        assert ruta_spa in texto


# =============================================================================
# 2. Validación de perímetro de red, HTTP 500 sanitizado y /metrics sin PII
# =============================================================================
def test_certificacion_perimetro_red_500_y_metricas_sin_pii() -> None:
    """Valida external: false en Bicep, 500 sin trazas y /metrics sin PII."""
    bicep = CONTAINERAPPS_BICEP.read_text(encoding="utf-8")
    assert "external: false" in bicep
    assert "external: true" not in bicep

    # Verificar que un fallo no controlado devuelve 500 sanitizado sin tracebacks ni secretos
    cliente = TestClient(app, base_url="http://localhost", raise_server_exceptions=False)
    with patch(
        "admin_api.routers.health.read_session",
        side_effect=RuntimeError("secreto_interno_sql"),
    ):
        resp_500 = cliente.get("/admin/v1/health")
    assert resp_500.status_code in (500, 503)
    assert "Traceback" not in resp_500.text
    assert "secreto_interno_sql" not in resp_500.text

    # /metrics solo contiene métricas registradas y ninguna etiqueta identificable
    resp_metrics = cliente.get("/metrics")
    assert resp_metrics.status_code == 200
    body = resp_metrics.text
    for prohibido in ("org_acme", "org_globex", "@kallicode.com", "tenant_id=", "email="):
        assert prohibido not in body
    nombres_reg = {f.name for f in ADMIN_METRICS_REGISTRY.collect()}
    assert "admin_aggregates_freshness_seconds" in nombres_reg


# =============================================================================
# 3. Certificación integrada punta a punta en PostgreSQL 16 + Redis real
# =============================================================================
@pytest.mark.integracion
async def test_certificacion_integral_cross_tenant_cadenas_y_enmascaramiento(
    cliente: Any,
    dos_clientes: list[str],
    staff_factory: Any,
    db: Any,
    db_ro: Any,
) -> None:
    """Audita punta a punta roles, inventario, enmascarado, concesiones y ambas cadenas."""
    # 3.1 Todas las 6 reglas de admin.validate_read_role() deben pasar (0 filas)
    res_val = await db.execute(text("SELECT * FROM admin.validate_read_role()"))
    assert res_val.fetchall() == []

    # 3.2 Inventario no vacío y tabla prohibida inaccesible para kallicode_admin_ro
    inv_count = (
        await db.execute(text("SELECT count(*) FROM admin.access_inventory"))
    ).scalar_one()
    assert int(inv_count) > 0

    with pytest.raises((ProgrammingError, DBAPIError)):
        await db_ro.execute(text("SELECT 1 FROM core.password_reset_tokens LIMIT 1"))
    await db_ro.rollback()

    # 3.3 Ciclo: enmascarado -> motivo corto rechazado -> grant -> revelación -> revocación
    emp = await staff_factory("staff_soporte")
    mfa_at = datetime.now(UTC) - timedelta(minutes=1)
    token = emitir_tokens_staff(emp["id"], "staff_soporte", mfa_at)
    headers = {"Authorization": f"Bearer {token}"}

    r_masked = await cliente.get("/admin/v1/business/customers/org_acme", headers=headers)
    assert r_masked.status_code == 200
    assert r_masked.json()["razon_social"] != "Acme Logística S.L."
    assert len(r_masked.json()["enmascarado"]) > 0

    r_short = await cliente.post(
        "/admin/v1/access-grants",
        headers=headers,
        json={
            "tenant_id": "org_acme",
            "alcance": "datos_negocio",
            "motivo": "corto",
        },
    )
    assert r_short.status_code == 422

    motivo_valido = f"Certificación final integridad M6 sobre caso SUP-9901 ({nuevo('cs')})"
    r_grant = await cliente.post(
        "/admin/v1/access-grants",
        headers=headers,
        json={
            "tenant_id": "org_acme",
            "alcance": "datos_negocio",
            "motivo": motivo_valido,
            "duracion_min": 30,
        },
    )
    assert r_grant.status_code == 201
    grant_id = r_grant.json()["grant_id"]

    r_revealed = await cliente.get("/admin/v1/business/customers/org_acme", headers=headers)
    assert r_revealed.status_code == 200
    assert r_revealed.json()["razon_social"] == "Acme Logística S.L."

    r_revoke = await cliente.request(
        "DELETE",
        f"/admin/v1/access-grants/{grant_id}",
        headers=headers,
        json={"motivo": "Cierre de auditoría M6 verificada sin incidentes"},
    )
    assert r_revoke.status_code == 200

    r_remasked = await cliente.get("/admin/v1/business/customers/org_acme", headers=headers)
    assert r_remasked.status_code == 200
    assert r_remasked.json()["razon_social"] != "Acme Logística S.L."

    # 3.4 Integridad criptográfica de ambas cadenas y cero eventos huérfanos en org_acme
    res_local = await db.execute(text("SELECT * FROM admin.verify_staff_action_chain()"))
    assert res_local.fetchall() == []

    central = await verificar_cadena_central_tenant(db, "org_acme")
    assert central["integra"] is True

    huerfanos = (
        await db.execute(
            text(
                """
                SELECT count(*)
                FROM admin.staff_actions sa
                WHERE sa.tenant_id = 'org_acme'
                  AND NOT EXISTS (
                      SELECT 1
                      FROM audit.audit_events ae
                      WHERE ae.tenant_id = sa.tenant_id
                        AND ae.actor_tipo = 'staff'
                        AND ae.datos->>'staff_action_id' = sa.id::text
                  )
                """
            )
        )
    ).scalar_one()
    assert int(huerfanos) == 0
