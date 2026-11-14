"""Suite de pruebas para el worker asíncrono de evaluación SLA ([KC-ADM-B5-04]).

Cubre pruebas unitarias rápidas (intervalo configurable, registro en `_TRABAJOS`,
backoff exponencial, manejo de fallos transitorios y permanentes, parada limpia)
e integración real contra PostgreSQL 16 (`admin.refresh_sla`, `admin.calcular_reloj_caso`,
umbral > 75 % `en_riesgo`, > 100 % `incumplido`, deducción de pausas `computa = false`,
idempotencia, registro `fallido` en `admin.aggregate_state` y recuperación).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock

import admin_workers.sla as sla_mod
import pytest
import pytest_asyncio
from admin_api.db import admin_session
from admin_workers.lider import LOCK_ID_SLA, LOCK_IDS, ejecutar_con_lider
from admin_workers.main import _TRABAJOS
from admin_workers.sla import (
    DEFAULT_SLA_INTERVAL_S,
    es_error_transitorio_bd,
    evaluar_sla,
    evaluar_sla_ciclo,
    obtener_intervalo_sla_s,
)
from sqlalchemy import text
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool


def _async_dsn(dsn_url: str) -> str:
    if dsn_url.startswith("postgresql+asyncpg://"):
        return dsn_url
    return dsn_url.replace("postgresql://", "postgresql+asyncpg://", 1)


@pytest_asyncio.fixture
async def super_session(dsn: str, esquema: str) -> AsyncIterator[AsyncSession]:
    """Sesión administrativa para sembrar y limpiar datos SLA aislados."""
    engine = create_async_engine(_async_dsn(dsn), poolclass=NullPool)
    async with AsyncSession(engine) as session:
        yield session
    await engine.dispose()


async def _limpiar_prefijo(session: AsyncSession, prefijo: str) -> None:
    """Elimina cualquier registro sembrado por una prueba usando el prefijo dado."""
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
        text("DELETE FROM core.organizations WHERE id LIKE :p"),
        {"p": like},
    )
    await session.commit()


async def _sembrar_tenant_con_plan(
    session: AsyncSession,
    tenant_id: str,
    plan_codigo: str,
) -> None:
    """Siembra organización y suscripción activa para evaluar SLA real."""
    await session.execute(
        text(
            """
            INSERT INTO core.organizations
                (id, nombre, idioma, timezone, despliegue, fabrica_activa)
            VALUES (:tid, :nombre, 'es', 'Europe/Madrid', 'cloud', true)
            ON CONFLICT (id) DO NOTHING
            """
        ),
        {"tid": tenant_id, "nombre": f"Cliente Worker SLA {tenant_id}"},
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


# ============================================================ 1. Unitarias
def test_obtener_intervalo_sla_s_default_y_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verifica el intervalo por defecto (300s) y overrides por entorno."""
    monkeypatch.delenv("SLA_EVALUATION_INTERVAL_S", raising=False)
    monkeypatch.delenv("KC_ADMIN_SLA_EVALUATION_INTERVAL_S", raising=False)
    assert obtener_intervalo_sla_s() == DEFAULT_SLA_INTERVAL_S == 300

    monkeypatch.setenv("SLA_EVALUATION_INTERVAL_S", "120")
    assert obtener_intervalo_sla_s() == 120

    monkeypatch.setenv("SLA_EVALUATION_INTERVAL_S", "0")
    assert obtener_intervalo_sla_s() == 300

    monkeypatch.setenv("SLA_EVALUATION_INTERVAL_S", "invalido")
    assert obtener_intervalo_sla_s() == 300


def test_registro_trabajo_y_lock_sla() -> None:
    """El trabajo evaluar_sla está registrado en _TRABAJOS y posee ADVISORY LOCK dedicado."""
    assert LOCK_ID_SLA == 918_404
    assert LOCK_IDS["evaluar_sla"] == LOCK_ID_SLA
    assert "evaluar_sla" in _TRABAJOS
    cuerpo, intervalo = _TRABAJOS["evaluar_sla"]
    assert callable(cuerpo)
    assert intervalo == 300


def test_clasificacion_error_transitorio_bd() -> None:
    """Detecta fallos transitorios de conexión, timeout y SQLSTATE de bloqueo/deadlock."""
    assert es_error_transitorio_bd(TimeoutError("timeout")) is True
    assert es_error_transitorio_bd(ConnectionError("refused")) is True
    op_err = OperationalError("stmt", {}, TimeoutError("lock"))
    assert es_error_transitorio_bd(op_err) is True

    class _DeadlockOrigError(Exception):
        pgcode = "40P01"

    assert es_error_transitorio_bd(RuntimeError("wrapper")) is False
    wrapped = OperationalError("stmt", {}, _DeadlockOrigError("deadlock"))
    assert es_error_transitorio_bd(wrapped) is True


@pytest.mark.asyncio
async def test_evaluar_sla_reintenta_con_backoff_exponencial(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reintenta fallos transitorios duplicando el backoff y persiste éxito al recuperarse."""
    intentos = 0
    esperas: list[float] = []

    class _FakeDb:
        def __init__(self) -> None:
            self.rollbacks = 0

        def in_transaction(self) -> bool:
            return True

        async def rollback(self) -> None:
            self.rollbacks += 1

    async def fake_ciclo(db: Any, **kwargs: Any) -> dict[str, int]:
        nonlocal intentos
        intentos += 1
        if intentos < 3:
            raise OperationalError("SELECT 1", {}, TimeoutError("lock timeout"))
        return {
            "refrescados": 2,
            "activos_evaluados": 1,
            "en_riesgo": 1,
            "incumplidos": 0,
            "en_curso": 0,
            "duracion_ms": 15,
            "fallido": 0,
        }

    async def fake_esperar(delay_s: float, stop_event: Any) -> bool:
        esperas.append(delay_s)
        return False

    monkeypatch.setattr(sla_mod, "evaluar_sla_ciclo", fake_ciclo)
    monkeypatch.setattr(sla_mod, "_esperar_backoff", fake_esperar)

    fake_db = _FakeDb()
    res = await evaluar_sla(
        fake_db,  # type: ignore[arg-type]
        max_reintentos=3,
        backoff_base_s=2.0,
    )

    assert intentos == 3
    assert esperas == [2.0, 4.0]
    assert fake_db.rollbacks == 2
    assert res["fallido"] == 0
    assert res["en_riesgo"] == 1


@pytest.mark.asyncio
async def test_evaluar_sla_registra_fallo_tras_agotar_reintentos(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Al agotarse los reintentos, persiste estado fallido sin lanzar excepción letal."""
    llamadas_estado: list[dict[str, Any]] = []

    class _FakeDb:
        def in_transaction(self) -> bool:
            return True

        async def rollback(self) -> None:
            return None

    async def fake_ciclo(db: Any, **kwargs: Any) -> dict[str, int]:
        raise ConnectionError("postgresql temporalmente inaccesible")

    async def fake_registrar_estado(db: Any, **kwargs: Any) -> None:
        llamadas_estado.append(kwargs)

    async def fake_esperar(delay_s: float, stop_event: Any) -> bool:
        return False

    monkeypatch.setattr(sla_mod, "evaluar_sla_ciclo", fake_ciclo)
    monkeypatch.setattr(sla_mod, "registrar_estado_sla", fake_registrar_estado)
    monkeypatch.setattr(sla_mod, "_esperar_backoff", fake_esperar)

    res = await evaluar_sla(
        _FakeDb(),  # type: ignore[arg-type]
        max_reintentos=3,
        backoff_base_s=0.5,
    )

    assert res["fallido"] == 1
    assert len(llamadas_estado) == 1
    assert llamadas_estado[0]["status"] == "fallido"
    assert "postgresql temporalmente inaccesible" in str(llamadas_estado[0]["error_mensaje"])


@pytest.mark.asyncio
async def test_evaluar_sla_stop_event_y_cancelled_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Aborta limpio durante el backoff ante stop_event y propaga CancelledError."""
    stop = asyncio.Event()

    class _FakeDb:
        def in_transaction(self) -> bool:
            return False

        async def rollback(self) -> None:
            return None

    async def fake_ciclo_transitorio(db: Any, **kwargs: Any) -> dict[str, int]:
        stop.set()
        raise TimeoutError("transitorio")

    monkeypatch.setattr(sla_mod, "evaluar_sla_ciclo", fake_ciclo_transitorio)
    res = await evaluar_sla(
        _FakeDb(),  # type: ignore[arg-type]
        max_reintentos=3,
        backoff_base_s=30.0,
        stop_event=stop,
    )
    assert res["fallido"] == 0

    monkeypatch.setattr(
        sla_mod,
        "evaluar_sla_ciclo",
        AsyncMock(side_effect=asyncio.CancelledError()),
    )
    with pytest.raises(asyncio.CancelledError):
        await evaluar_sla(_FakeDb())  # type: ignore[arg-type]


# ============================================================ 2. Integración PG16
@pytest.mark.integracion
@pytest.mark.asyncio
async def test_sla_worker_evalua_riesgo_75_incumplimiento_y_respeta_pausas(
    entorno: None,
    super_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Detecta > 75 % (en_riesgo), > 100 % (incumplido) y descuenta pausas."""
    caplog.set_level(logging.INFO, logger="kallicode")
    prefijo = "sla_wrk_int_"
    tid_risk = f"{prefijo}org_risk"
    tid_breach = f"{prefijo}org_breach"
    tid_pause = f"{prefijo}org_pause"
    tk_risk = f"{prefijo}tk_risk"
    tk_breach = f"{prefijo}tk_breach"
    tk_pause = f"{prefijo}tk_pause"
    job_risk = f"{prefijo}job_risk"
    job_breach = f"{prefijo}job_breach"
    job_pause = f"{prefijo}job_pause"
    ahora = datetime.now(UTC)

    warnings_capturados: list[tuple[str, dict[str, Any]]] = []
    criticals_capturados: list[tuple[str, dict[str, Any]]] = []
    orig_warning = sla_mod.log.warning
    orig_critical = sla_mod.log.critical

    def spy_warning(event: str, **kwargs: Any) -> Any:
        warnings_capturados.append((event, kwargs))
        return orig_warning(event, **kwargs)

    def spy_critical(event: str, **kwargs: Any) -> Any:
        criticals_capturados.append((event, kwargs))
        return orig_critical(event, **kwargs)

    monkeypatch.setattr(sla_mod.log, "warning", spy_warning)
    monkeypatch.setattr(sla_mod.log, "critical", spy_critical)

    try:
        for tid in (tid_risk, tid_breach, tid_pause):
            await _sembrar_tenant_con_plan(super_session, tid, "growth")  # objetivo 24h

        for tkid, tid, titulo in (
            (tk_risk, tid_risk, "Ticket Riesgo 79pct"),
            (tk_breach, tid_breach, "Ticket Incumplido 108pct"),
            (tk_pause, tid_pause, "Ticket Pausado Gate2"),
        ):
            await super_session.execute(
                text(
                    """
                    INSERT INTO core.tickets
                        (id, tenant_id, tipo, titulo, descripcion, prioridad, etapa, origen)
                    VALUES (
                        :tk, :tid, 'bug', :titulo, 'Prueba SLA Worker',
                        'alta', 'build', 'portal'
                    )
                    """
                ),
                {"tk": tkid, "tid": tid, "titulo": titulo},
            )

        # Caso 1: Growth 24h, activo 19h => ~79.17% (>75%, <80% del seed SQL; valida B1)
        t_risk = ahora - timedelta(hours=19)
        await super_session.execute(
            text(
                """
                INSERT INTO core.jobs
                    (id, tenant_id, ticket_id, estado, prioridad, creado_en, terminado_en)
                VALUES (:jid, :tid, :tk, 'build', 'P1', :ini, NULL)
                """
            ),
            {"jid": job_risk, "tid": tid_risk, "tk": tk_risk, "ini": t_risk},
        )
        await super_session.execute(
            text(
                """
                INSERT INTO core.job_transitions
                    (tenant_id, job_id, de_estado, a_estado, creado_en)
                VALUES (:tid, :jid, 'pendiente_asignacion', 'build', :ini)
                """
            ),
            {"tid": tid_risk, "jid": job_risk, "ini": t_risk},
        )

        # Caso 2: Growth 24h, activo hace 26h => ~108.33% (>100%, incumplido activo)
        t_breach = ahora - timedelta(hours=26)
        await super_session.execute(
            text(
                """
                INSERT INTO core.jobs
                    (id, tenant_id, ticket_id, estado, prioridad, creado_en, terminado_en)
                VALUES (:jid, :tid, :tk, 'build', 'P1', :ini, NULL)
                """
            ),
            {"jid": job_breach, "tid": tid_breach, "tk": tk_breach, "ini": t_breach},
        )
        await super_session.execute(
            text(
                """
                INSERT INTO core.job_transitions
                    (tenant_id, job_id, de_estado, a_estado, creado_en)
                VALUES (:tid, :jid, 'pendiente_asignacion', 'build', :ini)
                """
            ),
            {"tid": tid_breach, "jid": job_breach, "ini": t_breach},
        )

        # Caso 3: Growth 24h, inicio 30h: 5h en build + 25h pausado en gate2
        t_pause = ahora - timedelta(hours=30)
        await super_session.execute(
            text(
                """
                INSERT INTO core.jobs
                    (id, tenant_id, ticket_id, estado, prioridad, creado_en, terminado_en)
                VALUES (:jid, :tid, :tk, 'gate2', 'P2', :ini, NULL)
                """
            ),
            {"jid": job_pause, "tid": tid_pause, "tk": tk_pause, "ini": t_pause},
        )
        await super_session.execute(
            text(
                """
                INSERT INTO core.job_transitions
                    (tenant_id, job_id, de_estado, a_estado, creado_en)
                VALUES
                    (:tid, :jid, 'pendiente_asignacion', 'build', :t0),
                    (:tid, :jid, 'build', 'gate2', :t1)
                """
            ),
            {
                "tid": tid_pause,
                "jid": job_pause,
                "t0": t_pause,
                "t1": t_pause + timedelta(hours=5),
            },
        )
        await super_session.commit()

        async with admin_session() as db:
            resumen = await evaluar_sla_ciclo(db, trace_id="tr_worker_sla_test")

        assert resumen["en_riesgo"] >= 1
        assert resumen["incumplidos"] >= 1
        assert resumen["en_curso"] >= 1

        filas = (
            (
                await super_session.execute(
                    text(
                        """
                    SELECT job_id, resultado, bruto_h, transcurrido_h
                      FROM admin.sla_cases
                     WHERE job_id IN (:j1, :j2, :j3)
                     ORDER BY job_id
                    """
                    ),
                    {"j1": job_risk, "j2": job_breach, "j3": job_pause},
                )
            )
            .mappings()
            .all()
        )
        por_job = {f["job_id"]: f for f in filas}

        assert por_job[job_risk]["resultado"] == "en_riesgo"
        assert por_job[job_breach]["resultado"] == "incumplido"
        assert por_job[job_pause]["resultado"] == "en_curso"
        assert float(por_job[job_pause]["bruto_h"]) >= 29.9
        assert float(por_job[job_pause]["transcurrido_h"]) <= 5.2

        # Verificar sincronización de agregados mensuales y aggregate_state
        agg_filas = (
            (
                await super_session.execute(
                    text(
                        """
                    SELECT tenant_id, casos_en_riesgo, casos_incumplidos, casos_en_curso
                      FROM admin.agg_sla_compliance
                     WHERE tenant_id IN (:t1, :t2, :t3)
                    """
                    ),
                    {"t1": tid_risk, "t2": tid_breach, "t3": tid_pause},
                )
            )
            .mappings()
            .all()
        )
        agg_por_tenant = {f["tenant_id"]: f for f in agg_filas}
        assert agg_por_tenant[tid_risk]["casos_en_riesgo"] == 1
        assert agg_por_tenant[tid_breach]["casos_incumplidos"] == 1
        assert agg_por_tenant[tid_pause]["casos_en_curso"] == 1

        estados = (
            (
                await super_session.execute(
                    text(
                        """
                    SELECT agregado, status, error, duration_ms
                      FROM admin.aggregate_state
                     WHERE agregado IN ('sla_cases', 'agg_sla_compliance')
                    """
                    )
                )
            )
            .mappings()
            .all()
        )
        assert len(estados) == 2
        for st in estados:
            assert st["status"] == "ok"
            assert st["error"] is None
            assert st["duration_ms"] is not None

        # Verificar alertas estructuradas emitidas
        riesgo_ev = [
            kw for ev, kw in warnings_capturados if ev == "admin.ops.sla_caso_en_riesgo"
        ]
        incump_ev = [
            kw for ev, kw in criticals_capturados if ev == "admin.ops.sla_caso_incumplido"
        ]
        assert any(
            kw["job_id"] == job_risk
            and kw["ticket_id"] == tk_risk
            and kw["plan"] == "growth"
            and kw["porcentaje_consumido"] > 75.0
            and kw["trace_id"] == "tr_worker_sla_test"
            for kw in riesgo_ev
        )
        assert any(
            kw["job_id"] == job_breach
            and kw["ticket_id"] == tk_breach
            and kw["plan"] == "growth"
            and kw["porcentaje_consumido"] > 100.0
            and kw["trace_id"] == "tr_worker_sla_test"
            for kw in incump_ev
        )
        mensajes = [r.getMessage() for r in caplog.records]
        assert "admin.ops.sla_caso_en_riesgo" in mensajes
        assert "admin.ops.sla_caso_incumplido" in mensajes
    finally:
        await _limpiar_prefijo(super_session, prefijo)


@pytest.mark.integracion
@pytest.mark.asyncio
async def test_sla_worker_idempotente_y_recuperacion_tras_fallo(
    entorno: None,
    super_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ejecuciones consecutivas con advisory lock son idempotentes y el fallo se recupera."""
    prefijo = "sla_wrk_idem_"
    tid = f"{prefijo}org"
    tkid = f"{prefijo}tk"
    jid = f"{prefijo}job"
    t0 = datetime.now(UTC) - timedelta(hours=19)

    try:
        await _sembrar_tenant_con_plan(super_session, tid, "growth")
        await super_session.execute(
            text(
                """
                INSERT INTO core.tickets
                    (id, tenant_id, tipo, titulo, descripcion, prioridad, etapa, origen)
                VALUES (:tk, :tid, 'bug', 'Idempotencia', 'Detalle', 'alta', 'build', 'portal')
                """
            ),
            {"tk": tkid, "tid": tid},
        )
        await super_session.execute(
            text(
                """
                INSERT INTO core.jobs
                    (id, tenant_id, ticket_id, estado, prioridad, creado_en, terminado_en)
                VALUES (:jid, :tid, :tk, 'build', 'P1', :ini, NULL)
                """
            ),
            {"jid": jid, "tid": tid, "tk": tkid, "ini": t0},
        )
        await super_session.execute(
            text(
                """
                INSERT INTO core.job_transitions
                    (tenant_id, job_id, de_estado, a_estado, creado_en)
                VALUES (:tid, :jid, 'pendiente_asignacion', 'build', :ini)
                """
            ),
            {"tid": tid, "jid": jid, "ini": t0},
        )
        await super_session.commit()

        # 2 ejecuciones seguidas con líder
        assert await ejecutar_con_lider("evaluar_sla", evaluar_sla) is True
        assert await ejecutar_con_lider("evaluar_sla", evaluar_sla) is True

        filas = (
            (
                await super_session.execute(
                    text("SELECT resultado FROM admin.sla_cases WHERE job_id = :jid"),
                    {"jid": jid},
                )
            )
            .scalars()
            .all()
        )
        assert filas == ["en_riesgo"]

        # Simular fallo persistente de ciclo en BD y verificar status='fallido'
        orig_ciclo = sla_mod.evaluar_sla_ciclo

        async def ciclo_falla(db: AsyncSession, **kwargs: Any) -> dict[str, int]:
            raise RuntimeError("fallo_simulado_en_ciclo_sla")

        monkeypatch.setattr(sla_mod, "evaluar_sla_ciclo", ciclo_falla)
        assert await ejecutar_con_lider("evaluar_sla", evaluar_sla) is True

        estados_fail = (
            (
                await super_session.execute(
                    text(
                        """
                    SELECT agregado, status, error
                      FROM admin.aggregate_state
                     WHERE agregado IN ('sla_cases', 'agg_sla_compliance')
                    """
                    )
                )
            )
            .mappings()
            .all()
        )
        assert len(estados_fail) == 2
        for st in estados_fail:
            assert st["status"] == "fallido"
            assert "fallo_simulado_en_ciclo_sla" in str(st["error"])

        # Restaurar y verificar recuperación en el siguiente ciclo
        monkeypatch.setattr(sla_mod, "evaluar_sla_ciclo", orig_ciclo)
        assert await ejecutar_con_lider("evaluar_sla", evaluar_sla) is True

        estados_ok = (
            (
                await super_session.execute(
                    text(
                        """
                    SELECT agregado, status, error
                      FROM admin.aggregate_state
                     WHERE agregado IN ('sla_cases', 'agg_sla_compliance')
                    """
                    )
                )
            )
            .mappings()
            .all()
        )
        for st in estados_ok:
            assert st["status"] == "ok"
            assert st["error"] is None
    finally:
        await _limpiar_prefijo(super_session, prefijo)
