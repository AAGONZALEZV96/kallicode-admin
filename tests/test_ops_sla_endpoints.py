"""Pruebas de integración de los endpoints backend de SLA (§18.27 - §18.28 / KC-ADM-B5-02).

Valida sobre PostgreSQL real (sin mocks de negocio):
  1. GET /admin/v1/ops/sla:
     - Filtros `ciclo`, `tenant_id` y `plan` (y validación 422 en valores inválidos).
     - Desglose `por_plan` (`starter`, `growth`, `enterprise`), `tiempo_medio_h` y `p95_h`.
     - Regla estadística `sla_min_cases` (< 5 casos => `cumplimiento_pct = None`).
     - Detección de `casos_en_riesgo` activos con consumo > 75% del objetivo.
     - Validación de frescura de agregados: `WARN` (> 6h) y HTTP 503 (> 24h / fallido).
  2. GET /admin/v1/ops/sla/cases/{job_id}:
     - Descomposición matemática (`objetivo_h`, `bruto_h`, `transcurrido_h`, `pausa_total_h`),
       tramos cronológicos con `duracion_h`/`horas`, `etapa_actual` y `reglas_aplicadas`.
     - Clasificación `'en_riesgo'` cuando supera el 75% en curso.
     - HTTP 404 `JOB_NO_ENCONTRADO` para casos inexistentes.
     - HTTP 422 `SLA_SIN_DEFINICION` cuando el plan carece de objetivo activo.
  3. Seguridad RBAC, mínimo privilegio y enmascaramiento por defecto:
     - Acceso para `OPS_NEGOCIO` y `403 ROL_STAFF_INSUFICIENTE` para `staff_soporte`.
     - Enmascaramiento de `tenant_id`/`razon_social`/`ticket_numero` para `staff_operaciones`
       sin concesión y revelación auditada al existir concesión en `admin.access_grants`.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

pytestmark = pytest.mark.integracion


def _async_dsn(dsn_url: str) -> str:
    if dsn_url.startswith("postgresql+asyncpg://"):
        return dsn_url
    return dsn_url.replace("postgresql://", "postgresql+asyncpg://", 1)


@pytest_asyncio.fixture
async def super_db(dsn: str, esquema: str) -> AsyncIterator[AsyncSession]:
    """Sesión administrativa para sembrar y limpiar datos de prueba de forma aislada."""
    engine = create_async_engine(_async_dsn(dsn), poolclass=NullPool)
    async with AsyncSession(engine) as session:
        yield session
    await engine.dispose()


async def _asegurar_sla_targets(session: AsyncSession) -> None:
    """Restaura los objetivos canónicos si una prueba previa los modificó."""
    await session.execute(
        text(
            """
            INSERT INTO admin.sla_targets
                (plan_codigo, etapa, objetivo_h, riesgo_pct, vigente_desde, activo)
            VALUES
                ('starter',    '*',         72.00, 80.00, DATE '2026-01-01', true),
                ('growth',     '*',         24.00, 80.00, DATE '2026-01-01', true),
                ('enterprise', '*',          8.00, 80.00, DATE '2026-01-01', true),
                ('starter',    'total_e2e', 72.00, 80.00, DATE '2026-01-01', true),
                ('growth',     'total_e2e', 24.00, 80.00, DATE '2026-01-01', true),
                ('enterprise', 'total_e2e',  8.00, 80.00, DATE '2026-01-01', true)
            ON CONFLICT (plan_codigo, etapa) DO UPDATE
                SET objetivo_h = EXCLUDED.objetivo_h,
                    riesgo_pct = EXCLUDED.riesgo_pct,
                    activo = true
        """
        )
    )
    await session.commit()


async def _limpiar_b502(session: AsyncSession, prefijo: str) -> None:
    """Limpia datos de prueba B5-02 preservando intacta la cadena `staff_actions`."""
    await session.rollback()
    like = f"{prefijo}%"

    # Nunca eliminar filas de `admin.staff_actions` para preservar su sello criptográfico.
    # Solo revocar concesiones de prueba si están referenciadas en auditoría.
    await session.execute(
        text(
            """
            UPDATE admin.access_grants
            SET revoked_at = COALESCE(revoked_at, now()),
                revoked_by = COALESCE(revoked_by, 'st_prueba'),
                revoked_reason = COALESCE(revoked_reason, 'Limpieza de prueba B5-02')
            WHERE (tenant_id LIKE :p OR id LIKE :g)
        """
        ),
        {"p": like, "g": f"gr_{prefijo}%"},
    )
    await session.execute(
        text(
            """
            DELETE FROM admin.access_grants g
            WHERE (g.tenant_id LIKE :p OR g.id LIKE :gr)
              AND NOT EXISTS (
                  SELECT 1 FROM admin.staff_actions sa WHERE sa.grant_id = g.id
              )
        """
        ),
        {"p": like, "gr": f"gr_{prefijo}%"},
    )
    await session.execute(
        text("DELETE FROM admin.sla_clock_segments WHERE job_id LIKE :p OR tenant_id LIKE :p"),
        {"p": like},
    )
    await session.execute(
        text("DELETE FROM admin.sla_cases WHERE job_id LIKE :p OR tenant_id LIKE :p"),
        {"p": like},
    )
    await session.execute(
        text("DELETE FROM admin.agg_sla_compliance WHERE tenant_id LIKE :p"),
        {"p": like},
    )
    await session.execute(
        text("DELETE FROM admin.agg_customer_state WHERE tenant_id LIKE :p"),
        {"p": like},
    )
    await session.execute(
        text("DELETE FROM core.job_transitions WHERE job_id LIKE :p"),
        {"p": like},
    )
    await session.execute(
        text("DELETE FROM core.jobs WHERE id LIKE :p OR tenant_id LIKE :p"),
        {"p": like},
    )
    await session.execute(
        text("DELETE FROM core.tickets WHERE id LIKE :p OR tenant_id LIKE :p"),
        {"p": like},
    )
    await session.execute(
        text("DELETE FROM core.ticket_counters WHERE tenant_id LIKE :p"),
        {"p": like},
    )
    await session.execute(
        text("DELETE FROM core.subscriptions WHERE id LIKE :p OR tenant_id LIKE :p"),
        {"p": like},
    )
    await session.execute(
        text(
            """
            DELETE FROM core.organizations o
            WHERE o.id LIKE :p
              AND NOT EXISTS (
                  SELECT 1 FROM admin.staff_actions sa WHERE sa.tenant_id = o.id
              )
              AND NOT EXISTS (
                  SELECT 1 FROM admin.access_grants ag WHERE ag.tenant_id = o.id
              )
        """
        ),
        {"p": like},
    )
    await session.commit()


async def _crear_org_y_sub(
    session: AsyncSession, tenant_id: str, razon_social: str, plan: str
) -> None:
    await session.execute(
        text(
            """
            INSERT INTO core.organizations
                (id, nombre, idioma, timezone, despliegue, fabrica_activa)
            VALUES (:t, :rs, 'es', 'Europe/Madrid', 'cloud', true)
            ON CONFLICT (id) DO NOTHING
        """
        ),
        {"t": tenant_id, "rs": razon_social},
    )
    await session.execute(
        text(
            """
            INSERT INTO core.subscriptions
                (id, tenant_id, plan_codigo, estado, inicia_el, renueva_el)
            VALUES (:sid, :t, :p, 'activa', DATE '2026-01-01', current_date + 30)
            ON CONFLICT (id) DO UPDATE SET plan_codigo = EXCLUDED.plan_codigo, estado = 'activa'
        """
        ),
        {"sid": f"sub_{tenant_id}", "t": tenant_id, "p": plan},
    )
    await session.execute(
        text(
            """
            INSERT INTO admin.agg_customer_state
                (tenant_id, razon_social, plan_codigo, suscripcion_estado)
            VALUES (:t, :rs, :p, 'activa')
            ON CONFLICT (tenant_id) DO UPDATE SET razon_social = EXCLUDED.razon_social
        """
        ),
        {"t": tenant_id, "rs": razon_social, "p": plan},
    )


async def _crear_ticket_y_job(
    session: AsyncSession,
    *,
    job_id: str,
    tenant_id: str,
    ticket_id: str,
    numero_n: int,
    creado_en: datetime,
    terminado_en: datetime | None,
) -> None:
    await session.execute(
        text(
            """
            INSERT INTO core.tickets
                (id, tenant_id, tipo, titulo, descripcion, prioridad, etapa, origen)
            VALUES (
                :tk, :t, 'bug', :tit, 'Detalle SLA B5-02',
                'alta', 'produccion', 'portal'
            )
            ON CONFLICT (id) DO NOTHING
        """
        ),
        {"tk": ticket_id, "t": tenant_id, "tit": f"Ticket SLA #{numero_n}"},
    )
    await session.execute(
        text(
            """
            INSERT INTO core.jobs
                (id, tenant_id, ticket_id, estado, prioridad, creado_en, terminado_en)
            VALUES (:j, :t, :tk, :est, 'P1', :creado, :term)
            ON CONFLICT (id) DO NOTHING
        """
        ),
        {
            "j": job_id,
            "t": tenant_id,
            "tk": ticket_id,
            "est": "produccion" if terminado_en is not None else "qa",
            "creado": creado_en,
            "term": terminado_en,
        },
    )


async def test_ops_sla_resumen_por_plan_riesgo_y_filtros(
    cliente: Any,
    como: Any,
    sin_limite: None,
    super_db: AsyncSession,
) -> None:
    """Valida `/ops/sla` por plan/tenant/ciclo, percentiles, umbral >= 5 y riesgo > 75%."""
    pref = "b502_sum_"
    await _limpiar_b502(super_db, pref)
    await _asegurar_sla_targets(super_db)
    como("staff_negocio")

    ciclo_actual = datetime.now(UTC).strftime("%Y-%m")
    inicio_ciclo = datetime.now(UTC).replace(day=1, hour=8, minute=0, second=0, microsecond=0)
    inicio_anterior = datetime(2026, 9, 10, 9, 0, tzinfo=UTC)

    t_growth = f"{pref}growth"
    t_starter = f"{pref}starter"
    try:
        await _crear_org_y_sub(super_db, t_growth, "Growth Tech S.L.", "growth")
        await _crear_org_y_sub(super_db, t_starter, "Starter Labs S.L.", "starter")

        # 5 casos evaluados Growth (objetivo 24h): 4 dentro (4..16h) y 1 incumplido (30h)
        duraciones_growth = [4.0, 8.0, 12.0, 16.0, 30.0]
        for idx, horas in enumerate(duraciones_growth, start=1):
            jid = f"{pref}job_g_{idx}"
            tkid = f"{pref}tk_g_{idx}"
            ini = inicio_ciclo + timedelta(hours=idx)
            fin = ini + timedelta(hours=horas)
            await _crear_ticket_y_job(
                super_db,
                job_id=jid,
                tenant_id=t_growth,
                ticket_id=tkid,
                numero_n=100 + idx,
                creado_en=ini,
                terminado_en=fin,
            )
            await super_db.execute(
                text(
                    """
                    INSERT INTO admin.sla_clock_segments
                        (tenant_id, job_id, ticket_id, etapa, inicio, fin, computa, causa_pausa)
                    VALUES (:t, :j, :tk, 'build', :ini, :fin, true, NULL)
                """
                ),
                {"t": t_growth, "j": jid, "tk": tkid, "ini": ini, "fin": fin},
            )

        # 1 caso activo EN RIESGO en Growth (> 75% de 24h = 19.0h computadas y sin terminar)
        ahora = datetime.now(UTC)
        jid_risk = f"{pref}job_g_risk"
        tkid_risk = f"{pref}tk_g_risk"
        ini_risk = ahora - timedelta(hours=19)
        await _crear_ticket_y_job(
            super_db,
            job_id=jid_risk,
            tenant_id=t_growth,
            ticket_id=tkid_risk,
            numero_n=199,
            creado_en=ini_risk,
            terminado_en=None,
        )
        await super_db.execute(
            text(
                """
                INSERT INTO admin.sla_clock_segments
                    (tenant_id, job_id, ticket_id, etapa, inicio, fin, computa, causa_pausa)
                VALUES (:t, :j, :tk, 'qa', :ini, NULL, true, NULL)
            """
            ),
            {"t": t_growth, "j": jid_risk, "tk": tkid_risk, "ini": ini_risk},
        )

        # 2 casos evaluados Starter (< 5 mínimo => cumplimiento_pct debe ser None)
        for idx in range(1, 3):
            jid = f"{pref}job_s_{idx}"
            tkid = f"{pref}tk_s_{idx}"
            ini = inicio_ciclo + timedelta(hours=idx)
            fin = ini + timedelta(hours=5)
            await _crear_ticket_y_job(
                super_db,
                job_id=jid,
                tenant_id=t_starter,
                ticket_id=tkid,
                numero_n=200 + idx,
                creado_en=ini,
                terminado_en=fin,
            )
            await super_db.execute(
                text(
                    """
                    INSERT INTO admin.sla_clock_segments
                        (tenant_id, job_id, ticket_id, etapa, inicio, fin, computa, causa_pausa)
                    VALUES (:t, :j, :tk, 'build', :ini, :fin, true, NULL)
                """
                ),
                {"t": t_starter, "j": jid, "tk": tkid, "ini": ini, "fin": fin},
            )

        # 1 caso en ciclo histórico '2026-09' para validar filtro de ciclo
        jid_old = f"{pref}job_old"
        tkid_old = f"{pref}tk_old"
        await _crear_ticket_y_job(
            super_db,
            job_id=jid_old,
            tenant_id=t_growth,
            ticket_id=tkid_old,
            numero_n=301,
            creado_en=inicio_anterior,
            terminado_en=inicio_anterior + timedelta(hours=6),
        )
        await super_db.execute(
            text(
                """
                INSERT INTO admin.sla_clock_segments
                    (tenant_id, job_id, ticket_id, etapa, inicio, fin, computa, causa_pausa)
                VALUES (:t, :j, :tk, 'deploy', :ini, :fin, true, NULL)
            """
            ),
            {
                "t": t_growth,
                "j": jid_old,
                "tk": tkid_old,
                "ini": inicio_anterior,
                "fin": inicio_anterior + timedelta(hours=6),
            },
        )

        await super_db.execute(text("SELECT admin.refresh_sla(95, true)"))
        await super_db.commit()

        # 1) Consulta filtrada por tenant Growth en ciclo actual
        r_g = await cliente.get(
            "/admin/v1/ops/sla",
            params={"ciclo": ciclo_actual, "tenant_id": t_growth, "plan": "growth"},
        )
        assert r_g.status_code == 200, r_g.text
        body = r_g.json()

        assert body["ciclo"] == ciclo_actual
        assert body["frescura"]
        assert body["resumen"]["casos_totales"] == 6
        assert body["resumen"]["casos_evaluados"] == 5
        assert body["resumen"]["casos_dentro"] == 4
        assert body["resumen"]["casos_incumplidos"] == 1
        assert body["resumen"]["cumplimiento_pct"] == 80.0
        assert body["resumen"]["tiempo_medio_h"] == 14.0
        # p95 de [4, 8, 12, 16, 30] = 27.2
        assert body["resumen"]["p95_h"] == pytest.approx(27.2, abs=0.1)

        assert "growth" in body["por_plan"]
        gp = body["por_plan"]["growth"]
        assert gp["objetivo_h"] == 24.0
        assert gp["casos"] == 6
        assert gp["casos_evaluados"] == 5
        assert gp["cumplimiento_pct"] == 80.0
        assert gp["p95_h"] == pytest.approx(27.2, abs=0.1)

        riesgos = [c for c in body["casos_en_riesgo"] if c["job_id"] == jid_risk]
        assert len(riesgos) == 1
        assert riesgos[0]["porcentaje_objetivo"] > 75.0
        assert riesgos[0]["etapa_actual"] == "qa"

        r_risk_det = await cliente.get(f"/admin/v1/ops/sla/cases/{jid_risk}")
        assert r_risk_det.status_code == 200, r_risk_det.text
        assert r_risk_det.json()["resultado"] == "en_riesgo"

        # 2) Consulta Starter (<5 casos) no publica cumplimiento_pct
        r_s = await cliente.get(
            "/admin/v1/ops/sla",
            params={"ciclo": ciclo_actual, "tenant_id": t_starter},
        )
        assert r_s.status_code == 200, r_s.text
        bs = r_s.json()
        assert bs["por_plan"]["starter"]["casos_evaluados"] == 2
        assert bs["por_plan"]["starter"]["cumplimiento_pct"] is None
        assert bs["resumen"]["cumplimiento_pct"] is None

        # 3) Consulta ciclo histórico '2026-09'
        r_old = await cliente.get(
            "/admin/v1/ops/sla",
            params={"ciclo": "2026-09", "tenant_id": t_growth},
        )
        assert r_old.status_code == 200, r_old.text
        assert r_old.json()["ciclo"] == "2026-09"
        assert r_old.json()["resumen"]["casos_totales"] == 1

        # 4) Parámetros inválidos -> 422
        assert (
            await cliente.get("/admin/v1/ops/sla", params={"ciclo": "2026-13"})
        ).status_code == 422
        assert (
            await cliente.get("/admin/v1/ops/sla", params={"plan": "inexistente"})
        ).status_code == 422
    finally:
        await _limpiar_b502(super_db, pref)


async def test_ops_sla_frescura_warn_6h_y_503_24h(
    cliente: Any,
    como: Any,
    sin_limite: None,
    super_db: AsyncSession,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Frescura > 6h emite log WARN y devuelve 200; > 24h rechaza con HTTP 503."""
    como("staff_operaciones")
    await super_db.execute(text("SELECT admin.refresh_sla(95, true)"))
    await super_db.commit()

    try:
        # 7 horas (> aggregate_max_age_s = 6h, < 24h) -> 200 + WARN
        await super_db.execute(
            text(
                """
                UPDATE admin.aggregate_state
                SET refreshed_at = now() - interval '7 hours', status = 'ok'
                WHERE agregado = 'sla_cases'
            """
            )
        )
        await super_db.commit()

        caplog.clear()
        with caplog.at_level(logging.WARNING):
            r_warn = await cliente.get("/admin/v1/ops/sla")
        assert r_warn.status_code == 200, r_warn.text
        assert any(
            "sla_frescura_alta" in rec.message for rec in caplog.records
        ), f"No se registró log WARN de frescura >6h: {[r.message for r in caplog.records]}"

        # 25 horas (> aggregate_stale_s = 24h) -> 503 AGREGADO_NO_DISPONIBLE
        await super_db.execute(
            text(
                """
                UPDATE admin.aggregate_state
                SET refreshed_at = now() - interval '25 hours', status = 'ok'
                WHERE agregado = 'sla_cases'
            """
            )
        )
        await super_db.commit()

        r_stale = await cliente.get("/admin/v1/ops/sla")
        assert r_stale.status_code == 503, r_stale.text
        assert r_stale.json()["error"]["codigo"] == "AGREGADO_NO_DISPONIBLE"
    finally:
        await super_db.execute(
            text(
                """
                UPDATE admin.aggregate_state
                SET refreshed_at = now(), status = 'ok', error = NULL
                WHERE agregado IN ('sla_cases', 'agg_sla_compliance')
            """
            )
        )
        await super_db.commit()


async def test_ops_sla_case_detail_desglose_matematico_y_errores(
    cliente: Any,
    como: Any,
    sin_limite: None,
    super_db: AsyncSession,
) -> None:
    """Valida `/ops/sla/cases/{job_id}` con pausas deducidas, 404 y 422 sin objetivo."""
    pref = "b502_case_"
    await _limpiar_b502(super_db, pref)
    await _asegurar_sla_targets(super_db)
    como("staff_negocio")

    tenant_id = f"{pref}org"
    job_id = f"{pref}job_pausas"
    ticket_id = f"{pref}tk_pausas"
    t0 = datetime.now(UTC) - timedelta(hours=30)

    try:
        await _crear_org_y_sub(super_db, tenant_id, "Case Detail Corp S.L.", "growth")
        await _crear_ticket_y_job(
            super_db,
            job_id=job_id,
            tenant_id=tenant_id,
            ticket_id=ticket_id,
            numero_n=501,
            creado_en=t0,
            terminado_en=t0 + timedelta(hours=22),
        )

        tramos_seed = [
            ("triage", t0, t0 + timedelta(hours=2), True, None),
            (
                "design",
                t0 + timedelta(hours=2),
                t0 + timedelta(hours=12),
                False,
                "espera_firma_cliente",
            ),
            ("build", t0 + timedelta(hours=12), t0 + timedelta(hours=18), True, None),
            (
                "qa",
                t0 + timedelta(hours=18),
                t0 + timedelta(hours=22),
                False,
                "escalado_humano",
            ),
        ]
        for etapa, ini, fin, computa, causa in tramos_seed:
            await super_db.execute(
                text(
                    """
                    INSERT INTO admin.sla_clock_segments
                        (tenant_id, job_id, ticket_id, etapa, inicio, fin, computa, causa_pausa)
                    VALUES (:t, :j, :tk, :et, :ini, :fin, :comp, :causa)
                """
                ),
                {
                    "t": tenant_id,
                    "j": job_id,
                    "tk": ticket_id,
                    "et": etapa,
                    "ini": ini,
                    "fin": fin,
                    "comp": computa,
                    "causa": causa,
                },
            )
        await super_db.execute(text("SELECT admin.compute_sla_case(:j)"), {"j": job_id})
        await super_db.commit()

        r = await cliente.get(f"/admin/v1/ops/sla/cases/{job_id}")
        assert r.status_code == 200, r.text
        cuerpo = r.json()

        assert cuerpo["job_id"] == job_id
        assert cuerpo["ticket_id"] == ticket_id
        assert cuerpo["plan"] == "growth"
        assert cuerpo["etapa_actual"] == "qa"
        assert cuerpo["objetivo_h"] == 24.0
        assert cuerpo["bruto_h"] == pytest.approx(22.0, abs=0.05)
        assert cuerpo["transcurrido_h"] == pytest.approx(8.0, abs=0.05)
        assert cuerpo["pausa_total_h"] == pytest.approx(14.0, abs=0.05)
        assert cuerpo["resultado"] == "dentro"
        assert "espera_firma_cliente" in cuerpo["reglas_aplicadas"]
        assert "escalado_humano" in cuerpo["reglas_aplicadas"]

        assert len(cuerpo["tramos"]) == 4
        for idx, tramo in enumerate(cuerpo["tramos"]):
            assert tramo["etapa"] == tramos_seed[idx][0]
            assert tramo["duracion_h"] == tramo["horas"]
            assert tramo["computa"] is tramos_seed[idx][3]
            assert tramo["causa_pausa"] == tramos_seed[idx][4]

        # 404 JOB_NO_ENCONTRADO
        r_404 = await cliente.get(f"/admin/v1/ops/sla/cases/{pref}no_existe")
        assert r_404.status_code == 404, r_404.text
        assert r_404.json()["error"]["codigo"] == "JOB_NO_ENCONTRADO"

        # 422 SLA_SIN_DEFINICION cuando el plan carece de objetivo activo
        await super_db.execute(
            text("UPDATE admin.sla_targets SET activo = false WHERE plan_codigo = 'growth'")
        )
        await super_db.commit()
        r_422 = await cliente.get(f"/admin/v1/ops/sla/cases/{job_id}")
        assert r_422.status_code == 422, r_422.text
        assert r_422.json()["error"]["codigo"] == "SLA_SIN_DEFINICION"
    finally:
        await super_db.execute(
            text("UPDATE admin.sla_targets SET activo = true WHERE plan_codigo = 'growth'")
        )
        await super_db.commit()
        await _limpiar_b502(super_db, pref)


async def test_ops_sla_rbac_y_enmascaramiento_con_concesion(
    cliente: Any,
    como: Any,
    sin_limite: None,
    super_db: AsyncSession,
) -> None:
    """RBAC estricto y revelación controlada de `tenant_id` mediante `admin.access_grants`."""
    pref = "b502_sec_"
    await _limpiar_b502(super_db, pref)
    await _asegurar_sla_targets(super_db)

    tenant_id = f"{pref}secret_org"
    job_id = f"{pref}job_sec"
    ticket_id = f"{pref}tk_sec"
    grant_id = f"gr_{tenant_id}"
    t0 = datetime.now(UTC) - timedelta(hours=12)

    try:
        await _crear_org_y_sub(super_db, tenant_id, "Acme Secreto S.A.", "enterprise")
        await _crear_ticket_y_job(
            super_db,
            job_id=job_id,
            tenant_id=tenant_id,
            ticket_id=ticket_id,
            numero_n=801,
            creado_en=t0,
            terminado_en=t0 + timedelta(hours=3),
        )
        await super_db.execute(
            text(
                """
                INSERT INTO admin.sla_clock_segments
                    (tenant_id, job_id, ticket_id, etapa, inicio, fin, computa, causa_pausa)
                VALUES (:t, :j, :tk, 'deploy', :ini, :fin, true, NULL)
            """
            ),
            {
                "t": tenant_id,
                "j": job_id,
                "tk": ticket_id,
                "ini": t0,
                "fin": t0 + timedelta(hours=3),
            },
        )
        await super_db.execute(text("SELECT admin.refresh_sla(95, true)"))
        await super_db.commit()

        # 1) staff_soporte debe ser rechazado con 403 ROL_STAFF_INSUFICIENTE
        como("staff_soporte")
        for ruta in ("/admin/v1/ops/sla", f"/admin/v1/ops/sla/cases/{job_id}"):
            r_den = await cliente.get(ruta)
            assert r_den.status_code == 403
            assert r_den.json()["error"]["codigo"] == "ROL_STAFF_INSUFICIENTE"

        # 2) staff_operaciones sin concesión ve tenant_id y razon_social enmascarados
        como("staff_operaciones")
        r_masked = await cliente.get("/admin/v1/ops/sla", params={"tenant_id": tenant_id})
        assert r_masked.status_code == 200, r_masked.text
        item = r_masked.json()["items"][0]
        assert "•" in item["tenant_id"]
        assert "secret_org" not in item["tenant_id"]
        assert "•" in (item["razon_social"] or "")

        r_case_masked = await cliente.get(f"/admin/v1/ops/sla/cases/{job_id}")
        assert r_case_masked.status_code == 200, r_case_masked.text
        case_m = r_case_masked.json()
        assert "•" in case_m["tenant_id"]
        assert "tenant_id" in case_m["enmascarado"]
        assert "•" in (case_m["razon_social"] or "")

        # 3) Con concesión vigente en admin.access_grants se revela y audita
        await super_db.execute(
            text(
                """
                INSERT INTO admin.access_grants
                    (id, staff_id, tenant_id, scope, reason, expires_at)
                VALUES (
                    :gid, 'st_prueba', :t, 'expediente',
                    'Revision de incidente SLA ticket SUP-801 autorizado',
                    now() + interval '1 hour'
                )
                ON CONFLICT (id) DO UPDATE
                SET scope = 'expediente', revoked_at = NULL,
                    expires_at = now() + interval '1 hour'
            """
            ),
            {"gid": grant_id, "t": tenant_id},
        )
        await super_db.commit()

        como("staff_operaciones", grants={tenant_id: ["datos_negocio", "expediente"]})
        r_unmasked = await cliente.get(f"/admin/v1/ops/sla/cases/{job_id}")
        assert r_unmasked.status_code == 200, r_unmasked.text
        case_u = r_unmasked.json()
        assert case_u["tenant_id"] == tenant_id
        assert case_u["razon_social"] == "Acme Secreto S.A."
        assert "tenant_id" not in case_u["enmascarado"]

        audit_cnt = (
            await super_db.execute(
                text(
                    """
                    SELECT count(*) FROM admin.staff_actions
                    WHERE tenant_id = :t AND grant_id = :gid AND action = 'read'
                """
                ),
                {"t": tenant_id, "gid": grant_id},
            )
        ).scalar_one()
        assert audit_cnt >= 1
    finally:
        await _limpiar_b502(super_db, pref)
