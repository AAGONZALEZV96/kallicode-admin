"""Semilla sintética de volumen multi-tenant y pool de 50 tokens JWT staff (KC-ADM-B6-07).

Prepara en PostgreSQL 16 un volumen representativo de organizaciones, suscripciones,
ciclos de consumo, invocaciones de tokens LLM, líneas de producción, tickets, jobs y
segmentos de reloj SLA; ejecuta inicialmente las funciones `SECURITY DEFINER`
`admin.refresh_all_business_aggregates()` y `admin.refresh_sla(95, true)` y genera
50 empleados de carga (`st_load_00`..`st_load_49`) con sus tokens JWT RS256 para que
los 50 VUs de k6 / runner asíncrono operen como 50 operadores reales sin colisionar
en el contador por usuario de `limite_rl4` / `limite_vivo`.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from admin_api.security import emitir_tokens_staff, hashear_password, nuevo_secreto_totp
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

LOAD_DIR = Path(__file__).resolve().parent
TOKENS_FILE = LOAD_DIR / "tokens.json"

NUM_TENANTS_SINTETICOS = 24
NUM_STAFF_VUS = 50
PLANES = ("starter", "growth", "enterprise")
TIERS_MODELOS = (
    ("flash", "gemini-2.0-flash"),
    ("pro", "gemini-2.0-pro"),
    ("fable", "claude-3-7-sonnet"),
)


def _normalizar_async_dsn(dsn_url: str) -> str:
    if dsn_url.startswith("postgresql+asyncpg://"):
        return dsn_url
    return dsn_url.replace("postgresql://", "postgresql+asyncpg://", 1)


async def sembrar_datos_carga_y_tokens(
    dsn_url: str,
    *,
    num_tenants: int = NUM_TENANTS_SINTETICOS,
    num_staff: int = NUM_STAFF_VUS,
    guardar_archivo: bool = True,
) -> dict[str, Any]:
    """Siembra datos multi-tenant idempotentes, refresca agregados y emite JWTs."""
    engine = create_async_engine(_normalizar_async_dsn(dsn_url), poolclass=NullPool)
    ahora = datetime.now(UTC)
    ciclo_actual = ahora.strftime("%Y-%m")
    inicio_mes = ahora.replace(day=1, hour=8, minute=0, second=0, microsecond=0)
    hash_pw = hashear_password("Carga-Segura-2026!")
    secreto_totp = nuevo_secreto_totp()

    tenants_creados: list[str] = []
    staff_ids: list[str] = []
    tokens: list[str] = []

    async with AsyncSession(engine) as session:
        # 1. Organizaciones, suscripciones, consumo, líneas, tickets, jobs y tramos SLA
        for i in range(num_tenants):
            tid = f"org_load_{i:02d}"
            plan = PLANES[i % len(PLANES)]
            razon = f"Corporación Sintética {i:02d} S.A."
            tenants_creados.append(tid)

            await session.execute(
                text(
                    """
                    INSERT INTO core.organizations (
                        id, nombre, idioma, timezone, despliegue, fabrica_activa
                    )
                    VALUES (:id, :nombre, 'es', 'Europe/Madrid', 'cloud', true)
                    ON CONFLICT (id) DO NOTHING
                    """
                ),
                {"id": tid, "nombre": razon},
            )

            await session.execute(
                text(
                    """
                    INSERT INTO core.subscriptions (
                        id, tenant_id, plan_codigo, estado, inicia_el, renueva_el
                    )
                    VALUES (
                        :sid, :tid, :plan, 'activa',
                        current_date - 60, current_date + 30
                    )
                    ON CONFLICT (id) DO UPDATE
                        SET plan_codigo = EXCLUDED.plan_codigo,
                            estado = 'activa'
                    """
                ),
                {"sid": f"sub_{tid}", "tid": tid, "plan": plan},
            )

            await session.execute(
                text(
                    """
                    INSERT INTO core.usage_cycles (
                        tenant_id, ciclo, loc_consumidas, umbral
                    )
                    VALUES (:tid, :ciclo, :loc, 'normal')
                    ON CONFLICT DO NOTHING
                    """
                ),
                {"tid": tid, "ciclo": ciclo_actual, "loc": 1200 + (i * 350)},
            )

            tk_id = f"tk_load_{i:02d}"
            jb_id = f"jb_load_{i:02d}"
            ini_job = inicio_mes + timedelta(hours=(i % 12) + 1)
            fin_job = ini_job + timedelta(hours=3 + (i % 5))

            await session.execute(
                text(
                    """
                    INSERT INTO core.tickets (
                        id, tenant_id, tipo, titulo, descripcion,
                        prioridad, etapa, origen, creado_en, cerrado_en
                    )
                    VALUES (
                        :tk, :tid, 'bug', :tit, 'Ticket sintético de prueba de carga',
                        'alta', 'produccion', 'portal', :ini, :fin
                    )
                    ON CONFLICT (id) DO NOTHING
                    """
                ),
                {
                    "tk": tk_id,
                    "tid": tid,
                    "tit": f"Incidencia carga #{i:02d}",
                    "ini": ini_job,
                    "fin": fin_job,
                },
            )

            tier, modelo = TIERS_MODELOS[i % len(TIERS_MODELOS)]
            await session.execute(
                text(
                    """
                    INSERT INTO core.usage_tokens (
                        tenant_id, ticket_id, tier, modelo, etapa, invocaciones,
                        tokens_in, tokens_out, duracion_ms, creado_en
                    )
                    SELECT :tid, :tk, :tier, :mod, 'build', 15, 24000, 8000, 420, now()
                    WHERE NOT EXISTS (
                        SELECT 1 FROM core.usage_tokens
                        WHERE tenant_id = :tid AND ticket_id = :tk AND modelo = :mod
                    )
                    """
                ),
                {"tid": tid, "tk": tk_id, "tier": tier, "mod": modelo},
            )

            await session.execute(
                text(
                    """
                    INSERT INTO core.jobs (
                        id, tenant_id, ticket_id, estado, prioridad, creado_en, terminado_en
                    )
                    VALUES (:jb, :tid, :tk, 'produccion', 'P1', :ini, :fin)
                    ON CONFLICT (id) DO NOTHING
                    """
                ),
                {
                    "jb": jb_id,
                    "tid": tid,
                    "tk": tk_id,
                    "ini": ini_job,
                    "fin": fin_job,
                },
            )

            await session.execute(
                text(
                    """
                    INSERT INTO admin.sla_clock_segments (
                        tenant_id, job_id, ticket_id, etapa, inicio, fin, computa, causa_pausa
                    )
                    SELECT :tid, :jb, :tk, 'build', :ini, :fin, true, NULL
                    WHERE NOT EXISTS (
                        SELECT 1 FROM admin.sla_clock_segments WHERE job_id = :jb
                    )
                    """
                ),
                {
                    "tid": tid,
                    "jb": jb_id,
                    "tk": tk_id,
                    "ini": ini_job,
                    "fin": fin_job,
                },
            )

        # 2. Pool de 50 empleados staff_admin para los 50 VUs concurrentes
        for idx in range(num_staff):
            sid = f"st_load_{idx:02d}"
            email = f"load.vu{idx:02d}@kallicode.com"
            staff_ids.append(sid)
            await session.execute(
                text(
                    """
                    INSERT INTO admin.staff (
                        id, email, full_name, role, status,
                        password_hash, totp_secret, totp_enrolled_at
                    )
                    VALUES (
                        :id, :email, :name, 'staff_admin', 'active',
                        :pw, :totp, now()
                    )
                    ON CONFLICT (id) DO UPDATE
                        SET status = 'active',
                            role = 'staff_admin'
                    """
                ),
                {
                    "id": sid,
                    "email": email,
                    "name": f"Operador Carga VU {idx:02d}",
                    "pw": hash_pw,
                    "totp": secreto_totp,
                },
            )
            tokens.append(emitir_tokens_staff(sid, "staff_admin", ahora))

        # 3. Refresco inicial de todos los agregados de negocio y SLA (SECURITY DEFINER)
        await session.execute(text("SELECT * FROM admin.refresh_all_business_aggregates()"))
        await session.execute(text("SELECT admin.refresh_sla(95, true)"))
        await session.execute(
            text(
                """
                INSERT INTO admin.aggregate_state (
                    agregado, refreshed_at, duration_ms, rows_total, status
                )
                VALUES ('sla_cases', now(), 15, :n, 'ok')
                ON CONFLICT (agregado) DO UPDATE
                    SET refreshed_at = now(),
                        rows_total = EXCLUDED.rows_total,
                        status = 'ok',
                        error = NULL
                """
            ),
            {"n": num_tenants},
        )
        await session.commit()

    await engine.dispose()

    if guardar_archivo:
        TOKENS_FILE.write_text(json.dumps(tokens, indent=2), encoding="utf-8")

    return {
        "tenants_count": len(tenants_creados),
        "staff_count": len(staff_ids),
        "tokens": tokens,
        "ciclo": ciclo_actual,
    }


async def limpiar_datos_carga(dsn_url: str) -> None:
    """Elimina los registros sintéticos `*_load_*` sin tocar `admin.staff_actions`."""
    engine = create_async_engine(_normalizar_async_dsn(dsn_url), poolclass=NullPool)
    async with AsyncSession(engine) as session:
        await session.execute(
            text("DELETE FROM admin.sla_clock_segments WHERE job_id LIKE 'jb_load_%'")
        )
        await session.execute(text("DELETE FROM admin.sla_cases WHERE job_id LIKE 'jb_load_%'"))
        await session.execute(
            text("DELETE FROM admin.agg_sla_compliance WHERE tenant_id LIKE 'org_load_%'")
        )
        await session.execute(text("DELETE FROM core.jobs WHERE id LIKE 'jb_load_%'"))
        await session.execute(text("DELETE FROM core.tickets WHERE id LIKE 'tk_load_%'"))
        await session.execute(
            text("DELETE FROM core.ticket_counters WHERE tenant_id LIKE 'org_load_%'")
        )
        await session.execute(
            text("DELETE FROM admin.agg_customer_state WHERE tenant_id LIKE 'org_load_%'")
        )
        await session.execute(
            text("DELETE FROM core.usage_tokens WHERE tenant_id LIKE 'org_load_%'")
        )
        await session.execute(
            text("DELETE FROM core.usage_cycles WHERE tenant_id LIKE 'org_load_%'")
        )
        await session.execute(
            text("DELETE FROM core.subscriptions WHERE id LIKE 'sub_org_load_%'")
        )
        await session.execute(
            text(
                """
                DELETE FROM core.organizations o
                WHERE o.id LIKE 'org_load_%'
                  AND NOT EXISTS (
                      SELECT 1 FROM admin.staff_actions sa WHERE sa.tenant_id = o.id
                  )
                """
            )
        )
        await session.execute(
            text(
                """
                DELETE FROM admin.staff s
                WHERE s.id LIKE 'st_load_%'
                  AND NOT EXISTS (
                      SELECT 1 FROM admin.staff_actions sa WHERE sa.staff_id = s.id
                  )
                """
            )
        )
        await session.execute(text("SELECT * FROM admin.refresh_all_business_aggregates()"))
        await session.commit()
    await engine.dispose()
    if TOKENS_FILE.is_file():
        TOKENS_FILE.unlink()
