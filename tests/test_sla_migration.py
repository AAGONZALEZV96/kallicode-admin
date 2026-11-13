"""Suite de pruebas de migración y reloj de SLA (`db/004_sla.sql`).

Ticket [KC-ADM-B5-01]: Migración SQL 004_sla.sql: Objetivos, Pausas y Reloj
de SLA de Servicio (Épica EAD5 / ADM-G07 / §18.27 - §18.28 / ADR-003).

Cubre de forma determinista y no destructiva sobre PostgreSQL 16 real:
  1. Aplicación declarativa e idempotente de `db/004_sla.sql`.
  2. Seeding canónico de objetivos (`docs/decisiones-negocio.md`) y constraint
     `UNIQUE(plan_codigo, etapa)`.
  3. Constraints estrictos en `admin.sla_clock_segments`:
     - Rechazo de `computa = false` sin `causa_pausa` válida (`chk_causa_pausa`).
     - Rechazo de `computa = true` con `causa_pausa` no nula (`chk_causa_pausa`).
     - Aceptación de las cinco causas tipificadas y rechazo de `fin < inicio`.
  4. Cálculo exacto de `admin.calcular_reloj_caso()` descontando pausas:
     - Clasificación como `dentro`, `incumplido`, `en_curso`/`en_riesgo`.
     - Desglose JSONB de tramos y `reglas_aplicadas`.
  5. Determinismo y reproducibilidad en evaluaciones repetidas sobre casos cerrados.
  6. Agregación por ciclo y cliente (`admin.calcular_cumplimiento_sla_ciclo`) y
     materialización en `admin.sla_cases` / `admin.agg_sla_compliance` vía
     `admin.refresh_sla()`.
  7. Mínimo privilegio: `kallicode_admin_ro` consulta tablas y ejecuta cálculo
     en transacción `READ ONLY`, sin poder mutar datos ni ejecutar `refresh_sla`.
  8. Integración retrocompatible con `core.jobs`, `core.job_transitions` y
     `admin.compute_sla_case()`.
"""

from __future__ import annotations

import json
import subprocess
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

pytestmark = pytest.mark.integracion

RAIZ = Path(__file__).resolve().parents[1]
SQL_004 = RAIZ / "db" / "004_sla.sql"


def _async_dsn(dsn_url: str) -> str:
    if dsn_url.startswith("postgresql+asyncpg://"):
        return dsn_url
    return dsn_url.replace("postgresql://", "postgresql+asyncpg://", 1)


@pytest_asyncio.fixture
async def super_session(dsn: str, esquema: str) -> AsyncIterator[AsyncSession]:
    """Sesión administrativa para sembrar y limpiar datos de prueba de forma aislada."""
    engine = create_async_engine(_async_dsn(dsn), poolclass=NullPool)
    async with AsyncSession(engine) as session:
        yield session
    await engine.dispose()


async def _limpiar_prefijo(session: AsyncSession, prefijo: str) -> None:
    """Elimina cualquier registro sembrado por un caso de prueba."""
    await session.rollback()
    like = f"{prefijo}%"
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
        text("DELETE FROM core.job_transitions WHERE job_id LIKE :p"),
        {"p": like},
    )
    await session.execute(
        text("DELETE FROM core.jobs WHERE id LIKE :p"),
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
        text("DELETE FROM core.organizations WHERE id LIKE :p"),
        {"p": like},
    )
    await session.commit()


async def _sembrar_tenant_con_plan(
    session: AsyncSession,
    tenant_id: str,
    plan_codigo: str,
) -> None:
    """Crea una organización aislada con suscripción activa para el plan dado."""
    await session.execute(
        text(
            """
            INSERT INTO core.organizations
                (id, nombre, idioma, timezone, despliegue, fabrica_activa)
            VALUES (:tid, :nombre, 'es', 'Europe/Madrid', 'cloud', true)
            ON CONFLICT (id) DO NOTHING
            """
        ),
        {"tid": tenant_id, "nombre": f"Cliente SLA {tenant_id}"},
    )
    await session.execute(
        text(
            """
            INSERT INTO core.subscriptions
                (id, tenant_id, plan_codigo, estado, inicia_el, renueva_el)
            VALUES (:sid, :tid, :plan, 'activa', current_date - 60, current_date + 30)
            ON CONFLICT (id) DO UPDATE SET plan_codigo = EXCLUDED.plan_codigo, estado = 'activa'
            """
        ),
        {"sid": f"sub_{tenant_id}", "tid": tenant_id, "plan": plan_codigo},
    )
    await session.commit()


# ============================================================ 1. Idempotencia
async def test_migracion_004_es_idempotente(
    dsn: str,
    esquema: str,
    super_session: AsyncSession,
) -> None:
    """Aplicar `db/004_sla.sql` repetidamente no falla ni duplica catálogo/seeds."""
    for intento in range(2):
        proc = subprocess.run(
            ["psql", dsn, "-v", "ON_ERROR_STOP=1", "-q", "-f", str(SQL_004)],
            capture_output=True,
            text=True,
        )
        assert proc.returncode == 0, f"Fallo en aplicación #{intento + 1}: {proc.stderr}"

    tablas = await super_session.execute(
        text(
            """
            SELECT table_name
              FROM information_schema.tables
             WHERE table_schema = 'admin'
               AND table_name IN (
                   'sla_targets', 'sla_pause_states', 'sla_clock_segments',
                   'sla_cases', 'agg_sla_compliance'
               )
             ORDER BY table_name
            """
        )
    )
    assert [r[0] for r in tablas.fetchall()] == [
        "agg_sla_compliance",
        "sla_cases",
        "sla_clock_segments",
        "sla_pause_states",
        "sla_targets",
    ]

    funciones = await super_session.execute(
        text(
            """
            SELECT p.proname
              FROM pg_proc p
              JOIN pg_namespace n ON n.oid = p.pronamespace
             WHERE n.nspname = 'admin'
               AND p.proname IN (
                   'calcular_reloj_caso',
                   'calcular_cumplimiento_sla_ciclo',
                   'compute_sla_case',
                   'refresh_sla'
               )
             ORDER BY p.proname
            """
        )
    )
    assert [r[0] for r in funciones.fetchall()] == [
        "calcular_cumplimiento_sla_ciclo",
        "calcular_reloj_caso",
        "compute_sla_case",
        "refresh_sla",
    ]


# ============================================================ 2. Seeding y targets
async def test_seeding_canonico_y_unicidad_sla_targets(
    super_session: AsyncSession,
) -> None:
    """`admin.sla_targets` contiene los objetivos de `docs/decisiones-negocio.md`."""
    res = await super_session.execute(
        text(
            """
            SELECT plan_codigo, etapa, objetivo_h, activo
              FROM admin.sla_targets
             WHERE etapa IN ('*', 'total_e2e')
             ORDER BY plan_codigo, etapa
            """
        )
    )
    filas = {(r[0], r[1]): (r[2], r[3]) for r in res.fetchall()}
    esperados = {
        ("starter", "*"): Decimal("72.00"),
        ("starter", "total_e2e"): Decimal("72.00"),
        ("growth", "*"): Decimal("24.00"),
        ("growth", "total_e2e"): Decimal("24.00"),
        ("enterprise", "*"): Decimal("8.00"),
        ("enterprise", "total_e2e"): Decimal("8.00"),
    }
    for clave, horas in esperados.items():
        assert clave in filas, f"Falta objetivo canónico para {clave}"
        assert filas[clave][0] == horas
        assert filas[clave][1] is True

    with pytest.raises(IntegrityError):
        await super_session.execute(
            text(
                """
                INSERT INTO admin.sla_targets (plan_codigo, etapa, objetivo_h)
                VALUES ('enterprise', 'total_e2e', 10.00)
                """
            )
        )
    await super_session.rollback()


# ============================================================ 3. Constraints
@pytest.mark.parametrize(
    ("computa", "causa"),
    [
        (False, None),
        (False, ""),
        (False, "causa_inventada"),
        (True, "espera_firma_cliente"),
    ],
)
async def test_constraint_chk_causa_pausa_rechaza_combinaciones_invalidas(
    super_session: AsyncSession,
    computa: bool,
    causa: str | None,
) -> None:
    """Una pausa sin causa válida o un tramo computable con causa falla por constraint."""
    prefijo = "org_sla_mig_chk_"
    tid = f"{prefijo}1"
    jid = "job_sla_mig_chk_1"
    t0 = datetime(2026, 11, 10, 10, 0, tzinfo=UTC)
    try:
        await _sembrar_tenant_con_plan(super_session, tid, "enterprise")
        with pytest.raises(IntegrityError) as exc:
            await super_session.execute(
                text(
                    """
                    INSERT INTO admin.sla_clock_segments
                        (tenant_id, job_id, etapa, inicio, fin, computa, causa_pausa)
                    VALUES (:tid, :jid, 'gate1', :ini, :fin, :comp, :causa)
                    """
                ),
                {
                    "tid": tid,
                    "jid": jid,
                    "ini": t0,
                    "fin": t0 + timedelta(hours=1),
                    "comp": computa,
                    "causa": causa,
                },
            )
        assert "chk_causa_pausa" in str(exc.value)
        await super_session.rollback()
    finally:
        await _limpiar_prefijo(super_session, prefijo)
        await _limpiar_prefijo(super_session, "job_sla_mig_chk_")


async def test_sla_clock_segments_acepta_causas_validas_y_valida_ventana(
    super_session: AsyncSession,
) -> None:
    """Acepta todas las causas tipificadas y rechaza tramos con `fin < inicio`."""
    prefijo = "org_sla_mig_val_"
    tid = f"{prefijo}1"
    jid = "job_sla_mig_val_1"
    t0 = datetime(2026, 11, 10, 8, 0, tzinfo=UTC)
    causas_validas = (
        "espera_firma_cliente",
        "escalado_humano",
        "ventana_mantenimiento",
        "indisponibilidad_proveedor_llm",
        "otro",
    )
    try:
        await _sembrar_tenant_con_plan(super_session, tid, "growth")
        for idx, causa in enumerate(causas_validas):
            await super_session.execute(
                text(
                    """
                    INSERT INTO admin.sla_clock_segments
                        (tenant_id, job_id, etapa, inicio, fin, computa, causa_pausa)
                    VALUES (:tid, :jid, 'gate1', :ini, :fin, false, :causa)
                    """
                ),
                {
                    "tid": tid,
                    "jid": jid,
                    "ini": t0 + timedelta(hours=idx),
                    "fin": t0 + timedelta(hours=idx + 1),
                    "causa": causa,
                },
            )
        await super_session.commit()

        with pytest.raises(IntegrityError) as exc:
            await super_session.execute(
                text(
                    """
                    INSERT INTO admin.sla_clock_segments
                        (tenant_id, job_id, etapa, inicio, fin, computa, causa_pausa)
                    VALUES (:tid, :jid, 'build', :ini, :fin, true, NULL)
                    """
                ),
                {
                    "tid": tid,
                    "jid": jid,
                    "ini": t0 + timedelta(hours=10),
                    "fin": t0 + timedelta(hours=9),
                },
            )
        assert "chk_segment_window" in str(exc.value)
        await super_session.rollback()
    finally:
        await _limpiar_prefijo(super_session, prefijo)
        await _limpiar_prefijo(super_session, "job_sla_mig_val_")


# ============================================================ 4. Reloj y pausas
async def test_calcular_reloj_caso_descuenta_pausas_y_clasifica_dentro_e_incumplido(
    super_session: AsyncSession,
) -> None:
    """Descuenta exactamente `espera_firma_cliente` y distingue `dentro` vs `incumplido`."""
    prefijo = "org_sla_mig_clk_"
    tid = f"{prefijo}ent"
    job_ok = "job_sla_mig_clk_ok"
    job_fail = "job_sla_mig_clk_fail"
    job_open = "job_sla_mig_clk_open"
    base = datetime(2026, 11, 10, 9, 0, tzinfo=UTC)

    try:
        # Plan Enterprise => objetivo 8.00 h
        await _sembrar_tenant_con_plan(super_session, tid, "enterprise")

        # Caso 1 (dentro): 2h triage + 30h pausa gate cliente + 4h build => bruto 36h, neto 6h
        tramos_ok = [
            ("triage", base, base + timedelta(hours=2), True, None),
            (
                "gate2",
                base + timedelta(hours=2),
                base + timedelta(hours=32),
                False,
                "espera_firma_cliente",
            ),
            ("build", base + timedelta(hours=32), base + timedelta(hours=36), True, None),
        ]
        for etapa, ini, fin, comp, causa in tramos_ok:
            await super_session.execute(
                text(
                    """
                    INSERT INTO admin.sla_clock_segments
                        (tenant_id, job_id, ticket_id, etapa, inicio, fin, computa, causa_pausa)
                    VALUES (:tid, :jid, 'tk_1', :etapa, :ini, :fin, :comp, :causa)
                    """
                ),
                {
                    "tid": tid,
                    "jid": job_ok,
                    "etapa": etapa,
                    "ini": ini,
                    "fin": fin,
                    "comp": comp,
                    "causa": causa,
                },
            )

        # Caso 2 (incumplido): 5h design + 12h pausa escalado + 5.5h build => neto 10.5h > 8h
        tramos_fail = [
            ("design", base, base + timedelta(hours=5), True, None),
            (
                "escalado_humano",
                base + timedelta(hours=5),
                base + timedelta(hours=17),
                False,
                "escalado_humano",
            ),
            (
                "build",
                base + timedelta(hours=17),
                base + timedelta(hours=22, minutes=30),
                True,
                None,
            ),
        ]
        for etapa, ini, fin, comp, causa in tramos_fail:
            await super_session.execute(
                text(
                    """
                    INSERT INTO admin.sla_clock_segments
                        (tenant_id, job_id, ticket_id, etapa, inicio, fin, computa, causa_pausa)
                    VALUES (:tid, :jid, 'tk_2', :etapa, :ini, :fin, :comp, :causa)
                    """
                ),
                {
                    "tid": tid,
                    "jid": job_fail,
                    "etapa": etapa,
                    "ini": ini,
                    "fin": fin,
                    "comp": comp,
                    "causa": causa,
                },
            )

        # Caso 3 (en_curso): tramo reciente de 1 hora aún abierto (`fin IS NULL`)
        ahora = datetime.now(UTC)
        await super_session.execute(
            text(
                """
                INSERT INTO admin.sla_clock_segments
                    (tenant_id, job_id, ticket_id, etapa, inicio, fin, computa, causa_pausa)
                VALUES (:tid, :jid, 'tk_3', 'triage', :ini, NULL, true, NULL)
                """
            ),
            {"tid": tid, "jid": job_open, "ini": ahora - timedelta(hours=1)},
        )
        await super_session.commit()

        # Verificar Caso 1 (`dentro`)
        res_ok = (
            (
                await super_session.execute(
                    text("SELECT * FROM admin.calcular_reloj_caso(:j)"), {"j": job_ok}
                )
            )
            .mappings()
            .one()
        )
        assert res_ok["objetivo_h"] == Decimal("8.00")
        assert res_ok["bruto_h"] == Decimal("36.00")
        assert res_ok["transcurrido_h"] == Decimal("6.00")
        assert res_ok["resultado"] == "dentro"
        tramos_json = res_ok["tramos"]
        if isinstance(tramos_json, str):
            tramos_json = json.loads(tramos_json)
        assert len(tramos_json) == 3
        assert tramos_json[1]["computa"] is False
        assert tramos_json[1]["causa_pausa"] == "espera_firma_cliente"
        assert float(tramos_json[1]["horas"]) == pytest.approx(30.0)
        reglas = res_ok["reglas_aplicadas"]
        if isinstance(reglas, str):
            reglas = json.loads(reglas)
        assert reglas == ["espera_firma_cliente"]

        # Verificar Caso 2 (`incumplido`)
        res_fail = (
            (
                await super_session.execute(
                    text("SELECT * FROM admin.calcular_reloj_caso(:j)"), {"j": job_fail}
                )
            )
            .mappings()
            .one()
        )
        assert res_fail["objetivo_h"] == Decimal("8.00")
        assert res_fail["bruto_h"] == Decimal("22.50")
        assert res_fail["transcurrido_h"] == Decimal("10.50")
        assert res_fail["resultado"] == "incumplido"

        # Verificar Caso 3 (`en_curso`)
        res_open = (
            (
                await super_session.execute(
                    text("SELECT * FROM admin.calcular_reloj_caso(:j)"), {"j": job_open}
                )
            )
            .mappings()
            .one()
        )
        assert res_open["resultado"] == "en_curso"
        assert res_open["transcurrido_h"] < Decimal("2.00")

        # Caso 4: Determinismo absoluto sobre caso cerrado (dos evaluaciones iguales)
        res_ok_2 = (
            (
                await super_session.execute(
                    text("SELECT * FROM admin.calcular_reloj_caso(:j)"), {"j": job_ok}
                )
            )
            .mappings()
            .one()
        )
        assert dict(res_ok) == dict(res_ok_2)
    finally:
        await _limpiar_prefijo(super_session, prefijo)
        await _limpiar_prefijo(super_session, "job_sla_mig_clk_")


# ============================================================ 5. Ciclo y agregado
async def test_calcular_cumplimiento_sla_ciclo_y_refresh_sla(
    super_session: AsyncSession,
) -> None:
    """Calcula el cumplimiento agregado por ciclo y materializa `agg_sla_compliance`."""
    prefijo = "org_sla_mig_ciclo_"
    tid = f"{prefijo}1"
    j_ok = "job_sla_mig_ciclo_ok"
    j_fail = "job_sla_mig_ciclo_fail"
    # Usamos fecha dentro de los últimos 95 días para que `refresh_sla` lo incluya
    hoy = datetime.now(UTC).replace(hour=12, minute=0, second=0, microsecond=0)
    ciclo = hoy.strftime("%Y-%m")

    try:
        await _sembrar_tenant_con_plan(super_session, tid, "growth")  # 24.00 h

        # Caso dentro: 10h netas + 20h pausa
        await super_session.execute(
            text(
                """
                INSERT INTO admin.sla_clock_segments
                    (tenant_id, job_id, etapa, inicio, fin, computa, causa_pausa)
                VALUES
                    (:tid, :j1, 'design', :i1, :f1, true, NULL),
                    (:tid, :j1, 'gate1',  :f1, :f2, false, 'espera_firma_cliente'),
                    (:tid, :j2, 'build',  :i1, :f3, true, NULL)
                """
            ),
            {
                "tid": tid,
                "j1": j_ok,
                "j2": j_fail,
                "i1": hoy - timedelta(hours=30),
                "f1": hoy - timedelta(hours=20),
                "f2": hoy,
                "f3": hoy - timedelta(hours=4),  # 26h > 24h => incumplido
            },
        )
        await super_session.commit()

        # Evaluación agregada por ciclo filtrada por tenant
        agg = (
            (
                await super_session.execute(
                    text("SELECT * FROM admin.calcular_cumplimiento_sla_ciclo(:c, :t)"),
                    {"c": ciclo, "t": tid},
                )
            )
            .mappings()
            .one()
        )
        assert agg["ciclo"] == ciclo
        assert agg["tenant_id"] == tid
        assert agg["plan_codigo"] == "growth"
        assert agg["casos_totales"] == 2
        assert agg["casos_evaluados"] == 2
        assert agg["casos_dentro"] == 1
        assert agg["casos_incumplidos"] == 1
        assert agg["cumplimiento_pct"] == Decimal("50.00")
        assert agg["bruto_total_h"] == Decimal("56.00")
        assert agg["transcurrido_total_h"] == Decimal("36.00")

        # Materialización mediante `refresh_sla`
        await super_session.execute(text("SELECT admin.refresh_sla(95, true)"))
        await super_session.commit()

        mat = (
            (
                await super_session.execute(
                    text(
                        """
                    SELECT casos_totales, casos_dentro, casos_incumplidos, cumplimiento_pct
                      FROM admin.agg_sla_compliance
                     WHERE ciclo = :c AND tenant_id = :t
                    """
                    ),
                    {"c": ciclo, "t": tid},
                )
            )
            .mappings()
            .one()
        )
        assert mat["casos_totales"] == 2
        assert mat["casos_dentro"] == 1
        assert mat["casos_incumplidos"] == 1
        assert mat["cumplimiento_pct"] == Decimal("50.00")
    finally:
        await _limpiar_prefijo(super_session, prefijo)
        await _limpiar_prefijo(super_session, "job_sla_mig_ciclo_")


# ============================================================ 6. Privilegios
async def test_privilegios_minimos_para_kallicode_admin_ro(
    super_session: AsyncSession,
    db_ro: Any,
) -> None:
    """`kallicode_admin_ro` ejecuta funciones de cálculo en READ ONLY sin poder refrescar."""
    from sqlalchemy.exc import DBAPIError, ProgrammingError

    prefijo = "org_sla_mig_ro_"
    tid = f"{prefijo}1"
    jid = "job_sla_mig_ro_1"
    t0 = datetime(2026, 11, 10, 10, 0, tzinfo=UTC)

    try:
        await _sembrar_tenant_con_plan(super_session, tid, "starter")
        await super_session.execute(
            text(
                """
                INSERT INTO admin.sla_clock_segments
                    (tenant_id, job_id, etapa, inicio, fin, computa, causa_pausa)
                VALUES (:tid, :jid, 'triage', :ini, :fin, true, NULL)
                """
            ),
            {"tid": tid, "jid": jid, "ini": t0, "fin": t0 + timedelta(hours=5)},
        )
        await super_session.commit()

        # Puede consultar tablas y ejecutar las funciones de cálculo en READ ONLY
        res_caso = (
            await db_ro.execute(
                text("SELECT resultado, transcurrido_h FROM admin.calcular_reloj_caso(:j)"),
                {"j": jid},
            )
        ).one()
        assert res_caso[0] == "dentro"
        assert res_caso[1] == Decimal("5.00")

        res_ciclo = (
            await db_ro.execute(
                text(
                    "SELECT casos_dentro "
                    "FROM admin.calcular_cumplimiento_sla_ciclo('2026-11', :t)"
                ),
                {"t": tid},
            )
        ).one()
        assert res_ciclo[0] == 1

        # Prohibido escribir en sla_clock_segments o ejecutar refresh_sla
        with pytest.raises((ProgrammingError, DBAPIError)):
            await db_ro.execute(
                text("SELECT admin.refresh_sla(95, false)"),
            )
        await db_ro.rollback()

        with pytest.raises((ProgrammingError, DBAPIError)):
            await db_ro.execute(
                text(
                    """
                    INSERT INTO admin.sla_clock_segments
                        (tenant_id, job_id, etapa, inicio, computa)
                    VALUES (:tid, :jid, 'triage', now(), true)
                    """
                ),
                {"tid": tid, "jid": jid},
            )
        await db_ro.rollback()
    finally:
        await _limpiar_prefijo(super_session, prefijo)
        await _limpiar_prefijo(super_session, "job_sla_mig_ro_")


# ============================================================ 7. Core integration
async def test_compute_sla_case_compatible_con_core_job_transitions(
    super_session: AsyncSession,
) -> None:
    """`admin.compute_sla_case()` proyecta transiciones reales de `core.jobs`."""
    prefijo = "org_sla_mig_core_"
    tid = f"{prefijo}1"
    tkid = "tk_sla_mig_core_1"
    jid = "job_sla_mig_core_1"
    t0 = datetime(2026, 11, 10, 8, 0, tzinfo=UTC)

    try:
        await _sembrar_tenant_con_plan(super_session, tid, "enterprise")
        await super_session.execute(
            text(
                """
                INSERT INTO core.tickets
                    (id, tenant_id, tipo, titulo, descripcion, prioridad, etapa, origen)
                VALUES (
                    :tk, :tid, 'bug', 'Prueba SLA Core', 'Detalle',
                    'alta', 'produccion', 'portal'
                )
                """
            ),
            {"tk": tkid, "tid": tid},
        )
        await super_session.execute(
            text(
                """
                INSERT INTO core.jobs
                    (id, tenant_id, ticket_id, estado, prioridad, creado_en, terminado_en)
                VALUES (:jid, :tid, :tk, 'produccion', 'P1', :ini, :fin)
                """
            ),
            {"jid": jid, "tid": tid, "tk": tkid, "ini": t0, "fin": t0 + timedelta(hours=30)},
        )
        await super_session.execute(
            text(
                """
                INSERT INTO core.job_transitions
                    (tenant_id, job_id, de_estado, a_estado, creado_en)
                VALUES
                    (:tid, :jid, 'pendiente_asignacion', 'build', :t0),
                    (:tid, :jid, 'build', 'gate2', :t1),
                    (:tid, :jid, 'gate2', 'deploy', :t2)
                """
            ),
            {
                "tid": tid,
                "jid": jid,
                "t0": t0,
                "t1": t0 + timedelta(hours=3),
                "t2": t0 + timedelta(hours=27),
            },
        )
        await super_session.commit()

        caso = (
            (
                await super_session.execute(
                    text(
                        "SELECT resultado, bruto_h, transcurrido_h "
                        "FROM admin.compute_sla_case(:j)"
                    ),
                    {"j": jid},
                )
            )
            .mappings()
            .one()
        )
        await super_session.commit()

        # 3h build + 24h pausa gate2 + 3h deploy => bruto 30h, neto 6h <= 8h (Enterprise)
        assert caso["bruto_h"] == Decimal("30.00")
        assert caso["transcurrido_h"] == Decimal("6.00")
        assert caso["resultado"] == "dentro"
    finally:
        await _limpiar_prefijo(super_session, prefijo)
        await _limpiar_prefijo(super_session, "job_sla_mig_core_")
        await _limpiar_prefijo(super_session, "tk_sla_mig_core_")
