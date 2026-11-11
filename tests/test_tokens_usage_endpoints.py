"""Suite de Pruebas de Endpoints de Consumo de Tokens (§18.21).

Ticket [KC-ADM-B4-03]: Endpoints Backend de Consumo de Tokens por Cliente, Tier y Periodo.

Verifica de forma rigurosa y exhaustiva:
  1. GET /admin/v1/business/usage/tokens:
     - Cobertura HTTP 200 con sobre estándar (items, total, page, pages, frescura).
     - Validación de todos los campos analíticos devueltos por registro en modo 'cliente':
       tenant_id, razon_social, plan, tokens_input/tokens_in, tokens_output/tokens_out,
       tokens_total, por_tier (flash, pro, fable), coste_estimado_eur/coste,
       cuota_asignada/umbral, porcentaje_consumido/cuota_pct, loc_procesadas/loc_consumidas,
       cuadra_con_facturacion, enmascarado.
     - Resumen agregado superior ('resumen' y 'totales'):
       total_tokens, coste_consolidado, porcentaje_medio_cuota, moneda.
     - Enmascaramiento PII por defecto (A•••• S.L.) y revelación con concesión
       activa en admin.access_grants.
     - Auditoría append-only inmutable en admin.staff_actions al revelar datos en claro.
     - Filtros de periodo: mes_actual, mes_anterior, trimestre, ano
       (y retrocompatibilidad con ciclo AAAA-MM).
     - Validación estricta con HTTP 422 ante periodo inválido.
     - Filtros por tier y plan comercial: starter, growth, enterprise, todos;
       y rechazo 422 ante plan inválido.
     - Filtro por tenant_id específico.
     - Lista blanca de ordenación ALLOWLIST_USAGE_TOKENS (tokens_in, tokens_out,
       tokens_total, coste_eur, loc_consumidas, cuota_pct) y rechazo 422 ante orden
       indocumentado.
     - Control de acceso RBAC estricto: negocio y admin -> 200; soporte y operaciones -> 403;
       anónimo -> 401.
     - Agrupaciones alternativas: agrupar_por=tier y agrupar_por=dia, y rechazo 422
       ante agrupación inválida.
     - Detección de descuadre contra facturación (core.usage_cycles).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

pytestmark = pytest.mark.integracion


@pytest_asyncio.fixture
async def datos_consumo_tokens(dsn: str, dos_clientes: list[str]) -> None:
    """Siembra datos preagregados y de facturación en múltiples ciclos y días."""
    engine = create_async_engine(
        dsn.replace("postgresql://", "postgresql+asyncpg://"),
        poolclass=NullPool,
    )
    ahora = datetime.now(UTC)
    ciclo_actual = ahora.strftime("%Y-%m")

    # Calcular mes anterior
    if ahora.month == 1:
        ciclo_anterior = f"{ahora.year - 1}-12"
    else:
        ciclo_anterior = f"{ahora.year}-{ahora.month - 1:02d}"

    async with AsyncSession(engine) as session:
        # 1. Configurar organizaciones y suscripciones
        await session.execute(
            text(
                """
            UPDATE core.organizations
            SET nombre = 'Acme Logística S.L.'
            WHERE id = 'org_acme'
        """
            )
        )
        await session.execute(
            text(
                """
            UPDATE core.organizations
            SET nombre = 'Globex Industrial S.A.'
            WHERE id = 'org_globex'
        """
            )
        )
        await session.execute(
            text(
                """
            UPDATE core.subscriptions
            SET plan_codigo = 'growth', estado = 'activa'
            WHERE tenant_id = 'org_acme'
        """
            )
        )
        await session.execute(
            text(
                """
            UPDATE core.subscriptions
            SET plan_codigo = 'enterprise', estado = 'activa'
            WHERE tenant_id = 'org_globex'
        """
            )
        )

        # 2. Sembrar agg_customer_state para el join con razon_social y plan
        await session.execute(
            text(
                """
            INSERT INTO admin.agg_customer_state (
                tenant_id, razon_social, plan_codigo, suscripcion_estado,
                inicia_el, renueva_el, importe_mes, moneda, alta_el, actualizado_en
            )
            VALUES
                ('org_acme', 'Acme Logística S.L.', 'growth', 'activa',
                 current_date - 120, current_date + 30, 299.00, 'EUR',
                 now() - interval '120 days', now()),
                ('org_globex', 'Globex Industrial S.A.', 'enterprise', 'activa',
                 current_date - 240, current_date + 60, 999.00, 'EUR',
                 now() - interval '240 days', now())
            ON CONFLICT (tenant_id) DO UPDATE SET
                razon_social = EXCLUDED.razon_social,
                plan_codigo = EXCLUDED.plan_codigo,
                suscripcion_estado = EXCLUDED.suscripcion_estado,
                actualizado_en = now();
        """
            )
        )

        # 3. Sembrar facturación real en core.usage_cycles para validar cuadre
        await session.execute(
            text(
                f"""
            INSERT INTO core.usage_cycles (tenant_id, ciclo, loc_consumidas, umbral)
            VALUES
                ('org_acme', '{ciclo_actual}', 5000, 'normal'),
                ('org_acme', '{ciclo_anterior}', 4000, 'normal'),
                ('org_globex', '{ciclo_actual}', 22000, 'normal'),
                ('org_globex', '{ciclo_anterior}', 18000, 'normal')
            ON CONFLICT (tenant_id, ciclo) DO UPDATE SET
                loc_consumidas = EXCLUDED.loc_consumidas,
                umbral = EXCLUDED.umbral;
        """
            )
        )

        # 4. Sembrar admin.agg_usage_cycle
        await session.execute(
            text(
                f"""
            INSERT INTO admin.agg_usage_cycle (
                tenant_id, ciclo, loc_consumidas, umbral, cuota_pct,
                tokens_in, tokens_out, tokens_flash, tokens_pro, tokens_fable,
                coste, moneda
            )
            VALUES
                ('org_acme', '{ciclo_actual}', 5000, 10000, 50.00,
                 100000, 25000, 80000, 45000, 0,
                 15.50, 'EUR'),
                ('org_acme', '{ciclo_anterior}', 4000, 10000, 40.00,
                 80000, 20000, 70000, 30000, 0,
                 12.00, 'EUR'),
                ('org_globex', '{ciclo_actual}', 22000, 25000, 88.00,
                 300000, 75000, 200000, 150000, 25000,
                 55.00, 'EUR'),
                ('org_globex', '{ciclo_anterior}', 18000, 25000, 72.00,
                 250000, 60000, 180000, 120000, 10000,
                 45.00, 'EUR')
            ON CONFLICT (tenant_id, ciclo) DO UPDATE SET
                loc_consumidas = EXCLUDED.loc_consumidas,
                umbral = EXCLUDED.umbral,
                cuota_pct = EXCLUDED.cuota_pct,
                tokens_in = EXCLUDED.tokens_in,
                tokens_out = EXCLUDED.tokens_out,
                tokens_flash = EXCLUDED.tokens_flash,
                tokens_pro = EXCLUDED.tokens_pro,
                tokens_fable = EXCLUDED.tokens_fable,
                coste = EXCLUDED.coste,
                moneda = EXCLUDED.moneda;
        """
            )
        )

        # 5. Sembrar admin.agg_tokens_daily para agrupaciones por tier y día
        await session.execute(
            text(
                """
            INSERT INTO admin.agg_tokens_daily (
                dia, tenant_id, tier, modelo, etapa, tokens_in, tokens_out, coste
            )
            VALUES
                (current_date, 'org_acme', 'flash', 'gemini-1.5-flash',
                 'gen', 60000, 15000, 7.50),
                (current_date, 'org_acme', 'pro', 'gemini-1.5-pro',
                 'gen', 40000, 10000, 8.00),
                (current_date, 'org_globex', 'flash', 'gemini-1.5-flash',
                 'gen', 120000, 30000, 15.00),
                (current_date, 'org_globex', 'pro', 'gemini-1.5-pro',
                 'gen', 100000, 25000, 20.00),
                (current_date, 'org_globex', 'fable', 'fable-v1',
                 'gen', 80000, 20000, 20.00),
                (current_date - 1, 'org_acme', 'flash', 'gemini-1.5-flash',
                 'gen', 30000, 5000, 3.50)
            ON CONFLICT (dia, tenant_id, tier, modelo, etapa) DO UPDATE SET
                tokens_in = EXCLUDED.tokens_in,
                tokens_out = EXCLUDED.tokens_out,
                coste = EXCLUDED.coste;
        """
            )
        )

        # 6. Actualizar aggregate_state para asegurar frescura declarada 'ok'
        await session.execute(
            text(
                """
            INSERT INTO admin.aggregate_state
                (agregado, status, refreshed_at, rows_total, duration_ms)
            VALUES
                ('usage_cycle', 'ok', now(), 4, 15),
                ('tokens_daily', 'ok', now(), 6, 20),
                ('customer_state', 'ok', now(), 2, 10)
            ON CONFLICT (agregado) DO UPDATE SET
                status = 'ok',
                refreshed_at = now();
        """
            )
        )
        await session.commit()
    await engine.dispose()


@pytest_asyncio.fixture
async def concesion_tokens_acme(db: Any) -> Any:
    """Registra una concesión activa en admin.access_grants para org_acme."""
    await db.execute(
        text(
            """
        UPDATE admin.access_grants
        SET revoked_at = now(),
            revoked_by = 'st_prueba',
            revoked_reason = 'Limpieza previa test'
        WHERE staff_id = 'st_prueba' AND tenant_id = 'org_acme'
          AND revoked_at IS NULL;
        """
        )
    )
    await db.execute(
        text(
            """
        INSERT INTO admin.access_grants (
            id, staff_id, tenant_id, scope, reason, expires_at, revoked_at, revoked_by
        )
        VALUES (
            'gr_org_acme', 'st_prueba', 'org_acme', 'datos_negocio',
            'Auditoría y análisis de consumo de tokens autorizado',
            now() + interval '1 hour',
            NULL, NULL
        )
        ON CONFLICT (id) DO UPDATE
        SET scope = 'datos_negocio',
            expires_at = now() + interval '1 hour',
            revoked_at = NULL,
            revoked_by = NULL;
        """
        )
    )
    await db.commit()
    yield
    await db.execute(
        text(
            """
        UPDATE admin.access_grants
        SET revoked_at = now(),
            revoked_by = 'st_prueba',
            revoked_reason = 'Fin de prueba'
        WHERE id = 'gr_org_acme';
        """
        )
    )
    await db.commit()


# ==============================================================================
# 1. Cobertura HTTP 200 y Sobre Estándar
# ==============================================================================


async def test_usage_tokens_cobertura_200_sobre_estandar(
    cliente: Any, como: Any, sin_limite: None, datos_consumo_tokens: None
) -> None:
    """Valida HTTP 200, sobre estándar paginado y presencia de todos los campos analíticos."""
    como("staff_negocio")
    r = await cliente.get("/admin/v1/business/usage/tokens")
    assert r.status_code == 200, r.text
    body = r.json()

    # 1. Validar campos estructurales del sobre
    assert "items" in body
    assert "total" in body
    assert "page" in body
    assert "page_size" in body
    assert "pages" in body
    assert "frescura" in body
    assert "ciclo" in body
    assert "periodo" in body
    assert "totales" in body
    assert "resumen" in body
    assert "cuadra_con_facturacion" in body
    assert "alguna_enmascarada" in body

    assert body["total"] >= 2
    assert body["page"] == 1
    assert body["pages"] >= 1
    assert body["periodo"] == "mes_actual"

    # 2. Validar estructura completa de cada elemento (modo 'cliente')
    items = body["items"]
    tenants = [it["tenant_id"] for it in items]
    assert "org_acme" in tenants
    assert "org_globex" in tenants

    item_acme = next(it for it in items if it["tenant_id"] == "org_acme")
    assert item_acme["plan"] == "growth"
    assert item_acme["tokens_in"] == 100000
    assert item_acme["tokens_input"] == 100000
    assert item_acme["tokens_out"] == 25000
    assert item_acme["tokens_output"] == 25000
    assert item_acme["tokens_total"] == 125000
    assert isinstance(item_acme["por_tier"], dict)
    assert item_acme["por_tier"]["flash"] == 80000
    assert item_acme["por_tier"]["pro"] == 45000
    assert item_acme["por_tier"]["fable"] == 0
    assert item_acme["coste"] == 15.50
    assert item_acme["coste_estimado_eur"] == 15.50
    assert item_acme["loc_consumidas"] == 5000
    assert item_acme["loc_procesadas"] == 5000
    assert item_acme["umbral"] == 10000
    assert item_acme["cuota_asignada"] == 10000
    assert item_acme["cuota_pct"] == 50.00
    assert item_acme["porcentaje_consumido"] == 50.00
    assert item_acme["cuadra_con_facturacion"] is True
    assert item_acme["enmascarado"] is True


# ==============================================================================
# 2. Resumen Agregado Superior ('resumen' y 'totales')
# ==============================================================================


async def test_usage_tokens_resumen_agregado_superior(
    cliente: Any, como: Any, sin_limite: None, datos_consumo_tokens: None
) -> None:
    """Verifica el cálculo de los totales agregados superiores en el bloque resumen."""
    como("staff_negocio")
    r = await cliente.get("/admin/v1/business/usage/tokens", params={"periodo": "mes_actual"})
    assert r.status_code == 200
    body = r.json()

    resumen = body["resumen"]
    totales = body["totales"]

    # Acme: 125.000 tokens, 15.50 EUR, 50% cuota
    # Globex: 375.000 tokens, 55.00 EUR, 88% cuota
    # Total esperado: 500.000 tokens, 70.50 EUR, (50 + 88) / 2 = 69%
    assert resumen["total_tokens"] == 500000
    assert resumen["tokens_total"] == 500000
    assert resumen["coste_consolidado"] == 70.50
    assert resumen["coste_total_eur"] == 70.50
    assert resumen["porcentaje_medio_cuota"] == 69.00
    assert resumen["cuota_consumo_media_pct"] == 69.00
    assert resumen["moneda"] == "EUR"

    # Compatibilidad con totales
    assert totales["tokens"] == 500000
    assert totales["coste"] == 70.50
    assert totales["moneda"] == "EUR"


# ==============================================================================
# 3. Enmascaramiento PII y Auditoría Append-Only
# ==============================================================================


async def test_usage_tokens_enmascaramiento_por_defecto_y_revelacion_con_concesion(
    cliente: Any,
    como: Any,
    sin_limite: None,
    datos_consumo_tokens: None,
    concesion_tokens_acme: None,
    db: Any,
) -> None:
    """Valida enmascaramiento por defecto, revelación con concesión y auditoría append-only."""
    # 1. Sin concesión: ambas organizaciones enmascaradas
    como("staff_negocio")
    r1 = await cliente.get("/admin/v1/business/usage/tokens")
    assert r1.status_code == 200
    body1 = r1.json()
    assert body1["alguna_enmascarada"] is True

    acme1 = next(it for it in body1["items"] if it["tenant_id"] == "org_acme")
    assert acme1["razon_social"] != "Acme Logística S.L."
    assert "••••" in acme1["razon_social"]
    assert acme1["enmascarado"] is True

    globex1 = next(it for it in body1["items"] if it["tenant_id"] == "org_globex")
    assert globex1["razon_social"] != "Globex Industrial S.A."
    assert "••••" in globex1["razon_social"]
    assert globex1["enmascarado"] is True

    # 2. Con concesión activa sobre org_acme
    como("staff_negocio", grants={"org_acme": ["datos_negocio"]})
    r2 = await cliente.get("/admin/v1/business/usage/tokens")
    assert r2.status_code == 200, r2.text
    body2 = r2.json()

    acme2 = next(it for it in body2["items"] if it["tenant_id"] == "org_acme")
    assert acme2["razon_social"] == "Acme Logística S.L."
    assert acme2["enmascarado"] is False

    # Globex permanece enmascarada (aislamiento estricto cross-tenant)
    globex2 = next(it for it in body2["items"] if it["tenant_id"] == "org_globex")
    assert globex2["razon_social"] != "Globex Industrial S.A."
    assert "••••" in globex2["razon_social"]
    assert globex2["enmascarado"] is True

    # 3. Comprobar que la lectura se registró en admin.staff_actions
    res_audit = await db.execute(
        text(
            """
        SELECT action, tenant_id, endpoint FROM admin.staff_actions
        WHERE endpoint = 'GET /admin/v1/business/usage/tokens'
        ORDER BY occurred_at DESC LIMIT 5
    """
        )
    )
    rows_audit = res_audit.fetchall()
    assert len(rows_audit) >= 1
    assert any(ra.tenant_id == "org_acme" for ra in rows_audit)


# ==============================================================================
# 4. Filtros de Periodo y Ciclo
# ==============================================================================


async def test_usage_tokens_filtros_periodo(
    cliente: Any, como: Any, sin_limite: None, datos_consumo_tokens: None
) -> None:
    """Valida los filtros periodo=mes_actual, mes_anterior, trimestre, ano y rechazo 422."""
    como("staff_negocio")

    # Mes actual
    r_act = await cliente.get(
        "/admin/v1/business/usage/tokens", params={"periodo": "mes_actual"}
    )
    assert r_act.status_code == 200
    assert r_act.json()["resumen"]["total_tokens"] == 500000

    # Mes anterior (Acme: 100.000 + Globex: 310.000 = 410.000 tokens)
    r_ant = await cliente.get(
        "/admin/v1/business/usage/tokens", params={"periodo": "mes_anterior"}
    )
    assert r_ant.status_code == 200
    assert r_ant.json()["resumen"]["total_tokens"] == 410000

    # Trimestre (incluye ambos ciclos: 500.000 + 410.000 = 910.000 tokens)
    r_tri = await cliente.get(
        "/admin/v1/business/usage/tokens", params={"periodo": "trimestre"}
    )
    assert r_tri.status_code == 200
    assert r_tri.json()["resumen"]["total_tokens"] == 910000

    # Año (incluye ambos ciclos en el año actual)
    r_ano = await cliente.get("/admin/v1/business/usage/tokens", params={"periodo": "ano"})
    assert r_ano.status_code == 200
    assert r_ano.json()["resumen"]["total_tokens"] == 910000

    # Periodo inválido -> HTTP 422
    r_err = await cliente.get(
        "/admin/v1/business/usage/tokens", params={"periodo": "periodo_invalido"}
    )
    assert r_err.status_code == 422
    assert r_err.json()["error"]["codigo"] == "VALIDACION_ENTRADA"


async def test_usage_tokens_retrocompatibilidad_ciclo(
    cliente: Any, como: Any, sin_limite: None, datos_consumo_tokens: None
) -> None:
    """Valida soporte retrocompatible con el parámetro ciclo=AAAA-MM."""
    como("staff_negocio")
    ahora = datetime.now(UTC)
    ciclo_actual = ahora.strftime("%Y-%m")

    r = await cliente.get("/admin/v1/business/usage/tokens", params={"ciclo": ciclo_actual})
    assert r.status_code == 200
    body = r.json()
    assert body["ciclo"] == ciclo_actual
    assert body["resumen"]["total_tokens"] == 500000

    # Formato inválido de ciclo
    r_err = await cliente.get("/admin/v1/business/usage/tokens", params={"ciclo": "2026"})
    assert r_err.status_code == 422
    assert r_err.json()["error"]["codigo"] == "VALIDACION_ENTRADA"


# ==============================================================================
# 5. Filtros de Tier / Plan y Tenant
# ==============================================================================


async def test_usage_tokens_filtros_tier_y_plan(
    cliente: Any, como: Any, sin_limite: None, datos_consumo_tokens: None
) -> None:
    """Valida el filtrado por plan comercial (growth, enterprise) y 422 si es inválido."""
    como("staff_negocio")

    # Filtro plan=growth -> solo Acme
    r_growth = await cliente.get("/admin/v1/business/usage/tokens", params={"plan": "growth"})
    assert r_growth.status_code == 200
    items_growth = r_growth.json()["items"]
    assert len(items_growth) == 1
    assert items_growth[0]["tenant_id"] == "org_acme"
    assert items_growth[0]["plan"] == "growth"

    # Filtro plan=enterprise -> solo Globex
    r_ent = await cliente.get("/admin/v1/business/usage/tokens", params={"plan": "enterprise"})
    assert r_ent.status_code == 200
    items_ent = r_ent.json()["items"]
    assert len(items_ent) == 1
    assert items_ent[0]["tenant_id"] == "org_globex"
    assert items_ent[0]["plan"] == "enterprise"

    # Filtro plan=starter -> sin resultados en datos de prueba
    r_starter = await cliente.get("/admin/v1/business/usage/tokens", params={"plan": "starter"})
    assert r_starter.status_code == 200
    assert len(r_starter.json()["items"]) == 0

    # Filtro tier=todos -> sin restricción de plan
    r_todos = await cliente.get("/admin/v1/business/usage/tokens", params={"tier": "todos"})
    assert r_todos.status_code == 200
    assert len(r_todos.json()["items"]) == 2

    # Plan inválido -> 422
    r_inv = await cliente.get(
        "/admin/v1/business/usage/tokens", params={"plan": "plan_inventado"}
    )
    assert r_inv.status_code == 422
    assert r_inv.json()["error"]["codigo"] == "VALIDACION_ENTRADA"


async def test_usage_tokens_filtro_tenant_id(
    cliente: Any, como: Any, sin_limite: None, datos_consumo_tokens: None
) -> None:
    """Valida la consulta acotada a una sola organización cliente."""
    como("staff_negocio")
    r = await cliente.get("/admin/v1/business/usage/tokens", params={"tenant_id": "org_globex"})
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 1
    assert body["items"][0]["tenant_id"] == "org_globex"


# ==============================================================================
# 6. Allowlist de Ordenación
# ==============================================================================


@pytest.mark.parametrize(
    "sort_param",
    [
        "tokens_in-asc",
        "tokens_in-desc",
        "tokens_out-asc",
        "tokens_out-desc",
        "tokens_total-asc",
        "tokens_total-desc",
        "coste_eur-asc",
        "coste_eur-desc",
        "coste-desc",
        "loc_consumidas-asc",
        "loc_consumidas-desc",
        "cuota_pct-asc",
        "cuota_pct-desc",
        "tenant_id-asc",
        "tenant_id-desc",
    ],
)
async def test_usage_tokens_ordenacion_allowlist_valida(
    cliente: Any, como: Any, sin_limite: None, datos_consumo_tokens: None, sort_param: str
) -> None:
    """Comprueba que todos los campos autorizados en la allowlist funcionan correctamente."""
    como("staff_negocio")
    r = await cliente.get("/admin/v1/business/usage/tokens", params={"sort": sort_param})
    assert r.status_code == 200, f"Fallo al ordenar por {sort_param}: {r.text}"
    assert len(r.json()["items"]) >= 1


async def test_usage_tokens_ordenacion_invalida_devuelve_422(
    cliente: Any, como: Any, sin_limite: None
) -> None:
    """Valida que un campo fuera de la lista blanca o con formato erróneo retorne HTTP 422."""
    como("staff_negocio")

    # Campo no permitido
    r_no_perm = await cliente.get(
        "/admin/v1/business/usage/tokens", params={"sort": "password_hash-desc"}
    )
    assert r_no_perm.status_code == 422
    assert r_no_perm.json()["error"]["codigo"] == "VALIDACION_ENTRADA"

    # Formato inválido sin sufijo -asc o -desc
    r_formato = await cliente.get(
        "/admin/v1/business/usage/tokens", params={"sort": "tokens_in"}
    )
    assert r_formato.status_code == 422
    assert r_formato.json()["error"]["codigo"] == "VALIDACION_ENTRADA"


# ==============================================================================
# 7. Control de Acceso RBAC
# ==============================================================================


@pytest.mark.parametrize("rol", ["staff_negocio", "staff_admin"])
async def test_usage_tokens_roles_autorizados_200(
    cliente: Any, como: Any, sin_limite: None, datos_consumo_tokens: None, rol: str
) -> None:
    """staff_negocio y staff_admin tienen permiso de consulta analítica."""
    como(rol)
    r = await cliente.get("/admin/v1/business/usage/tokens")
    assert r.status_code == 200


@pytest.mark.parametrize("rol", ["staff_soporte", "staff_operaciones"])
async def test_usage_tokens_roles_denegados_403(
    cliente: Any, como: Any, sin_limite: None, rol: str
) -> None:
    """staff_soporte y staff_operaciones reciben 403 ROL_STAFF_INSUFICIENTE."""
    como(rol)
    r = await cliente.get("/admin/v1/business/usage/tokens")
    assert r.status_code == 403
    assert r.json()["error"]["codigo"] == "ROL_STAFF_INSUFICIENTE"


async def test_usage_tokens_anonimo_401(cliente: Any) -> None:
    """Petición anónima sin cabecera de autenticación devuelve HTTP 401."""
    r = await cliente.get("/admin/v1/business/usage/tokens")
    assert r.status_code == 401
    assert r.json()["error"]["codigo"] == "NO_AUTENTICADO"


# ==============================================================================
# 8. Agrupaciones Alternativas (Tier y Día)
# ==============================================================================


async def test_usage_tokens_agrupacion_tier(
    cliente: Any, como: Any, sin_limite: None, datos_consumo_tokens: None
) -> None:
    """Valida la agrupación analítica por tier de modelo LLM (flash, pro, fable)."""
    como("staff_negocio")
    r = await cliente.get("/admin/v1/business/usage/tokens", params={"agrupar_por": "tier"})
    assert r.status_code == 200
    body = r.json()
    items = body["items"]
    tiers = [it["tier"] for it in items]
    assert "flash" in tiers
    assert "pro" in tiers
    assert "fable" in tiers

    for it in items:
        assert it["tokens_total"] == it["tokens_in"] + it["tokens_out"]
        assert it["coste"] > 0
        assert it["enmascarado"] is False


async def test_usage_tokens_agrupacion_dia(
    cliente: Any, como: Any, sin_limite: None, datos_consumo_tokens: None
) -> None:
    """Valida la serie temporal agrupada por día."""
    como("staff_negocio")
    r = await cliente.get("/admin/v1/business/usage/tokens", params={"agrupar_por": "dia"})
    assert r.status_code == 200
    body = r.json()
    items = body["items"]
    assert len(items) >= 1
    assert "dia" in items[0]
    assert "por_tier" in items[0]
    assert "flash" in items[0]["por_tier"]


async def test_usage_tokens_agrupacion_invalida_422(
    cliente: Any, como: Any, sin_limite: None
) -> None:
    """Valida que una agrupación desconocida retorne HTTP 422."""
    como("staff_negocio")
    r = await cliente.get("/admin/v1/business/usage/tokens", params={"agrupar_por": "semana"})
    assert r.status_code == 422
    assert r.json()["error"]["codigo"] == "VALIDACION_ENTRADA"


# ==============================================================================
# 9. Detección de Descuadre con Facturación
# ==============================================================================


async def test_usage_tokens_descuadre_facturacion(
    cliente: Any, como: Any, sin_limite: None, datos_consumo_tokens: None, dsn: str
) -> None:
    """Verifica que un descuadre entre consumo y factura se alerte visiblemente."""
    # Introducir descuadre malicioso en core.usage_cycles para org_acme
    engine = create_async_engine(
        dsn.replace("postgresql://", "postgresql+asyncpg://"),
        poolclass=NullPool,
    )
    ahora = datetime.now(UTC)
    ciclo_actual = ahora.strftime("%Y-%m")
    async with AsyncSession(engine) as session:
        await session.execute(
            text(
                f"""
            UPDATE core.usage_cycles
            SET loc_consumidas = 999999
            WHERE tenant_id = 'org_acme' AND ciclo = '{ciclo_actual}';
        """
            )
        )
        await session.commit()
    await engine.dispose()

    como("staff_negocio")
    r = await cliente.get("/admin/v1/business/usage/tokens", params={"periodo": "mes_actual"})
    assert r.status_code == 200
    body = r.json()

    # Debe reportar cuadra_con_facturacion = False en el sobre y listar descuadres
    assert body["cuadra_con_facturacion"] is False
    assert body["descuadres"] is not None
    assert "org_acme" in body["descuadres"]

    item_acme = next(it for it in body["items"] if it["tenant_id"] == "org_acme")
    assert item_acme["cuadra_con_facturacion"] is False
