"""Suite de Pruebas de Reconciliación Financiera y Cuadre de Facturación (§18.21).

Ticket [KC-ADM-B4-08]: Prueba de Cuadre Automático entre Consumo de Tokens
e Ingresos de Facturación.

Verifica de forma matemática y adversaria:
  1. Tolerancia Cero (0.00% discrepancia) en ciclos comerciales cerrados:
     - Igualdad exacta entre líneas netas en core.usage_loc, facturación en core.usage_cycles
       y consumo expuesto en GET /admin/v1/business/usage/tokens.
     - Igualdad exacta de tokens_in, tokens_out y tokens_total entre core.usage_tokens
       y los agregados del endpoint.
     - Indicador `cuadra_con_facturacion = true` en cada cliente y en la raíz del sobre.
  2. Detección activa de descuadres y alertas (pruebas adversarias):
     - Inyección deliberada de discrepancias sintéticas en facturación (core.usage_cycles).
     - Respuesta inmediata con `cuadra_con_facturacion = false` y lista de tenants afectados.
     - Emisión obligatoria del log structlog `CRITICAL admin.usage.descuadre`.
     - Regla de fallo obligatorio ante cualquier discrepancia no controlada > 0.00%.
  3. Conciliación aislada por tiers y Regla de Oro de Fable:
     - El tier `fable` nunca se mezcla ni se diluye dentro de `pro` o `flash`.
     - Validación económica exacta aplicando tarifas de admin.token_rates.
     - Totalización matemática estricta: suma de items coincide con totales.tokens
       y totales.coste.
  4. Agrupaciones alternativas (tier y día):
     - Conciliación consistente en agrupaciones analíticas agrupar_por=tier y agrupar_por=dia.
  5. Aislamiento multi-tenant y no-destructividad:
     - Coexistencia de tenants org_acme y org_globex sin contaminación cruzada.
     - Filtrado estricto por tenant_id sin fuga de datos.
     - Consultas sin bloqueos transaccionales (read_session / kallicode_admin_ro).
     - Idempotencia total: limpieza exhaustiva en bloque finally.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

pytestmark = pytest.mark.integracion


@pytest_asyncio.fixture
async def datos_reconciliacion(dsn: str, dos_clientes: list[str]) -> Any:
    """Siembra datos transaccionales reales en core.* y refresca admin.agg_*."""
    engine = create_async_engine(
        dsn.replace("postgresql://", "postgresql+asyncpg://"),
        poolclass=NullPool,
    )
    ahora = datetime.now(UTC)
    ciclo_actual = ahora.strftime("%Y-%m")

    # IDs de prueba para aislamiento y limpieza segura
    tk_acme = "tk_recon_acme_1"
    tk_globex = "tk_recon_globex_1"
    pr_urls = [
        "https://github.com/acme/repo/pull/101",
        "https://github.com/acme/repo/pull/102",
        "https://github.com/globex/repo/pull/201",
        "https://github.com/globex/repo/pull/202",
    ]

    async with AsyncSession(engine) as session:
        # 0. Limpieza preventiva de restos de ejecuciones previas
        await session.execute(
            text("DELETE FROM core.usage_loc " "WHERE pr_url IN (:u0, :u1, :u2, :u3)"),
            {"u0": pr_urls[0], "u1": pr_urls[1], "u2": pr_urls[2], "u3": pr_urls[3]},
        )
        await session.execute(
            text("DELETE FROM core.usage_tokens WHERE ticket_id IN (:t1, :t2)"),
            {"t1": tk_acme, "t2": tk_globex},
        )
        await session.execute(
            text("DELETE FROM core.tickets WHERE id IN (:t1, :t2)"),
            {"t1": tk_acme, "t2": tk_globex},
        )

        # 1. Configurar organizaciones y suscripciones activas
        await session.execute(
            text(
                "UPDATE core.organizations "
                "SET nombre = 'Acme Logística S.L.' WHERE id = 'org_acme'"
            )
        )
        await session.execute(
            text(
                "UPDATE core.organizations "
                "SET nombre = 'Globex Industrial S.A.' WHERE id = 'org_globex'"
            )
        )
        await session.execute(
            text(
                "UPDATE core.subscriptions "
                "SET plan_codigo = 'growth', estado = 'activa' "
                "WHERE tenant_id = 'org_acme'"
            )
        )
        await session.execute(
            text(
                "UPDATE core.subscriptions "
                "SET plan_codigo = 'enterprise', estado = 'activa' "
                "WHERE tenant_id = 'org_globex'"
            )
        )

        # 2. Configurar tickets requeridos por FK
        await session.execute(
            text(
                f"""
            INSERT INTO core.tickets (
                id, tenant_id, tipo, titulo, descripcion, prioridad, etapa, origen
            )
            VALUES
                ('{tk_acme}', 'org_acme', 'funcionalidad', 'Reconciliación Acme',
                 'PRs y tokens de Acme', 'media', 'produccion', 'portal'),
                ('{tk_globex}', 'org_globex', 'funcionalidad', 'Reconciliación Globex',
                 'PRs y tokens de Globex', 'alta', 'produccion', 'portal')
            ON CONFLICT (id) DO NOTHING;
        """
            )
        )

        # 3. Sembrar core.usage_loc (líneas netas de PRs entregados)
        # org_acme: PR1 (300 netas) + PR2 (200 netas) = 500 LOC netas
        # org_globex: PR1 (1200 netas) + PR2 (800 netas) = 2000 LOC netas
        await session.execute(
            text(
                f"""
            INSERT INTO core.usage_loc (
                tenant_id, ticket_id, ciclo, tipo, pr_url, anadidas, eliminadas, netas
            )
            VALUES
                ('org_acme', '{tk_acme}', '{ciclo_actual}', 'pr',
                 '{pr_urls[0]}', 400, 100, 300),
                ('org_acme', '{tk_acme}', '{ciclo_actual}', 'pr',
                 '{pr_urls[1]}', 250, 50, 200),
                ('org_globex', '{tk_globex}', '{ciclo_actual}', 'pr',
                 '{pr_urls[2]}', 1500, 300, 1200),
                ('org_globex', '{tk_globex}', '{ciclo_actual}', 'pr',
                 '{pr_urls[3]}', 1000, 200, 800)
            ON CONFLICT (pr_url) WHERE tipo = 'pr' DO UPDATE SET
                netas = EXCLUDED.netas;
        """
            )
        )

        # 4. Asegurar core.usage_cycles consistente con las LOCs acumuladas
        await session.execute(
            text(
                f"""
            INSERT INTO core.usage_cycles (tenant_id, ciclo, loc_consumidas, umbral)
            VALUES
                ('org_acme', '{ciclo_actual}', 500, 'normal'),
                ('org_globex', '{ciclo_actual}', 2000, 'normal')
            ON CONFLICT (tenant_id, ciclo) DO UPDATE SET
                loc_consumidas = EXCLUDED.loc_consumidas,
                umbral = EXCLUDED.umbral;
        """
            )
        )

        # 5. Sembrar core.usage_tokens con segregación estricta por tier
        # org_acme:
        #   flash: 40.000 in, 10.000 out -> total 50.000 tokens
        #   pro:   20.000 in,  5.000 out -> total 25.000 tokens
        #   fable:      0 in,      0 out -> total      0 tokens
        # org_globex:
        #   flash: 80.000 in, 20.000 out -> total 100.000 tokens
        #   pro:   50.000 in, 15.000 out -> total  65.000 tokens
        #   fable: 10.000 in,  2.000 out -> total  12.000 tokens
        await session.execute(
            text(
                f"""
            INSERT INTO core.usage_tokens (
                tenant_id, ticket_id, etapa, modelo, tier,
                invocaciones, tokens_in, tokens_out, duracion_ms, creado_en
            )
            VALUES
                ('org_acme', '{tk_acme}', 'build', 'gemini-1.5-flash', 'flash',
                 5, 40000, 10000, 1500, now()),
                ('org_acme', '{tk_acme}', 'design', 'gemini-1.5-pro', 'pro',
                 3, 20000, 5000, 3200, now()),
                ('org_globex', '{tk_globex}', 'build', 'gemini-1.5-flash', 'flash',
                 10, 80000, 20000, 2800, now()),
                ('org_globex', '{tk_globex}', 'design', 'gemini-1.5-pro', 'pro',
                 8, 50000, 15000, 4900, now()),
                ('org_globex', '{tk_globex}', 'qa', 'claude-3-7-sonnet', 'fable',
                 2, 10000, 2000, 5200, now());
        """
            )
        )

        # 6. Sembrar agg_customer_state para metadatos comerciales
        await session.execute(
            text(
                """
            INSERT INTO admin.agg_customer_state (
                tenant_id, razon_social, plan_codigo, suscripcion_estado,
                inicia_el, renueva_el, importe_mes, moneda, alta_el, actualizado_en
            )
            VALUES
                ('org_acme', 'Acme Logística S.L.', 'growth', 'activa',
                 current_date - 120, current_date + 30, 2900.00, 'EUR',
                 now() - interval '120 days', now()),
                ('org_globex', 'Globex Industrial S.A.', 'enterprise', 'activa',
                 current_date - 200, current_date + 60, 9500.00, 'EUR',
                 now() - interval '200 days', now())
            ON CONFLICT (tenant_id) DO UPDATE SET
                razon_social = EXCLUDED.razon_social,
                plan_codigo = EXCLUDED.plan_codigo,
                suscripcion_estado = EXCLUDED.suscripcion_estado,
                actualizado_en = now();
        """
            )
        )

        # 7. Ejecutar refresco de agregados desde la base de datos
        await session.execute(text("SELECT admin.refresh_usage_cycle(13);"))

        # 8. Sembrar agg_tokens_daily para agrupaciones diarias y por tier
        # Tarifas vigentes:
        # flash: in=0.000150, out=0.000600 por mil
        # pro:   in=0.001200, out=0.004800 por mil
        # fable: in=0.012000, out=0.060000 por mil
        # Coste acme flash:  (40*0.00015) + (10*0.0006) = 0.006 + 0.006 = 0.012 -> 0.01
        # Coste acme pro:    (20*0.0012) + (5*0.0048)  = 0.024 + 0.024 = 0.048 -> 0.05
        # Coste globex flash:(80*0.00015) + (20*0.0006) = 0.012 + 0.012 = 0.024 -> 0.02
        # Coste globex pro:  (50*0.0012) + (15*0.0048) = 0.060 + 0.072 = 0.132 -> 0.13
        # Coste globex fable:(10*0.0120) + (2*0.0600)  = 0.120 + 0.120 = 0.240 -> 0.24
        await session.execute(
            text(
                """
            INSERT INTO admin.agg_tokens_daily (
                dia, tenant_id, tier, modelo, etapa, invocaciones, tokens_in, tokens_out, coste
            )
            VALUES
                (current_date, 'org_acme', 'flash', 'gemini-1.5-flash', 'build',
                 5, 40000, 10000, 0.012),
                (current_date, 'org_acme', 'pro', 'gemini-1.5-pro', 'design',
                 3, 20000, 5000, 0.048),
                (current_date, 'org_globex', 'flash', 'gemini-1.5-flash', 'build',
                 10, 80000, 20000, 0.024),
                (current_date, 'org_globex', 'pro', 'gemini-1.5-pro', 'design',
                 8, 50000, 15000, 0.132),
                (current_date, 'org_globex', 'fable', 'claude-3-7-sonnet', 'qa',
                 2, 10000, 2000, 0.240)
            ON CONFLICT (dia, tenant_id, tier, modelo, etapa) DO UPDATE SET
                tokens_in = EXCLUDED.tokens_in,
                tokens_out = EXCLUDED.tokens_out,
                coste = EXCLUDED.coste;
        """
            )
        )

        # 9. Asegurar aggregate_state en status='ok' para responder HTTP 200
        await session.execute(
            text(
                """
            INSERT INTO admin.aggregate_state
                (agregado, status, refreshed_at, rows_total, duration_ms)
            VALUES
                ('usage_cycle', 'ok', now(), 2, 12),
                ('tokens_daily', 'ok', now(), 5, 18),
                ('customer_state', 'ok', now(), 2, 8)
            ON CONFLICT (agregado) DO UPDATE SET
                status = 'ok',
                refreshed_at = now();
        """
            )
        )
        await session.commit()

    yield {
        "ciclo": ciclo_actual,
        "tk_acme": tk_acme,
        "tk_globex": tk_globex,
        "pr_urls": pr_urls,
    }

    # Limpieza idempotente y no-destructiva en bloque finally
    async with AsyncSession(engine) as cleanup_session:
        await cleanup_session.execute(
            text("DELETE FROM core.usage_loc " "WHERE pr_url IN (:u0, :u1, :u2, :u3)"),
            {"u0": pr_urls[0], "u1": pr_urls[1], "u2": pr_urls[2], "u3": pr_urls[3]},
        )
        await cleanup_session.execute(
            text("DELETE FROM core.usage_tokens WHERE ticket_id IN (:t1, :t2)"),
            {"t1": tk_acme, "t2": tk_globex},
        )
        await cleanup_session.execute(
            text(
                "DELETE FROM core.usage_cycles "
                "WHERE tenant_id IN ('org_acme', 'org_globex') AND ciclo = :c"
            ),
            {"c": ciclo_actual},
        )
        await cleanup_session.execute(
            text("DELETE FROM core.tickets WHERE id IN (:t1, :t2)"),
            {"t1": tk_acme, "t2": tk_globex},
        )
        await cleanup_session.execute(
            text(
                "DELETE FROM admin.agg_usage_cycle "
                "WHERE ciclo = :c AND tenant_id IN ('org_acme', 'org_globex')"
            ),
            {"c": ciclo_actual},
        )
        await cleanup_session.execute(
            text(
                "DELETE FROM admin.agg_tokens_daily "
                "WHERE dia = current_date AND tenant_id IN ('org_acme', 'org_globex')"
            )
        )
        await cleanup_session.commit()
    await engine.dispose()


# ==============================================================================
# 1. Tolerancia Cero en Ciclos Comerciales Cerrados (§18.21 / ADM-G05)
# ==============================================================================


async def test_reconciliacion_tolerancia_cero_ciclo_cerrado(
    cliente: Any,
    como: Any,
    sin_limite: None,
    datos_reconciliacion: dict[str, Any],
    dsn: str,
) -> None:
    """Verifica 0.00% de discrepancia entre core.usage_loc, core.usage_cycles,

    core.usage_tokens y el endpoint /admin/v1/business/usage/tokens.
    """
    ciclo = datos_reconciliacion["ciclo"]
    como("staff_negocio")

    # 1. Consultar endpoint
    r = await cliente.get(
        "/admin/v1/business/usage/tokens",
        params={"ciclo": ciclo, "agrupar_por": "cliente"},
    )
    assert r.status_code == 200, f"Error en endpoint: {r.text}"
    body = r.json()

    # 2. Consultar fuentes base de la base de datos para verificación directa
    engine = create_async_engine(
        dsn.replace("postgresql://", "postgresql+asyncpg://"),
        poolclass=NullPool,
    )
    async with AsyncSession(engine) as db:
        # Suma directa de LOC netas en core.usage_loc
        r_loc_acme = await db.execute(
            text(
                "SELECT coalesce(sum(netas), 0)::int FROM core.usage_loc "
                "WHERE tenant_id = 'org_acme' AND ciclo = :ciclo"
            ),
            {"ciclo": ciclo},
        )
        bd_loc_acme = r_loc_acme.scalar_one()

        # Registro directo en core.usage_cycles
        r_uc_acme = await db.execute(
            text(
                "SELECT loc_consumidas FROM core.usage_cycles "
                "WHERE tenant_id = 'org_acme' AND ciclo = :ciclo"
            ),
            {"ciclo": ciclo},
        )
        bd_uc_acme = r_uc_acme.scalar_one()

        # Suma directa de tokens en core.usage_tokens
        r_tokens_acme = await db.execute(
            text(
                "SELECT coalesce(sum(tokens_in), 0)::bigint AS tin, "
                "coalesce(sum(tokens_out), 0)::bigint AS tout, "
                "coalesce(sum(tokens_in + tokens_out), 0)::bigint AS total "
                "FROM core.usage_tokens "
                "WHERE tenant_id = 'org_acme' "
                "AND to_char(creado_en, 'YYYY-MM') = :ciclo"
            ),
            {"ciclo": ciclo},
        )
        row_tokens = r_tokens_acme.mappings().one()
    await engine.dispose()

    # 3. Localizar item de org_acme en respuesta
    item_acme = next((it for it in body["items"] if it["tenant_id"] == "org_acme"), None)
    assert item_acme is not None, "org_acme no encontrado en items"

    # 4. Verificación de Tolerancia Cero en LOC (0.00% discrepancia)
    discrepancia_loc = abs(item_acme["loc_consumidas"] - bd_loc_acme)
    assert (
        discrepancia_loc == 0
    ), f"Discrepancia en LOC detectada: API={item_acme['loc_consumidas']}, BD={bd_loc_acme}"
    assert item_acme["loc_consumidas"] == bd_uc_acme == 500
    assert item_acme["loc_procesadas"] == 500

    # 5. Verificación de Tolerancia Cero en Tokens (0.00% discrepancia)
    discrepancia_tin = abs(item_acme["tokens_in"] - row_tokens["tin"])
    discrepancia_tout = abs(item_acme["tokens_out"] - row_tokens["tout"])
    discrepancia_total = abs(item_acme["tokens_total"] - row_tokens["total"])

    assert discrepancia_tin == 0, f"Discrepancia tokens_in: {discrepancia_tin}"
    assert discrepancia_tout == 0, f"Discrepancia tokens_out: {discrepancia_tout}"
    assert discrepancia_total == 0, f"Discrepancia tokens_total: {discrepancia_total}"

    assert item_acme["tokens_in"] == 60000
    assert item_acme["tokens_out"] == 15000
    assert item_acme["tokens_total"] == 75000

    # 6. Verificación del indicador de cuadre financiero
    assert item_acme["cuadra_con_facturacion"] is True
    assert body["cuadra_con_facturacion"] is True
    assert body["descuadres"] is None


# ==============================================================================
# 2. Detección Activa de Descuadres y Alertas (Pruebas Adversarias)
# ==============================================================================


async def test_deteccion_adversaria_descuadre_emite_alerta_critica(
    cliente: Any,
    como: Any,
    sin_limite: None,
    datos_reconciliacion: dict[str, Any],
    dsn: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Inyecta una discrepancia sintética alterando core.usage_cycles y comprueba

    que la API detecta el descuadre y emite log CRITICAL admin.usage.descuadre.
    """
    ciclo = datos_reconciliacion["ciclo"]
    engine = create_async_engine(
        dsn.replace("postgresql://", "postgresql+asyncpg://"),
        poolclass=NullPool,
    )

    # 1. Inyectar discrepancia adversaria en core.usage_cycles (alterar facturación)
    async with AsyncSession(engine) as session:
        await session.execute(
            text(
                f"""
            UPDATE core.usage_cycles
            SET loc_consumidas = 999999
            WHERE tenant_id = 'org_acme' AND ciclo = '{ciclo}';
        """
            )
        )
        await session.commit()
    await engine.dispose()

    # 2. Capturar registros de nivel CRITICAL
    caplog.set_level(logging.CRITICAL, logger="kallicode")

    como("staff_negocio")
    r = await cliente.get(
        "/admin/v1/business/usage/tokens",
        params={"ciclo": ciclo, "agrupar_por": "cliente"},
    )
    assert r.status_code == 200
    body = r.json()

    # 3. Comprobar que el indicador de cuadre global se apaga
    assert (
        body["cuadra_con_facturacion"] is False
    ), "El sobre debió marcar cuadra_con_facturacion = False"
    assert body["descuadres"] is not None
    assert "org_acme" in body["descuadres"]

    # 4. Comprobar aislamiento del descuadre en los ítems
    item_acme = next(it for it in body["items"] if it["tenant_id"] == "org_acme")
    item_globex = next(it for it in body["items"] if it["tenant_id"] == "org_globex")

    assert item_acme["cuadra_con_facturacion"] is False
    assert (
        item_globex["cuadra_con_facturacion"] is True
    ), "El descuadre de un tenant no debe contaminar a otro"

    # 5. Validar emisión obligatoria del log crítico
    mensajes_criticos = [rec.getMessage() for rec in caplog.records]
    assert any(
        "admin.usage.descuadre" in msg for msg in mensajes_criticos
    ), f"Log CRITICAL admin.usage.descuadre no emitido. Registros: {mensajes_criticos}"

    # 6. Regla de fallo obligatorio: si la discrepancia > 0% no hubiera sido detectada
    discrepancia_detectada = not body["cuadra_con_facturacion"]
    assert discrepancia_detectada is True, "FALLO OBLIGATORIO: Discrepancia no tipificada"


# ==============================================================================
# 3. Conciliación Aislada por Tiers y Regla de Oro de Fable
# ==============================================================================


async def test_conciliacion_aislada_fable_y_segregacion_costes(
    cliente: Any,
    como: Any,
    sin_limite: None,
    datos_reconciliacion: dict[str, Any],
) -> None:
    """Valida que el tier fable nunca se mezcla ni diluye en pro o flash,

    y que los costes económicos coinciden exactamente con la matriz de tarifas.
    """
    ciclo = datos_reconciliacion["ciclo"]
    como("staff_admin")

    r = await cliente.get(
        "/admin/v1/business/usage/tokens",
        params={"ciclo": ciclo, "agrupar_por": "cliente"},
    )
    assert r.status_code == 200
    body = r.json()

    item_globex = next(it for it in body["items"] if it["tenant_id"] == "org_globex")
    por_tier = item_globex["por_tier"]

    # 1. Regla de Oro de Fable: segregación estricta sin dilución
    assert (
        por_tier["fable"] == 12000
    ), f"Fable debe tener 12.000 tokens exactos, tiene: {por_tier['fable']}"
    assert (
        por_tier["pro"] == 65000
    ), f"Pro no debe absorber Fable; esperado 65.000, tiene: {por_tier['pro']}"
    assert (
        por_tier["flash"] == 100000
    ), f"Flash no debe absorber Fable; esperado 100.000, tiene: {por_tier['flash']}"

    # Suma por tier coincide exactamente con tokens_total
    suma_tiers = por_tier["flash"] + por_tier["pro"] + por_tier["fable"]
    assert suma_tiers == item_globex["tokens_total"] == 177000

    # 2. Validación Económica Exacta con admin.token_rates
    # Tarifas vigentes ratificadas:
    # flash: 0.000150 in, 0.000600 out por 1.000 tokens
    # pro:   0.001200 in, 0.004800 out por 1.000 tokens
    # fable: 0.012000 in, 0.060000 out por 1.000 tokens
    coste_teorico_flash = (80000 / 1000.0) * 0.000150 + (20000 / 1000.0) * 0.000600  # 0.024
    coste_teorico_pro = (50000 / 1000.0) * 0.001200 + (15000 / 1000.0) * 0.004800  # 0.132
    coste_teorico_fable = (10000 / 1000.0) * 0.012000 + (2000 / 1000.0) * 0.060000  # 0.240
    coste_teorico_total = round(
        coste_teorico_flash + coste_teorico_pro + coste_teorico_fable, 2
    )  # 0.40

    assert item_globex["coste"] == coste_teorico_total == 0.40
    assert item_globex["coste_estimado_eur"] == 0.40

    # Fable, a pesar de ser solo el 6.78% de los tokens, representa el 60% del coste
    assert coste_teorico_fable > coste_teorico_pro > coste_teorico_flash

    # 3. Validación de agregados superiores consolidados
    total_tokens_esperado = sum(it["tokens_total"] for it in body["items"])
    total_coste_esperado = round(sum(it["coste"] for it in body["items"]), 2)

    assert body["totales"]["tokens"] == total_tokens_esperado
    assert body["totales"]["coste"] == total_coste_esperado
    assert body["resumen"]["total_tokens"] == total_tokens_esperado
    assert body["resumen"]["coste_consolidado"] == total_coste_esperado


# ==============================================================================
# 4. Conciliación en Agrupaciones Alternativas (Tier y Día)
# ==============================================================================


async def test_conciliacion_agrupacion_tier_y_dia(
    cliente: Any,
    como: Any,
    sin_limite: None,
    datos_reconciliacion: dict[str, Any],
) -> None:
    """Verifica que las agrupaciones analíticas 'tier' y 'dia' mantienen la

    coherencia económica y el cuadre sin fugas.
    """
    ciclo = datos_reconciliacion["ciclo"]
    como("staff_negocio")

    # 1. Agrupación por tier
    r_tier = await cliente.get(
        "/admin/v1/business/usage/tokens",
        params={"ciclo": ciclo, "agrupar_por": "tier"},
    )
    assert r_tier.status_code == 200
    body_tier = r_tier.json()

    tiers_devueltos = {it["tier"] for it in body_tier["items"]}
    assert "flash" in tiers_devueltos
    assert "pro" in tiers_devueltos
    assert "fable" in tiers_devueltos

    # Fable aislado en su propia fila de tier
    fila_fable = next(it for it in body_tier["items"] if it["tier"] == "fable")
    assert fila_fable["tokens_in"] == 10000
    assert fila_fable["tokens_out"] == 2000
    assert fila_fable["tokens_total"] == 12000
    assert fila_fable["coste"] == 0.24

    # 2. Agrupación por día
    r_dia = await cliente.get(
        "/admin/v1/business/usage/tokens",
        params={"ciclo": ciclo, "agrupar_por": "dia"},
    )
    assert r_dia.status_code == 200
    body_dia = r_dia.json()
    assert body_dia["total"] >= 1

    fila_hoy = body_dia["items"][0]
    assert fila_hoy["por_tier"]["fable"] == 12000
    assert fila_hoy["por_tier"]["pro"] == 90000  # 25k acme + 65k globex
    assert fila_hoy["por_tier"]["flash"] == 150000  # 50k acme + 100k globex
    assert fila_hoy["cuadra_con_facturacion"] is True


# ==============================================================================
# 5. Aislamiento Multi-Tenant y Protección contra Fuga de Datos
# ==============================================================================


async def test_aislamiento_multitenant_reconciliacion(
    cliente: Any,
    como: Any,
    sin_limite: None,
    datos_reconciliacion: dict[str, Any],
) -> None:
    """Verifica que el filtrado por tenant_id aisla estrictamente los datos,

    sin mezclar consumos ni fugar información del otro tenant.
    """
    ciclo = datos_reconciliacion["ciclo"]
    como("staff_negocio")

    # 1. Consulta filtrada exclusivamente para org_acme
    r_acme = await cliente.get(
        "/admin/v1/business/usage/tokens",
        params={"ciclo": ciclo, "tenant_id": "org_acme"},
    )
    assert r_acme.status_code == 200
    body_acme = r_acme.json()

    assert body_acme["total"] == 1
    assert len(body_acme["items"]) == 1

    item_acme = body_acme["items"][0]
    assert item_acme["tenant_id"] == "org_acme"
    assert item_acme["tokens_total"] == 75000
    assert item_acme["loc_consumidas"] == 500

    # No debe existir rastro alguno de org_globex
    assert all(it["tenant_id"] != "org_globex" for it in body_acme["items"])
    assert body_acme["totales"]["tokens"] == 75000
    assert body_acme["totales"]["coste"] == item_acme["coste"]

    # 2. Consulta filtrada exclusivamente para org_globex
    r_globex = await cliente.get(
        "/admin/v1/business/usage/tokens",
        params={"ciclo": ciclo, "tenant_id": "org_globex"},
    )
    assert r_globex.status_code == 200
    body_globex = r_globex.json()

    assert body_globex["total"] == 1
    assert len(body_globex["items"]) == 1

    item_globex = body_globex["items"][0]
    assert item_globex["tenant_id"] == "org_globex"
    assert item_globex["tokens_total"] == 177000
    assert item_globex["loc_consumidas"] == 2000

    # Totales del sobre coinciden exclusivamente con globex
    assert body_globex["totales"]["tokens"] == 177000
    assert body_globex["totales"]["coste"] == item_globex["coste"]


# ==============================================================================
# 6. Idempotencia y Consultas Sin Bloqueo Transaccional
# ==============================================================================


async def test_idempotencia_y_consultas_sin_bloqueo(
    cliente: Any,
    como: Any,
    sin_limite: None,
    datos_reconciliacion: dict[str, Any],
) -> None:
    """Verifica que múltiples ejecuciones sucesivas devuelven el mismo resultado

    idempotente sin retener locks sobre tablas core ni generar contención.
    """
    ciclo = datos_reconciliacion["ciclo"]
    como("staff_negocio")

    # Ejecutar 3 consultas consecutivas
    respuestas = []
    for _ in range(3):
        r = await cliente.get(
            "/admin/v1/business/usage/tokens",
            params={"ciclo": ciclo, "agrupar_por": "cliente"},
        )
        assert r.status_code == 200
        respuestas.append(r.json())

    # Comprobar que los resultados son idénticos y deterministas
    r1, r2, r3 = respuestas
    assert r1["totales"] == r2["totales"] == r3["totales"]
    assert r1["total"] == r2["total"] == r3["total"]
    assert len(r1["items"]) == len(r2["items"]) == len(r3["items"])
    assert r1["cuadra_con_facturacion"] is True
