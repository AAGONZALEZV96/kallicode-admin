"""Suite de Pruebas de Endpoints de Suscripciones y Upgrade Requests (§18.19, §18.20).

Ticket [KC-ADM-B4-01]: Endpoints Backend de Suscripciones y Cambio de Plan.

Verifica:
  1. GET /admin/v1/business/subscriptions:
     - Cobertura HTTP 200 con sobre estándar (items, total, page, pages, frescura).
     - Cálculo de renovación (renueva_el) y días restantes (dias_para_renovacion).
     - Enmascaramiento PII por defecto (A•••• S.L.) y revelación con concesión activa.
     - Registro de auditoría de lecturas (admin.staff_actions) cuando hay concesión.
     - RBAC estricto: negocio y admin -> 200; soporte y operaciones -> 403.
     - Filtros de estado, plan y renueva_en_dias (1..90), validando 422 fuera de rango.
     - Lista blanca de ordenación ALLOWLIST_SUSCRIPCIONES y rechazo 422 ante orden inválido.
  2. GET /admin/v1/business/upgrade-requests:
     - Cobertura HTTP 200 con sobre estándar y estado por defecto 'pendiente'.
     - Ordenación por defecto por antigüedad (solicitud más antigua primero).
     - Cálculo dinámico de antigüedad en horas (antiguedad_h).
     - Filtro por estado y plan_deseado.
     - Lista blanca de ordenación ALLOWLIST_UPGRADE_REQUESTS y rechazo 422 ante orden inválido.
     - Enmascaramiento PII por defecto y revelación selectiva con concesión.
     - Control de acceso RBAC idéntico (negocio/admin -> 200; otros -> 403; anónimo -> 401).
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

pytestmark = pytest.mark.integracion


@pytest_asyncio.fixture
async def datos_suscripciones_y_upgrades(dsn: str, dos_clientes: list[str]) -> None:
    """Siembra datos de suscripciones y solicitudes de upgrade con estado fresco."""
    engine = create_async_engine(
        dsn.replace("postgresql://", "postgresql+asyncpg://"),
        poolclass=NullPool,
    )
    async with AsyncSession(engine) as session:
        # Asegurar estado comercial y fechas de renovación en suscripciones
        await session.execute(
            text("""
            UPDATE core.subscriptions
            SET plan_codigo = 'growth',
                estado = 'activa',
                inicia_el = current_date - 90,
                renueva_el = current_date + 30
            WHERE tenant_id = 'org_acme'
        """)
        )
        await session.execute(
            text("""
            UPDATE core.subscriptions
            SET plan_codigo = 'enterprise',
                estado = 'periodo_gracia',
                inicia_el = current_date - 300,
                renueva_el = current_date + 65
            WHERE tenant_id = 'org_globex'
        """)
        )

        # Sembrar solicitudes de upgrade directamente en la tabla agregada
        await session.execute(
            text("""
            INSERT INTO admin.agg_upgrade_requests
                (solicitud_id, tenant_id, razon_social, plan_actual, plan_deseado,
                 urgente, estado, comentario, solicitado_el, cuota_uso_pct)
            VALUES
                ('upg_acme_1', 'org_acme', 'Acme Logística S.L.', 'growth', 'enterprise',
                 true, 'pendiente', 'Necesidad urgente de más líneas',
                 now() - interval '48 hours', 85.50),
                ('upg_globex_1', 'org_globex', 'Globex Industrial S.A.', 'starter', 'growth',
                 false, 'pendiente', 'Ampliación normal de capacidad',
                 now() - interval '12 hours', 40.00),
                ('upg_acme_old', 'org_acme', 'Acme Logística S.L.', 'enterprise', 'starter',
                 false, 'aprobada', 'Downgrade anterior completado',
                 now() - interval '120 hours', 15.00)
            ON CONFLICT (solicitud_id) DO UPDATE SET
                estado = EXCLUDED.estado,
                solicitado_el = EXCLUDED.solicitado_el,
                urgente = EXCLUDED.urgente
        """)
        )

        # Refrescar agregados y marcar frescura 'ok'
        await session.execute(text("SELECT admin.refresh_customer_state();"))
        await session.execute(
            text("""
            INSERT INTO admin.aggregate_state
                (agregado, status, refreshed_at, rows_total, duration_ms)
            VALUES ('customer_state', 'ok', now(), 2, 10)
            ON CONFLICT (agregado) DO UPDATE SET status = 'ok', refreshed_at = now();
        """)
        )
        await session.execute(
            text("""
            INSERT INTO admin.aggregate_state
                (agregado, status, refreshed_at, rows_total, duration_ms)
            VALUES ('usage_cycle', 'ok', now(), 2, 10)
            ON CONFLICT (agregado) DO UPDATE SET status = 'ok', refreshed_at = now();
        """)
        )
        await session.execute(
            text("""
            INSERT INTO admin.aggregate_state
                (agregado, status, refreshed_at, rows_total, duration_ms)
            VALUES ('upgrade_requests', 'ok', now(), 3, 10)
            ON CONFLICT (agregado) DO UPDATE SET status = 'ok', refreshed_at = now();
        """)
        )
        await session.commit()
    await engine.dispose()


@pytest_asyncio.fixture
async def concesion_acme(db: Any) -> Any:
    """Registra una concesión activa en admin.access_grants para org_acme."""
    await db.execute(
        text("""
        INSERT INTO admin.access_grants (
            id, staff_id, tenant_id, scope, reason, expires_at, revoked_at, revoked_by
        )
        VALUES (
            'gr_org_acme', 'st_prueba', 'org_acme', 'datos_negocio',
            'Incidencia comercial NEG-1234 justificada',
            now() + interval '1 hour',
            NULL, NULL
        )
        ON CONFLICT (id) DO UPDATE
        SET scope = 'datos_negocio',
            expires_at = now() + interval '1 hour',
            revoked_at = NULL,
            revoked_by = NULL;
        """)
    )
    await db.commit()
    yield
    await db.execute(
        text("""
        UPDATE admin.access_grants
        SET revoked_at = now(),
            revoked_by = 'st_prueba',
            revoked_reason = 'Fin de prueba'
        WHERE id = 'gr_org_acme';
        """)
    )
    await db.commit()


# ============================================================ 1. Suscripciones HTTP 200
async def test_subscriptions_listado_con_datos_sembrados(
    cliente: Any, como: Any, sin_limite: None, datos_suscripciones_y_upgrades: None
) -> None:
    """Valida HTTP 200, sobre estándar y campos de suscripción."""
    como("staff_negocio")
    r = await cliente.get("/admin/v1/business/subscriptions")
    assert r.status_code == 200, r.text
    body = r.json()

    # Sobre estándar
    assert "items" in body
    assert "total" in body
    assert "page" in body
    assert "page_size" in body
    assert "pages" in body
    assert "frescura" in body
    assert "alguna_enmascarada" in body
    assert body["total"] >= 2
    assert body["page"] == 1
    assert body["pages"] >= 1

    items = body["items"]
    tenants = [it["tenant_id"] for it in items]
    assert "org_acme" in tenants
    assert "org_globex" in tenants

    item_acme = next(it for it in items if it["tenant_id"] == "org_acme")
    assert item_acme["plan"] == "growth"
    assert item_acme["estado"] == "activa"
    assert item_acme["renueva_el"] is not None
    assert item_acme["dias_para_renovacion"] is not None
    assert isinstance(item_acme["dias_para_renovacion"], int)
    assert item_acme["dias_para_renovacion"] == 30


async def test_subscriptions_calculo_dias_para_renovacion(
    cliente: Any, como: Any, sin_limite: None, datos_suscripciones_y_upgrades: None
) -> None:
    """Verifica el cálculo exacto de días_para_renovacion contra la fecha actual."""
    como("staff_admin")
    r = await cliente.get("/admin/v1/business/subscriptions")
    assert r.status_code == 200
    items = r.json()["items"]

    for it in items:
        renueva_str = it.get("renueva_el")
        dias = it.get("dias_para_renovacion")
        if renueva_str:
            f_renueva = date.fromisoformat(renueva_str)
            dias_esperados = (f_renueva - datetime.now(UTC).date()).days
            assert dias == dias_esperados


async def test_subscriptions_filtros_estado_y_plan(
    cliente: Any, como: Any, sin_limite: None, datos_suscripciones_y_upgrades: None
) -> None:
    """Valida filtrado combinado por estado y plan."""
    como("staff_negocio")

    # Filtro por estado activa
    r_act = await cliente.get("/admin/v1/business/subscriptions", params={"estado": "activa"})
    assert r_act.status_code == 200
    items_act = r_act.json()["items"]
    assert len(items_act) >= 1
    for it in items_act:
        assert it["estado"] == "activa"

    # Filtro por plan growth
    r_plan = await cliente.get("/admin/v1/business/subscriptions", params={"plan": "growth"})
    assert r_plan.status_code == 200
    items_plan = r_plan.json()["items"]
    assert len(items_plan) >= 1
    for it in items_plan:
        assert it["plan"] == "growth"

    # Filtro por periodo_gracia
    r_gracia = await cliente.get(
        "/admin/v1/business/subscriptions", params={"estado": "periodo_gracia"}
    )
    assert r_gracia.status_code == 200
    items_gracia = r_gracia.json()["items"]
    assert len(items_gracia) >= 1
    assert items_gracia[0]["tenant_id"] == "org_globex"


async def test_subscriptions_filtro_renueva_en_dias(
    cliente: Any, como: Any, sin_limite: None, datos_suscripciones_y_upgrades: None
) -> None:
    """Valida filtrado por ventana de días de renovación (1..90)."""
    como("staff_negocio")

    # Ventana de 45 días: incluye Acme (30 días), excluye Globex (65 días)
    r45 = await cliente.get("/admin/v1/business/subscriptions", params={"renueva_en_dias": 45})
    assert r45.status_code == 200
    items45 = r45.json()["items"]
    tenants45 = [it["tenant_id"] for it in items45]
    assert "org_acme" in tenants45
    assert "org_globex" not in tenants45

    # Ventana de 90 días: incluye tanto Acme (30 días) como Globex (65 días)
    r90 = await cliente.get("/admin/v1/business/subscriptions", params={"renueva_en_dias": 90})
    assert r90.status_code == 200
    tenants90 = [it["tenant_id"] for it in r90.json()["items"]]
    assert "org_acme" in tenants90
    assert "org_globex" in tenants90

    # Ventana de 10 días: ninguna suscripción debe entrar
    r10 = await cliente.get("/admin/v1/business/subscriptions", params={"renueva_en_dias": 10})
    assert r10.status_code == 200
    assert len(r10.json()["items"]) == 0


async def test_subscriptions_renueva_en_dias_fuera_de_rango_devuelve_422(
    cliente: Any, como: Any, sin_limite: None
) -> None:
    """Valida que valores de renueva_en_dias menores a 1 o mayores a 90 devuelvan 422."""
    como("staff_negocio")

    r_cero = await cliente.get(
        "/admin/v1/business/subscriptions", params={"renueva_en_dias": 0}
    )
    assert r_cero.status_code == 422
    assert r_cero.json()["error"]["codigo"] == "VALIDACION_ENTRADA"

    r_alto = await cliente.get(
        "/admin/v1/business/subscriptions", params={"renueva_en_dias": 91}
    )
    assert r_alto.status_code == 422
    assert r_alto.json()["error"]["codigo"] == "VALIDACION_ENTRADA"


async def test_subscriptions_estado_invalido_devuelve_422(
    cliente: Any, como: Any, sin_limite: None
) -> None:
    """Un estado fuera del catálogo _ESTADOS_SUS devuelve HTTP 422."""
    como("staff_negocio")
    r = await cliente.get(
        "/admin/v1/business/subscriptions", params={"estado": "estado_inventado"}
    )
    assert r.status_code == 422
    assert r.json()["error"]["codigo"] == "VALIDACION_ENTRADA"


# ============================================================ 2. Allowlist y Ordenación
async def test_subscriptions_allowlist_ordenacion(
    cliente: Any, como: Any, sin_limite: None, datos_suscripciones_y_upgrades: None
) -> None:
    """Valida columnas permitidas en ALLOWLIST_SUSCRIPCIONES y rechazo 422 de inválidas."""
    como("staff_negocio")

    # Columnas permitidas
    for sort_param in (
        "renovacion-asc",
        "renovacion-desc",
        "importe-asc",
        "importe-desc",
        "nombre-asc",
        "razon_social-desc",
        "tenant_id-asc",
        "plan-desc",
        "estado-asc",
    ):
        r = await cliente.get("/admin/v1/business/subscriptions", params={"sort": sort_param})
        assert r.status_code == 200, f"Fallo en sort: {sort_param} - {r.text}"
        assert "items" in r.json()

    # Columnas no permitidas devuelven 422
    for sort_inv in ("password-asc", "token-desc", "campo_falso-asc", "invalido"):
        r_inv = await cliente.get("/admin/v1/business/subscriptions", params={"sort": sort_inv})
        assert r_inv.status_code == 422
        assert r_inv.json()["error"]["codigo"] == "VALIDACION_ENTRADA"


# ============================================================ 3. Enmascaramiento y Concesión
async def test_subscriptions_enmascaramiento_por_defecto_y_concesion(
    cliente: Any,
    como: Any,
    sin_limite: None,
    db: Any,
    datos_suscripciones_y_upgrades: None,
    concesion_acme: None,
) -> None:
    """Sin concesión la razón social está ofuscada; con concesión activa se muestra en claro."""
    # 1. Sin concesión activa
    como("staff_negocio")
    r1 = await cliente.get("/admin/v1/business/subscriptions")
    assert r1.status_code == 200
    items1 = r1.json()["items"]
    assert r1.json()["alguna_enmascarada"] is True

    acme1 = next(it for it in items1 if it["tenant_id"] == "org_acme")
    assert acme1["razon_social"] != "Acme Logística S.L."
    assert "••••" in acme1["razon_social"]
    assert acme1["enmascarado"] is True

    globex1 = next(it for it in items1 if it["tenant_id"] == "org_globex")
    assert globex1["razon_social"] != "Globex Industrial S.A."
    assert "••••" in globex1["razon_social"]
    assert globex1["enmascarado"] is True

    # 2. Con concesión activa sobre org_acme
    como("staff_negocio", grants={"org_acme": ["datos_negocio"]})
    r2 = await cliente.get("/admin/v1/business/subscriptions")
    assert r2.status_code == 200
    items2 = r2.json()["items"]

    acme2 = next(it for it in items2 if it["tenant_id"] == "org_acme")
    assert acme2["razon_social"] == "Acme Logística S.L."
    assert acme2["enmascarado"] is False

    # Globex permanece enmascarada (no-fuga cross-tenant)
    globex2 = next(it for it in items2 if it["tenant_id"] == "org_globex")
    assert globex2["razon_social"] != "Globex Industrial S.A."
    assert "••••" in globex2["razon_social"]
    assert globex2["enmascarado"] is True

    # 3. Verificar que se haya registrado la lectura en auditoría
    res_audit = await db.execute(
        text("""
        SELECT action, tenant_id, endpoint FROM admin.staff_actions
        WHERE endpoint = 'GET /admin/v1/business/subscriptions'
        ORDER BY occurred_at DESC LIMIT 5
    """)
    )
    rows_audit = res_audit.fetchall()
    assert len(rows_audit) >= 1
    assert any(ra.tenant_id == "org_acme" for ra in rows_audit)


# ============================================================ 4. RBAC y Autorización
@pytest.mark.parametrize("rol", ["staff_negocio", "staff_admin"])
async def test_subscriptions_roles_autorizados_200(
    cliente: Any, como: Any, sin_limite: None, datos_suscripciones_y_upgrades: None, rol: str
) -> None:
    """staff_negocio y staff_admin tienen permiso de acceso."""
    como(rol)
    r = await cliente.get("/admin/v1/business/subscriptions")
    assert r.status_code == 200


@pytest.mark.parametrize("rol", ["staff_soporte", "staff_operaciones"])
async def test_subscriptions_roles_denegados_403(
    cliente: Any, como: Any, sin_limite: None, rol: str
) -> None:
    """staff_soporte y staff_operaciones reciben HTTP 403 ROL_STAFF_INSUFICIENTE."""
    como(rol)
    r = await cliente.get("/admin/v1/business/subscriptions")
    assert r.status_code == 403
    assert r.json()["error"]["codigo"] == "ROL_STAFF_INSUFICIENTE"


async def test_subscriptions_sin_autenticacion_devuelve_401(cliente: Any) -> None:
    """Peticiones sin credenciales son rechazadas con 401."""
    r = await cliente.get("/admin/v1/business/subscriptions")
    assert r.status_code == 401


# ============================================================ 5. Upgrade Requests HTTP 200
async def test_upgrade_requests_listado_y_orden_por_defecto(
    cliente: Any, como: Any, sin_limite: None, datos_suscripciones_y_upgrades: None
) -> None:
    """Valida HTTP 200, orden más antigua primero y cálculo de antigüedad en horas."""
    como("staff_negocio")
    r = await cliente.get("/admin/v1/business/upgrade-requests")
    assert r.status_code == 200, r.text
    body = r.json()

    assert "items" in body
    assert "total" in body
    assert "page" in body
    assert "page_size" in body
    assert "pages" in body
    assert "frescura" in body

    # Por defecto estado="pendiente": debe devolver upg_acme_1 (48h) y upg_globex_1 (12h)
    items = body["items"]
    assert len(items) == 2
    for it in items:
        assert it["estado"] == "pendiente"
        assert it["antiguedad_h"] is not None
        assert isinstance(it["antiguedad_h"], int)
        assert it["antiguedad_h"] >= 1

    # Orden más antigua primero: upg_acme_1 (~48h) antes de upg_globex_1 (~12h)
    assert items[0]["solicitud_id"] == "upg_acme_1"
    assert items[1]["solicitud_id"] == "upg_globex_1"
    assert items[0]["antiguedad_h"] > items[1]["antiguedad_h"]
    assert items[0]["urgente"] is True
    assert items[1]["urgente"] is False


async def test_upgrade_requests_filtros_estado_y_plan_deseado(
    cliente: Any, como: Any, sin_limite: None, datos_suscripciones_y_upgrades: None
) -> None:
    """Valida filtros específicos por estado y plan_deseado."""
    como("staff_admin")

    # Filtrar por estado aprobada (upg_acme_old)
    r_apr = await cliente.get(
        "/admin/v1/business/upgrade-requests", params={"estado": "aprobada"}
    )
    assert r_apr.status_code == 200
    items_apr = r_apr.json()["items"]
    assert len(items_apr) == 1
    assert items_apr[0]["solicitud_id"] == "upg_acme_old"
    assert items_apr[0]["plan_deseado"] == "starter"

    # Filtrar por plan_deseado enterprise
    r_ent = await cliente.get(
        "/admin/v1/business/upgrade-requests",
        params={"estado": "pendiente", "plan_deseado": "enterprise"},
    )
    assert r_ent.status_code == 200
    items_ent = r_ent.json()["items"]
    assert len(items_ent) == 1
    assert items_ent[0]["solicitud_id"] == "upg_acme_1"


async def test_upgrade_requests_allowlist_ordenacion(
    cliente: Any, como: Any, sin_limite: None, datos_suscripciones_y_upgrades: None
) -> None:
    """Valida columnas permitidas en ALLOWLIST_UPGRADE_REQUESTS y rechazo 422 de inválidas."""
    como("staff_negocio")

    # Columnas permitidas
    for sort_param in (
        "antiguedad-asc",
        "antiguedad-desc",
        "urgente-desc",
        "solicitado_el-asc",
        "plan_deseado-desc",
        "tenant_id-asc",
    ):
        r = await cliente.get(
            "/admin/v1/business/upgrade-requests", params={"sort": sort_param}
        )
        assert r.status_code == 200, f"Fallo en sort: {sort_param} - {r.text}"
        assert "items" in r.json()

    # Columnas inválidas devuelven 422
    for sort_inv in ("password-asc", "invalido-desc", "malicioso"):
        r_inv = await cliente.get(
            "/admin/v1/business/upgrade-requests", params={"sort": sort_inv}
        )
        assert r_inv.status_code == 422
        assert r_inv.json()["error"]["codigo"] == "VALIDACION_ENTRADA"


async def test_upgrade_requests_enmascaramiento_por_defecto_y_concesion(
    cliente: Any,
    como: Any,
    sin_limite: None,
    db: Any,
    datos_suscripciones_y_upgrades: None,
    concesion_acme: None,
) -> None:
    """Sin concesión la razón social en upgrade_requests está ofuscada;
    con concesión activa se muestra en claro.
    """
    # 1. Sin concesión
    como("staff_negocio")
    r1 = await cliente.get("/admin/v1/business/upgrade-requests")
    assert r1.status_code == 200
    items1 = r1.json()["items"]
    for it in items1:
        assert "••••" in it["razon_social"]
        assert it["enmascarado"] is True

    # 2. Con concesión activa sobre org_acme
    como("staff_negocio", grants={"org_acme": ["datos_negocio"]})
    r2 = await cliente.get("/admin/v1/business/upgrade-requests")
    assert r2.status_code == 200
    items2 = r2.json()["items"]

    acme = next(it for it in items2 if it["tenant_id"] == "org_acme")
    assert acme["razon_social"] == "Acme Logística S.L."
    assert acme["enmascarado"] is False

    globex = next(it for it in items2 if it["tenant_id"] == "org_globex")
    assert "••••" in globex["razon_social"]
    assert globex["enmascarado"] is True

    # 3. Auditoría de lecturas
    res_audit = await db.execute(
        text("""
        SELECT action, tenant_id, endpoint FROM admin.staff_actions
        WHERE endpoint = 'GET /admin/v1/business/upgrade-requests'
        ORDER BY occurred_at DESC LIMIT 5
    """)
    )
    rows_audit = res_audit.fetchall()
    assert len(rows_audit) >= 1
    assert any(ra.tenant_id == "org_acme" for ra in rows_audit)


@pytest.mark.parametrize("rol", ["staff_negocio", "staff_admin"])
async def test_upgrade_requests_roles_autorizados_200(
    cliente: Any, como: Any, sin_limite: None, datos_suscripciones_y_upgrades: None, rol: str
) -> None:
    """staff_negocio y staff_admin tienen acceso autorizado a upgrade_requests."""
    como(rol)
    r = await cliente.get("/admin/v1/business/upgrade-requests")
    assert r.status_code == 200


@pytest.mark.parametrize("rol", ["staff_soporte", "staff_operaciones"])
async def test_upgrade_requests_roles_denegados_403(
    cliente: Any, como: Any, sin_limite: None, rol: str
) -> None:
    """staff_soporte y staff_operaciones reciben HTTP 403 ROL_STAFF_INSUFICIENTE."""
    como(rol)
    r = await cliente.get("/admin/v1/business/upgrade-requests")
    assert r.status_code == 403
    assert r.json()["error"]["codigo"] == "ROL_STAFF_INSUFICIENTE"


async def test_upgrade_requests_sin_autenticacion_devuelve_401(cliente: Any) -> None:
    """Peticiones no autenticadas devuelven 401."""
    r = await cliente.get("/admin/v1/business/upgrade-requests")
    assert r.status_code == 401
