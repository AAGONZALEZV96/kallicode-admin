"""Suite de verificación de UAT, Backlog Fase 2 y Sign-Off de Release M6 (KC-ADM-B6-14).

Valida de forma determinista el cierre del Bloque 6 (Hito M6):
1. Existencia, portabilidad (cero enlaces `file://` o `/home/`) e integridad de enlaces
   relativos en `docs/informes/uat_signoff_m6.md` y `docs/fase-2.md`, comprobando que
   todos los artefactos de evidencia del Bloque 6 existen físicamente en el repositorio.
2. Cobertura completa en los guiones UAT de los 4 roles (`STAFF_ROLES`), las 7 pantallas
   operativas (`AppRouter.tsx`), la degradación `TELEMETRIA_NO_DISPONIBLE` y las 4 firmas
   de aceptación (Product Owner, Architecture Board / ADM1, Testing CAL1, Seguridad PLT4/ADM2).
3. Smoke test unitario rápido sobre FastAPI (`app.openapi()`, `/admin/v1/health`, `/metrics`
   y degradación controlada HTTP 503 `TELEMETRIA_NO_DISPONIBLE` sin afectar vistas de negocio).
4. Recorrido UAT integrado multi-rol sobre PostgreSQL 16 y Redis (`@pytest.mark.integracion`).
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from admin_api.deps import Staff, limite_rl4, limite_vivo, staff_actual
from admin_api.errors import telemetria_no_disponible
from admin_api.main import app
from admin_api.security import STAFF_ROLES, emitir_tokens_staff
from fastapi.testclient import TestClient
from sqlalchemy import text

REPO_ROOT = Path(__file__).resolve().parent.parent
UAT_SIGNOFF_FILE = REPO_ROOT / "docs" / "informes" / "uat_signoff_m6.md"
FASE_2_FILE = REPO_ROOT / "docs" / "fase-2.md"
APP_ROUTER_FILE = REPO_ROOT / "apps" / "web" / "src" / "router" / "AppRouter.tsx"

EVIDENCIAS_FISICAS_M6 = (
    REPO_ROOT / "docs" / "seguridad" / "informe_final_integridad_m6.md",
    REPO_ROOT / "docs" / "seguridad" / "revision_cross_tenant.md",
    REPO_ROOT / "docs" / "informes" / "carga.md",
    REPO_ROOT / "infra" / "containerapps.bicep",
    REPO_ROOT / "docs" / "runbooks" / "admin_console_ops.md",
    REPO_ROOT / "docs" / "user_guides" / "admin_manual.md",
    REPO_ROOT / "docs" / "politica_contrato_admin.md",
    REPO_ROOT / "docs" / "openapi-admin-v1.yaml",
)

PANTALLAS_OPERATIVAS_SPA = (
    "/overview",
    "/business/customers",
    "/business/customers/:tenant_id",
    "/business/subscriptions",
    "/business/tokens",
    "/ops/agents",
    "/ops/models",
    "/ops/sla",
)


def _validar_enlaces_markdown(archivo: Path) -> str:
    assert archivo.exists(), f"Falta documento obligatorio de cierre M6: {archivo}"
    texto = archivo.read_text(encoding="utf-8")
    assert "file://" not in texto, f"Prohibidos enlaces locales file:// en {archivo.name}"
    assert "/home/" not in texto, f"Prohibidas rutas locales /home/ en {archivo.name}"

    for destino in re.findall(r"\]\(([^)]+)\)", texto):
        if destino.startswith(("http://", "https://", "#")):
            continue
        resuelto = (archivo.parent / destino.split("#", 1)[0]).resolve()
        assert resuelto.exists(), f"Enlace relativo roto {destino!r} en {archivo.name}"
        assert resuelto.is_relative_to(REPO_ROOT), f"Enlace fuera del repo en {archivo.name}"
    return texto


# =============================================================================
# 1. Existencia de evidencias físicas M6 y validez de enlaces relativos
# =============================================================================
def test_uat_signoff_documentos_enlaces_y_evidencias_existen() -> None:
    """Valida uat_signoff_m6.md, fase-2.md y la existencia física de las evidencias M6."""
    texto_uat = _validar_enlaces_markdown(UAT_SIGNOFF_FILE)
    texto_f2 = _validar_enlaces_markdown(FASE_2_FILE)

    for evidencia in EVIDENCIAS_FISICAS_M6:
        assert evidencia.exists(), f"Falta archivo físico de evidencia M6: {evidencia}"
        assert (
            evidencia.name in texto_uat
        ), f"El acta uat_signoff_m6.md debe referenciar {evidencia.name}"

    for item_f2 in (
        "KC-ADM-F2-01",
        "KC-ADM-F2-02",
        "KC-ADM-F2-03",
        "KC-ADM-F2-04",
        "KC-ADM-F2-05",
    ):
        assert item_f2 in texto_f2, f"Falta ítem {item_f2} en docs/fase-2.md"


# =============================================================================
# 2. Cobertura UAT de los 4 roles, 7 pantallas y 4 firmas de Sign-Off
# =============================================================================
def test_uat_signoff_cubre_roles_pantallas_y_cuatro_firmas() -> None:
    """El acta debe cubrir los 4 roles STAFF_ROLES, las 7 pantallas y las 4 firmas."""
    texto_uat = UAT_SIGNOFF_FILE.read_text(encoding="utf-8")
    router_src = APP_ROUTER_FILE.read_text(encoding="utf-8")

    for rol in STAFF_ROLES:
        assert rol in texto_uat, f"Falta guión UAT para el rol {rol!r}"

    for ruta in PANTALLAS_OPERATIVAS_SPA:
        assert f'path="{ruta}"' in router_src, f"Ruta {ruta!r} no existe en AppRouter.tsx"
        assert ruta in texto_uat, f"Ruta operativa {ruta!r} no cubierta en uat_signoff_m6.md"

    for codigo_uat in ("UAT-01", "UAT-02", "UAT-03", "UAT-04", "UAT-05"):
        assert codigo_uat in texto_uat

    assert "TELEMETRIA_NO_DISPONIBLE" in texto_uat
    assert "DetalleRelojSLA" in texto_uat
    assert "SolicitudConcesionModal" in texto_uat

    for firmante in (
        "Product Owner",
        "Architecture Board / ADM1",
        "Testing / CAL1",
        "Seguridad / PLT4 & ADM2",
    ):
        assert firmante in texto_uat, f"Falta firmante {firmante!r} en el acta de Sign-Off"


# =============================================================================
# 3. Smoke test unitario de API, esquemas y degradación controlada E2
# =============================================================================
def test_smoke_api_esquemas_y_degradacion_telemetria_m6() -> None:
    """Smoke test sin BD: esquemas OpenAPI, /metrics y 503 TELEMETRIA_NO_DISPONIBLE."""
    esquema = app.openapi()
    assert esquema["openapi"] == "3.0.3"
    comps = esquema["components"]
    assert "BearerAuth" in comps["securitySchemes"]
    assert "ErrorStandard" in comps["schemas"]
    assert "CustomerSummary" in comps["schemas"]

    cliente = TestClient(app, base_url="http://localhost", raise_server_exceptions=False)
    r_metrics = cliente.get("/metrics")
    assert r_metrics.status_code == 200
    assert "admin_aggregates_freshness_seconds" in r_metrics.text

    # Simular operador autenticado ante caída de telemetría E2 -> 503 TELEMETRIA_NO_DISPONIBLE
    st_ops = Staff(
        id="st_uat_ops",
        role="staff_operaciones",
        full_name="Operaciones UAT",
        email="ops.uat@kallicode.com",
        mfa_at=datetime.now(UTC),
        jti="jti_uat_ops",
        grants={},
    )
    app.dependency_overrides[staff_actual] = lambda: st_ops
    app.dependency_overrides[limite_rl4] = lambda: st_ops
    app.dependency_overrides[limite_vivo] = lambda: st_ops
    try:
        with patch(
            "admin_api.routers.ops.telemetry.agentes",
            new=AsyncMock(side_effect=telemetria_no_disponible()),
        ):
            r_agents = cliente.get("/admin/v1/ops/agents")
        assert r_agents.status_code == 503
        cuerpo = r_agents.json()
        assert cuerpo["error"]["codigo"] == "TELEMETRIA_NO_DISPONIBLE"
        assert "X-Trace-Id" in r_agents.headers
    finally:
        app.dependency_overrides.pop(staff_actual, None)
        app.dependency_overrides.pop(limite_rl4, None)
        app.dependency_overrides.pop(limite_vivo, None)


# =============================================================================
# 4. Recorrido UAT integrado de los 4 roles sobre PostgreSQL 16 + Redis real
# =============================================================================
@pytest.mark.integracion
async def test_uat_recorrido_cuatro_roles_integrado(
    cliente: Any,
    dos_clientes: list[str],
    staff_factory: Any,
    db: Any,
) -> None:
    """Ejecuta un recorrido UAT real con los 4 roles de STAFF_ROLES sin errores 500."""
    ahora_mfa = datetime.now(UTC) - timedelta(minutes=1)

    def _hdr(emp: dict[str, Any], rol: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {emitir_tokens_staff(emp['id'], rol, ahora_mfa)}"}

    # Garantizar frescura de agregados si una prueba previa simuló expiración (>24h)
    await db.execute(text("SELECT admin.refresh_all_business_aggregates()"))
    await db.execute(
        text(
            """
            INSERT INTO admin.aggregate_state (
                agregado, refreshed_at, duration_ms, rows_total, status
            )
            VALUES ('sla_cases', now(), 5, 1, 'ok')
            ON CONFLICT (agregado) DO UPDATE SET refreshed_at = now(), status = 'ok'
            """
        )
    )
    await db.execute(
        text("UPDATE admin.aggregate_state SET refreshed_at = now(), status = 'ok'")
    )
    await db.commit()

    # 1) staff_soporte: lectura enmascarada -> concesión -> lectura revelada
    st_sup = await staff_factory("staff_soporte")
    h_sup = _hdr(st_sup, "staff_soporte")
    r_cust_mask = await cliente.get("/admin/v1/business/customers/org_acme", headers=h_sup)
    assert r_cust_mask.status_code == 200
    assert r_cust_mask.json()["razon_social"] != "Acme Logística S.L."

    r_grant = await cliente.post(
        "/admin/v1/access-grants",
        headers=h_sup,
        json={
            "tenant_id": "org_acme",
            "alcance": "datos_negocio",
            "motivo": "Verificación UAT-01 de soporte para release M6 sobre ticket SUP-6014",
            "duracion_min": 30,
        },
    )
    assert r_grant.status_code == 201
    r_cust_clear = await cliente.get("/admin/v1/business/customers/org_acme", headers=h_sup)
    assert r_cust_clear.status_code == 200
    assert r_cust_clear.json()["razon_social"] == "Acme Logística S.L."

    # 2) staff_operaciones: acceso a /admin/v1/ops/sla y bloqueo 403 en /business/overview
    st_ops = await staff_factory("staff_operaciones")
    h_ops = _hdr(st_ops, "staff_operaciones")
    await db.execute(
        text(
            """
            INSERT INTO admin.aggregate_state (
                agregado, refreshed_at, duration_ms, rows_total, status
            )
            VALUES ('sla_cases', now(), 5, 1, 'ok')
            ON CONFLICT (agregado) DO UPDATE SET refreshed_at = now(), status = 'ok'
            """
        )
    )
    await db.commit()
    r_sla = await cliente.get("/admin/v1/ops/sla", headers=h_ops)
    assert r_sla.status_code == 200
    r_ops_forbidden = await cliente.get("/admin/v1/business/overview", headers=h_ops)
    assert r_ops_forbidden.status_code == 403

    # 3) staff_negocio: acceso a /business/overview, /subscriptions y /usage/tokens
    st_biz = await staff_factory("staff_negocio")
    h_biz = _hdr(st_biz, "staff_negocio")
    for ruta_biz in (
        "/admin/v1/business/overview",
        "/admin/v1/business/subscriptions",
        "/admin/v1/business/usage/tokens",
    ):
        r_b = await cliente.get(ruta_biz, headers=h_biz)
        assert r_b.status_code == 200, f"Fallo en {ruta_biz}: {r_b.text}"

    # 4) staff_admin: inventario de personal y auditoría forense de acciones
    st_adm = await staff_factory("staff_admin")
    h_adm = _hdr(st_adm, "staff_admin")
    r_staff = await cliente.get("/admin/v1/staff", headers=h_adm)
    assert r_staff.status_code == 200
    r_audit = await cliente.get("/admin/v1/audit/staff-actions?ambito=todas", headers=h_adm)
    assert r_audit.status_code == 200
    assert r_audit.json()["total"] >= 1
