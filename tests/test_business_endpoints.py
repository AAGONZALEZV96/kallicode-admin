"""Pruebas de integración para endpoints backend de negocio (KC-ADM-B3-01).

Cubre:
  1. GET /admin/v1/business/summary: datos agregados, tokens por tier, tendencia y frescura.
  2. Autorización RBAC en /summary (staff_negocio y staff_admin permitidos; otros 403).
  3. GET /admin/v1/business/overview: latencia < 200ms y bloques requeridos.
  4. GET /admin/v1/business/customers: paginación, filtros por plan y estado, frescura.
  5. Enmascaramiento por defecto en /customers (razón social y dominio ofuscados sin concesión).
  6. Revelación condicional en /customers ante concesiones activas por organización.
  7. Denegación categórica a staff_operaciones en /customers (HTTP 403).
  8. Búsqueda por q: identificador libre vs razón social exigiendo concesión.
  9. GET /admin/v1/business/customers/{tenant_id}: ficha 360°, enmascaramiento y revelación.
  10. Detección de organización inexistente en ficha (HTTP 404).
  11. Detección de agregados obsoletos (HTTP 503 AGREGADO_NO_DISPONIBLE).
"""

from __future__ import annotations

import time
from typing import Any

import pytest
import pytest_asyncio
from admin_api.errors import agregado_no_disponible
from admin_workers.main import refrescar_agregados
from sqlalchemy import text


@pytest_asyncio.fixture
async def agregados_frescos(db: Any, dos_clientes: list[str]) -> None:
    """Calcula y refresca los agregados de negocio para disponer de datos frescos."""
    await refrescar_agregados(db)


@pytest_asyncio.fixture
async def concesion_acme(db: Any) -> None:
    """Registra una concesión activa en admin.access_grants para org_acme."""
    await db.execute(
        text("""
        INSERT INTO admin.access_grants (
            id, staff_id, tenant_id, scope, reason, expires_at
        )
        VALUES (
            'gr_org_acme', 'st_prueba', 'org_acme', 'expediente',
            'Incidencia de soporte SUP-1234 justificada',
            now() + interval '1 hour'
        )
        ON CONFLICT (id) DO NOTHING;
        """)
    )
    await db.commit()


# ============================================================= 1. /business/summary
@pytest.mark.integracion
@pytest.mark.asyncio
async def test_summary_responde_con_datos_agregados_y_frescura(
    cliente: Any, como: Any, sin_limite: None, agregados_frescos: None
) -> None:
    """Verifica que /summary devuelva los indicadores ejecutivos consolidados."""
    como("staff_negocio")
    r = await cliente.get("/admin/v1/business/summary")
    assert r.status_code == 200, r.text
    body = r.json()

    assert "mrr_eur" in body
    assert isinstance(body["mrr_eur"], int | float)
    assert body["mrr_eur"] >= 0.0

    assert "clientes_activos" in body
    assert isinstance(body["clientes_activos"], int)
    assert body["clientes_activos"] >= 2

    assert "consumo_tokens_ciclo" in body
    tokens = body["consumo_tokens_ciclo"]
    assert "total" in tokens
    assert "flash" in tokens
    assert "pro" in tokens
    assert "fable" in tokens

    assert "tendencia" in body
    assert "frescura" in body
    assert body["frescura"] is not None


@pytest.mark.integracion
@pytest.mark.asyncio
async def test_summary_autorizacion_negocio_y_admin_ok(
    cliente: Any, como: Any, sin_limite: None, agregados_frescos: None
) -> None:
    """staff_negocio y staff_admin tienen acceso autorizado al resumen."""
    como("staff_negocio")
    r_negocio = await cliente.get("/admin/v1/business/summary")
    assert r_negocio.status_code == 200, r_negocio.text

    como("staff_admin")
    r_admin = await cliente.get("/admin/v1/business/summary")
    assert r_admin.status_code == 200, r_admin.text


@pytest.mark.integracion
@pytest.mark.asyncio
@pytest.mark.parametrize("rol_prohibido", ["staff_soporte", "staff_operaciones"])
async def test_summary_deniega_soporte_y_operaciones_con_403(
    cliente: Any, como: Any, sin_limite: None, agregados_frescos: None, rol_prohibido: str
) -> None:
    """staff_soporte y staff_operaciones no pueden acceder a /summary."""
    como(rol_prohibido)
    r = await cliente.get("/admin/v1/business/summary")
    assert r.status_code == 403, r.text
    assert r.json()["error"]["codigo"] == "ROL_STAFF_INSUFICIENTE"


# ============================================================ 2. /business/overview
@pytest.mark.integracion
@pytest.mark.asyncio
async def test_overview_responde_en_menos_de_200ms_y_con_bloques(
    cliente: Any, como: Any, sin_limite: None, agregados_frescos: None
) -> None:
    """Verifica que /overview responda en < 200ms e incluya todos los bloques."""
    como("staff_negocio")

    t0 = time.perf_counter()
    r = await cliente.get("/admin/v1/business/overview")
    latencia_ms = (time.perf_counter() - t0) * 1000

    assert r.status_code == 200, r.text
    assert latencia_ms < 200.0, f"Latencia excesiva: {latencia_ms:.1f}ms > 200ms"

    body = r.json()
    bloques_esperados = (
        "clientes",
        "ingresos",
        "ingreso_recurrente",
        "consumo",
        "pipeline",
        "frescura",
    )
    for bloque in bloques_esperados:
        assert bloque in body, f"Falta el bloque requerido '{bloque}'"
    assert "mrr_eur" in body


# =========================================================== 3. /business/customers
@pytest.mark.integracion
@pytest.mark.asyncio
async def test_listado_clientes_enmascarado_por_defecto_sin_concesion(
    cliente: Any, como: Any, sin_limite: None, agregados_frescos: None
) -> None:
    """Sin concesión activa, las razones sociales y dominios se devuelven enmascarados."""
    como("staff_soporte")
    r = await cliente.get("/admin/v1/business/customers")
    assert r.status_code == 200, r.text
    body = r.json()

    assert body["total"] >= 2
    assert body["page"] == 1
    assert body["page_size"] == 25
    assert "frescura" in body

    for item in body["items"]:
        assert item["enmascarado"] is True
        assert item["razon_social"] != "Acme Logística S.L."
        assert "••••" in item["razon_social"]
        assert "••••" in item["dominio"]
        assert item["dominio"].endswith(".com")


@pytest.mark.integracion
@pytest.mark.asyncio
async def test_listado_clientes_revelado_con_concesion_activa(
    cliente: Any, como: Any, sin_limite: None, agregados_frescos: None, concesion_acme: None
) -> None:
    """Con concesión activa sobre Acme, solo Acme se revela; Globex sigue enmascarado."""
    como("staff_soporte", grants={"org_acme": ["datos_negocio"]})
    r = await cliente.get("/admin/v1/business/customers")
    assert r.status_code == 200, r.text
    body = r.json()

    filas = {f["tenant_id"]: f for f in body["items"]}
    assert "org_acme" in filas
    assert "org_globex" in filas

    # Acme revelado
    assert filas["org_acme"]["enmascarado"] is False
    assert filas["org_acme"]["razon_social"] == "Acme Logística S.L."
    assert filas["org_acme"]["dominio"] == "acme.com"

    # Globex permanece enmascarado
    assert filas["org_globex"]["enmascarado"] is True
    assert filas["org_globex"]["razon_social"] != "Globex Industrial S.A."
    assert "••••" in filas["org_globex"]["dominio"]


@pytest.mark.integracion
@pytest.mark.asyncio
async def test_listado_clientes_staff_operaciones_recibe_403(
    cliente: Any, como: Any, sin_limite: None, agregados_frescos: None
) -> None:
    """staff_operaciones recibe 403 ROL_STAFF_INSUFFICIENTE al listar clientes."""
    como("staff_operaciones")
    r = await cliente.get("/admin/v1/business/customers")
    assert r.status_code == 403, r.text
    assert r.json()["error"]["codigo"] == "ROL_STAFF_INSUFICIENTE"


@pytest.mark.integracion
@pytest.mark.asyncio
@pytest.mark.parametrize("rol", ["staff_soporte", "staff_negocio", "staff_admin"])
async def test_listado_clientes_roles_permitidos_ok(
    cliente: Any, como: Any, sin_limite: None, agregados_frescos: None, rol: str
) -> None:
    """staff_soporte, staff_negocio y staff_admin pueden acceder a /customers."""
    como(rol)
    r = await cliente.get("/admin/v1/business/customers")
    assert r.status_code == 200, r.text


@pytest.mark.integracion
@pytest.mark.asyncio
async def test_listado_clientes_filtros_plan_y_estado(
    cliente: Any, como: Any, sin_limite: None, agregados_frescos: None
) -> None:
    """Filtrado de clientes por plan y por estado (incluyendo sinónimos amigables)."""
    como("staff_negocio")

    r_plan = await cliente.get("/admin/v1/business/customers", params={"plan": "growth"})
    assert r_plan.status_code == 200, r_plan.text
    for item in r_plan.json()["items"]:
        assert item["plan"] == "growth"

    # Prueba con estado 'activa' y su variante 'activo'
    r_activa = await cliente.get("/admin/v1/business/customers", params={"estado": "activa"})
    assert r_activa.status_code == 200, r_activa.text

    r_activo = await cliente.get("/admin/v1/business/customers", params={"estado": "activo"})
    assert r_activo.status_code == 200, r_activo.text


@pytest.mark.integracion
@pytest.mark.asyncio
async def test_buscar_cliente_por_q_razon_social_exige_concesion(
    cliente: Any, como: Any, sin_limite: None, agregados_frescos: None, concesion_acme: None
) -> None:
    """Búsqueda libre por ID no exige concesión; por texto de nombre sí la exige."""
    como("staff_soporte")

    # Por tenant_id: permitido
    r_id = await cliente.get("/admin/v1/business/customers", params={"q": "org_acme"})
    assert r_id.status_code == 200, r_id.text

    # Por razón social sin concesión: 403 acceso_no_justificado
    r_nom = await cliente.get("/admin/v1/business/customers", params={"q": "Acme"})
    assert r_nom.status_code == 403, r_nom.text
    assert r_nom.json()["error"]["code"] == "acceso_no_justificado"

    # Con concesión sobre Acme: permitido
    como("staff_soporte", grants={"org_acme": ["datos_negocio"]})
    r_nom_ok = await cliente.get("/admin/v1/business/customers", params={"q": "Acme"})
    assert r_nom_ok.status_code == 200, r_nom_ok.text


# ================================================= 4. /business/customers/{tenant_id}
@pytest.mark.integracion
@pytest.mark.asyncio
async def test_ficha_cliente_360_enmascarado_sin_concesion(
    cliente: Any, como: Any, sin_limite: None, agregados_frescos: None
) -> None:
    """La ficha 360 se devuelve enmascarada sin concesión y declara 'enmascarado'."""
    como("staff_soporte")
    r = await cliente.get("/admin/v1/business/customers/org_acme")
    assert r.status_code == 200, r.text
    body = r.json()

    assert body["tenant_id"] == "org_acme"
    assert "frescura" in body
    assert body["razon_social"] != "Acme Logística S.L."
    assert "••••" in body["razon_social"]
    assert "••••" in body["dominio"]
    assert "razon_social" in body["enmascarado"]
    assert "dominio" in body["enmascarado"]

    for bloque in ("suscripcion", "lineas", "actividad", "consumo"):
        assert bloque in body


@pytest.mark.integracion
@pytest.mark.asyncio
async def test_ficha_cliente_360_revelado_con_concesion(
    cliente: Any, como: Any, sin_limite: None, agregados_frescos: None, concesion_acme: None
) -> None:
    """Con concesión de datos de negocio, los campos de identificación se entregan
    en claro. Con alcance expediente, la ficha completa queda revelada.
    """
    como("staff_soporte", grants={"org_acme": ["datos_negocio"]})
    r = await cliente.get("/admin/v1/business/customers/org_acme")
    assert r.status_code == 200, r.text
    body = r.json()

    assert body["razon_social"] == "Acme Logística S.L."
    assert body["dominio"] == "acme.com"
    assert "razon_social" not in body["enmascarado"]
    assert "dominio" not in body["enmascarado"]

    # Con alcance expediente se revela toda la ficha y la lista de enmascarados queda vacía
    como("staff_soporte", grants={"org_acme": ["expediente"]})
    r_exp = await cliente.get("/admin/v1/business/customers/org_acme")
    assert r_exp.status_code == 200, r_exp.text
    assert r_exp.json()["enmascarado"] == []


@pytest.mark.integracion
@pytest.mark.asyncio
async def test_ficha_cliente_inexistente_devuelve_404(
    cliente: Any, como: Any, sin_limite: None, agregados_frescos: None
) -> None:
    """Una organización que no existe devuelve 404."""
    como("staff_soporte")
    r = await cliente.get("/admin/v1/business/customers/org_inexistente")
    assert r.status_code == 404, r.text


@pytest.mark.integracion
@pytest.mark.asyncio
async def test_ficha_cliente_staff_operaciones_recibe_403(
    cliente: Any, como: Any, sin_limite: None, agregados_frescos: None
) -> None:
    """staff_operaciones recibe 403 al solicitar la ficha de un cliente."""
    como("staff_operaciones")
    r = await cliente.get("/admin/v1/business/customers/org_acme")
    assert r.status_code == 403, r.text
    assert r.json()["error"]["codigo"] == "ROL_STAFF_INSUFICIENTE"


# ============================================================ 5. Control de frescura
@pytest.mark.asyncio
async def test_frescura_agregados_obsoleta_devuelve_503(
    cliente: Any, como: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Si la capa agregada está obsoleta o no disponible, los endpoints devuelven 503."""
    como("staff_negocio")

    async def mock_frescura_fallida(*args: Any, **kwargs: Any) -> Any:
        raise agregado_no_disponible("customer_state", 100_000)

    monkeypatch.setattr(
        "admin_api.routers.business.consultar_resumen_negocio", mock_frescura_fallida
    )

    r = await cliente.get("/admin/v1/business/summary")
    assert r.status_code == 503, r.text
    assert r.json()["error"]["code"] == "agregado_no_disponible"
