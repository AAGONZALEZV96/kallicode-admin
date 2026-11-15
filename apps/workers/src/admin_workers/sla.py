"""Evaluación continua y asíncrona de SLA, pausas y alertas operativas (§18.27-§18.28).

Ejecuta periódicamente:
1. ``admin.refresh_sla(p_dias, p_forzar)`` para materializar tramos y actualizar
   ``admin.sla_cases`` y ``admin.agg_sla_compliance``.
2. ``admin.calcular_reloj_caso(p_job_id)`` sobre casos activos (``terminado_en IS NULL``)
   evaluando el umbral de riesgo del 75 % e incumplimientos (> 100 %), preservando
   estrictamente las deducciones de pausa (``computa = false``).
3. Sincronización de estado operativo en ``admin.aggregate_state`` (``sla_cases`` y
   ``agg_sla_compliance``) con reintentos de backoff exponencial ante fallos transitorios.
"""

from __future__ import annotations

import asyncio
import os
import time
import uuid
from decimal import Decimal
from typing import Any

from admin_api.db import admin_session, todos, uno
from kallicode_core.logging import bind_contexto, log
from sqlalchemy import text
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

DEFAULT_SLA_INTERVAL_S: int = 300
DEFAULT_SLA_DIAS: int = 95
DEFAULT_RIESGO_RATIO: float = 0.75
DEFAULT_MAX_REINTENTOS: int = 3
DEFAULT_BACKOFF_BASE_S: float = 2.0

SLA_AGGREGATES: tuple[str, str] = ("sla_cases", "agg_sla_compliance")
ESTADOS_AGGREGATE_VALIDOS: frozenset[str] = frozenset(
    {"pendiente", "refrescando", "ok", "fallido"}
)
SQLSTATES_TRANSITORIOS: frozenset[str] = frozenset(
    {
        "40P01",  # deadlock_detected
        "40001",  # serialization_failure
        "55P03",  # lock_not_available
        "57P03",  # cannot_connect_now
        "53300",  # too_many_connections
    }
)


def obtener_intervalo_sla_s() -> int:
    """Obtiene el intervalo de evaluación SLA desde ``SLA_EVALUATION_INTERVAL_S``."""
    raw = os.environ.get("SLA_EVALUATION_INTERVAL_S")
    if raw is None or not raw.strip():
        raw = os.environ.get("KC_ADMIN_SLA_EVALUATION_INTERVAL_S")
    if raw is None or not raw.strip():
        return DEFAULT_SLA_INTERVAL_S
    try:
        valor = int(raw.strip())
    except ValueError:
        log.warning(
            "admin.workers.sla_intervalo_invalido",
            valor=raw,
            fallback_s=DEFAULT_SLA_INTERVAL_S,
        )
        return DEFAULT_SLA_INTERVAL_S
    if valor < 1:
        log.warning(
            "admin.workers.sla_intervalo_invalido",
            valor=valor,
            fallback_s=DEFAULT_SLA_INTERVAL_S,
        )
        return DEFAULT_SLA_INTERVAL_S
    return valor


def _to_float(val: Any) -> float:
    """Convierte valores numéricos SQL (``Decimal``, ``int``, ``float``) a ``float``."""
    if val is None:
        return 0.0
    if isinstance(val, Decimal):
        return float(val)
    return float(val)


def es_error_transitorio_bd(exc: BaseException) -> bool:
    """Determina si una excepción corresponde a un fallo transitorio de conexión o bloqueo."""
    visitados: set[int] = set()
    pendientes: list[BaseException | None] = [exc]
    while pendientes:
        actual = pendientes.pop()
        if actual is None or id(actual) in visitados:
            continue
        visitados.add(id(actual))

        if isinstance(actual, TimeoutError | ConnectionError | OSError | OperationalError):
            return True

        for attr in ("pgcode", "sqlstate"):
            codigo = getattr(actual, attr, None)
            if isinstance(codigo, str) and (
                codigo in SQLSTATES_TRANSITORIOS or codigo.startswith("08")
            ):
                return True

        orig = getattr(actual, "orig", None)
        if isinstance(orig, BaseException):
            pendientes.append(orig)
        if actual.__cause__ is not None:
            pendientes.append(actual.__cause__)
        if actual.__context__ is not None:
            pendientes.append(actual.__context__)
    return False


async def _rollback_seguro(db: AsyncSession) -> None:
    """Revierte cualquier transacción abortada sin propagar errores secundarios."""
    try:
        if db.in_transaction():
            await db.rollback()
    except Exception:
        pass


async def _esperar_backoff(delay_s: float, stop_event: asyncio.Event | None) -> bool:
    """Espera el backoff exponencial respondiendo de inmediato al apagado ordenado.

    Retorna ``True`` si se solicitó detener el worker durante la espera.
    """
    if delay_s <= 0:
        return stop_event.is_set() if stop_event is not None else False
    if stop_event is None:
        await asyncio.sleep(delay_s)
        return False
    if stop_event.is_set():
        return True
    try:
        await asyncio.wait_for(stop_event.wait(), timeout=delay_s)
        return True
    except TimeoutError:
        return False


async def registrar_estado_sla(
    db: AsyncSession,
    *,
    status: str,
    duracion_ms: int,
    filas_procesadas: int,
    error_mensaje: str | None = None,
) -> None:
    """Actualiza ``admin.aggregate_state`` para ``sla_cases`` y ``agg_sla_compliance``."""
    if status not in ESTADOS_AGGREGATE_VALIDOS:
        raise ValueError(f"Estado inválido para admin.aggregate_state: {status!r}")

    error_limpio = error_mensaje[:1000] if error_mensaje else None
    sql = text(
        """
        INSERT INTO admin.aggregate_state
            (agregado, refreshed_at, duration_ms, rows_total, status, error)
        VALUES
            (:agregado, now(), :duration_ms, :rows_total, :status, :error)
        ON CONFLICT (agregado) DO UPDATE SET
            refreshed_at = now(),
            duration_ms  = excluded.duration_ms,
            rows_total   = excluded.rows_total,
            status       = excluded.status,
            error        = excluded.error
        """
    )
    for agregado in SLA_AGGREGATES:
        await db.execute(
            sql,
            {
                "agregado": agregado,
                "duration_ms": max(0, duracion_ms),
                "rows_total": max(0, filas_procesadas),
                "status": status,
                "error": error_limpio,
            },
        )


async def _sincronizar_cumplimiento_ciclo_tenant(
    db: AsyncSession, pares: set[tuple[str, str]]
) -> None:
    """Recalcula filas afectadas en ``admin.agg_sla_compliance`` desde ``admin.sla_cases``."""
    sql = text(
        """
        WITH resumen AS (
            SELECT to_char(sc.iniciado_en, 'YYYY-MM') AS ciclo,
                   sc.tenant_id,
                   max(sc.plan_codigo) AS plan_codigo,
                   count(*)::int AS casos_totales,
                   count(*) FILTER (
                       WHERE sc.resultado IN ('dentro', 'incumplido')
                   )::int AS casos_evaluados,
                   count(*) FILTER (WHERE sc.resultado = 'dentro')::int AS casos_dentro,
                   count(*) FILTER (
                       WHERE sc.resultado = 'incumplido'
                   )::int AS casos_incumplidos,
                   count(*) FILTER (WHERE sc.resultado = 'en_riesgo')::int AS casos_en_riesgo,
                   count(*) FILTER (WHERE sc.resultado = 'en_curso')::int AS casos_en_curso,
                   count(*) FILTER (
                       WHERE sc.resultado = 'sin_objetivo'
                   )::int AS casos_sin_objetivo,
                   round(
                       100.0 * count(*) FILTER (WHERE sc.resultado = 'dentro')
                       / nullif(
                           count(*) FILTER (WHERE sc.resultado IN ('dentro', 'incumplido')),
                           0
                       ),
                       2
                   )::numeric(5,2) AS cumplimiento_pct,
                   coalesce(sum(sc.bruto_h), 0.00)::numeric(12,2) AS bruto_total_h,
                   coalesce(sum(sc.transcurrido_h), 0.00)::numeric(12,2) AS transcurrido_total_h
              FROM admin.sla_cases sc
             WHERE to_char(sc.iniciado_en, 'YYYY-MM') = :ciclo
               AND sc.tenant_id = :tenant_id
             GROUP BY to_char(sc.iniciado_en, 'YYYY-MM'), sc.tenant_id
        )
        INSERT INTO admin.agg_sla_compliance (
            ciclo, tenant_id, plan_codigo, objetivo_h,
            casos_totales, casos_evaluados, casos_dentro,
            casos_incumplidos, casos_en_riesgo, casos_en_curso,
            casos_sin_objetivo, cumplimiento_pct,
            bruto_total_h, transcurrido_total_h, actualizado_en
        )
        SELECT r.ciclo,
               r.tenant_id,
               r.plan_codigo,
               (
                   SELECT t.objetivo_h
                     FROM admin.sla_targets t
                    WHERE t.plan_codigo = r.plan_codigo
                      AND t.etapa IN ('total_e2e', '*')
                      AND t.activo = true
                    ORDER BY (t.etapa = 'total_e2e') DESC, t.vigente_desde DESC
                    LIMIT 1
               ),
               r.casos_totales,
               r.casos_evaluados,
               r.casos_dentro,
               r.casos_incumplidos,
               r.casos_en_riesgo,
               r.casos_en_curso,
               r.casos_sin_objetivo,
               r.cumplimiento_pct,
               r.bruto_total_h,
               r.transcurrido_total_h,
               now()
          FROM resumen r
        ON CONFLICT (ciclo, tenant_id) DO UPDATE SET
            plan_codigo          = excluded.plan_codigo,
            objetivo_h           = excluded.objetivo_h,
            casos_totales        = excluded.casos_totales,
            casos_evaluados      = excluded.casos_evaluados,
            casos_dentro         = excluded.casos_dentro,
            casos_incumplidos    = excluded.casos_incumplidos,
            casos_en_riesgo      = excluded.casos_en_riesgo,
            casos_en_curso       = excluded.casos_en_curso,
            casos_sin_objetivo   = excluded.casos_sin_objetivo,
            cumplimiento_pct     = excluded.cumplimiento_pct,
            bruto_total_h        = excluded.bruto_total_h,
            transcurrido_total_h = excluded.transcurrido_total_h,
            actualizado_en       = now()
        """
    )
    for ciclo, tenant_id in sorted(pares):
        await db.execute(sql, {"ciclo": ciclo, "tenant_id": tenant_id})


async def evaluar_sla_ciclo(
    db: AsyncSession,
    *,
    dias: int = DEFAULT_SLA_DIAS,
    forzar: bool = False,
    ratio_riesgo: float = DEFAULT_RIESGO_RATIO,
    trace_id: str | None = None,
) -> dict[str, int]:
    """Ejecuta un ciclo completo de evaluación SLA reutilizando ``db`` sin sesiones anidadas."""
    cid = trace_id or f"tr_{uuid.uuid4().hex[:16]}"
    bind_contexto(worker="evaluar_sla", trace_id=cid)
    inicio = time.monotonic()

    refrescado = await uno(
        db,
        "SELECT admin.refresh_sla(:dias, :forzar) AS total",
        {"dias": dias, "forzar": forzar},
    )
    filas_refrescadas = int(refrescado["total"] or 0) if refrescado is not None else 0

    activos = await todos(
        db,
        """
        SELECT sc.job_id,
               sc.tenant_id,
               sc.ticket_id,
               sc.ticket_numero,
               sc.plan_codigo,
               sc.objetivo_h,
               sc.bruto_h,
               sc.transcurrido_h,
               sc.resultado,
               to_char(sc.iniciado_en, 'YYYY-MM') AS ciclo
          FROM admin.sla_cases sc
         WHERE sc.terminado_en IS NULL
         ORDER BY sc.iniciado_en ASC
        """,
    )

    en_riesgo = 0
    incumplidos = 0
    en_curso = 0
    pares_afectados: set[tuple[str, str]] = set()
    update_caso_sql = text(
        """
        UPDATE admin.sla_cases
           SET resultado      = :resultado,
               transcurrido_h = :transcurrido_h,
               bruto_h        = :bruto_h,
               calculado_en   = now()
         WHERE job_id = :job_id
        """
    )

    for caso in activos:
        job_id = str(caso["job_id"])
        reloj = await uno(
            db,
            """
            SELECT job_id,
                   tenant_id,
                   plan_codigo,
                   objetivo_h,
                   transcurrido_h,
                   bruto_h,
                   resultado
              FROM admin.calcular_reloj_caso(:job_id)
            """,
            {"job_id": job_id},
        )
        objetivo_raw = reloj["objetivo_h"] if reloj is not None else caso["objetivo_h"]
        if objetivo_raw is None or _to_float(objetivo_raw) <= 0.0:
            continue

        objetivo_h = _to_float(objetivo_raw)
        transcurrido_h = (
            _to_float(reloj["transcurrido_h"])
            if reloj is not None
            else _to_float(caso["transcurrido_h"])
        )
        bruto_h = (
            _to_float(reloj["bruto_h"]) if reloj is not None else _to_float(caso["bruto_h"])
        )
        plan = str(
            (reloj["plan_codigo"] if reloj is not None else None)
            or caso["plan_codigo"]
            or "sin_plan"
        )
        tenant_id = str(caso["tenant_id"])
        ticket_id = caso.get("ticket_id")
        porcentaje_consumido = round((transcurrido_h / objetivo_h) * 100.0, 2)

        if transcurrido_h > objetivo_h:
            nuevo_resultado = "incumplido"
            incumplidos += 1
            log.critical(
                "admin.ops.sla_caso_incumplido",
                job_id=job_id,
                ticket_id=ticket_id,
                ticket_numero=caso.get("ticket_numero"),
                tenant_id=tenant_id,
                plan=plan,
                objetivo_h=round(objetivo_h, 2),
                transcurrido_h=round(transcurrido_h, 2),
                porcentaje_consumido=porcentaje_consumido,
                trace_id=cid,
            )
        elif transcurrido_h > objetivo_h * ratio_riesgo:
            nuevo_resultado = "en_riesgo"
            en_riesgo += 1
            log.warning(
                "admin.ops.sla_caso_en_riesgo",
                job_id=job_id,
                ticket_id=ticket_id,
                ticket_numero=caso.get("ticket_numero"),
                tenant_id=tenant_id,
                plan=plan,
                objetivo_h=round(objetivo_h, 2),
                transcurrido_h=round(transcurrido_h, 2),
                porcentaje_consumido=porcentaje_consumido,
                trace_id=cid,
            )
        else:
            nuevo_resultado = "en_curso"
            en_curso += 1

        if str(caso["resultado"]) != nuevo_resultado:
            await db.execute(
                update_caso_sql,
                {
                    "job_id": job_id,
                    "resultado": nuevo_resultado,
                    "transcurrido_h": round(transcurrido_h, 2),
                    "bruto_h": round(max(bruto_h, transcurrido_h), 2),
                },
            )
            pares_afectados.add((str(caso["ciclo"]), tenant_id))

    if pares_afectados:
        await _sincronizar_cumplimiento_ciclo_tenant(db, pares_afectados)

    duracion_ms = max(0, int((time.monotonic() - inicio) * 1000))
    await registrar_estado_sla(
        db,
        status="ok",
        duracion_ms=duracion_ms,
        filas_procesadas=filas_refrescadas,
        error_mensaje=None,
    )

    log.info(
        "admin.workers.sla_evaluado",
        refrescados=filas_refrescadas,
        activos_evaluados=len(activos),
        en_riesgo=en_riesgo,
        incumplidos=incumplidos,
        en_curso=en_curso,
        duracion_ms=duracion_ms,
        trace_id=cid,
    )
    return {
        "refrescados": filas_refrescadas,
        "activos_evaluados": len(activos),
        "en_riesgo": en_riesgo,
        "incumplidos": incumplidos,
        "en_curso": en_curso,
        "duracion_ms": duracion_ms,
        "fallido": 0,
    }


async def _registrar_fallo_seguro(
    db: AsyncSession,
    *,
    duracion_ms: int,
    error_mensaje: str,
) -> None:
    """Persiste estado ``fallido`` en ``db`` tras rollback o sesión limpia."""
    try:
        await registrar_estado_sla(
            db,
            status="fallido",
            duracion_ms=duracion_ms,
            filas_procesadas=0,
            error_mensaje=error_mensaje,
        )
        return
    except Exception:
        await _rollback_seguro(db)

    try:
        async with admin_session() as sesion_recuperacion:
            await registrar_estado_sla(
                sesion_recuperacion,
                status="fallido",
                duracion_ms=duracion_ms,
                filas_procesadas=0,
                error_mensaje=error_mensaje,
            )
    except Exception as exc_rec:
        log.error("admin.workers.sla_estado_fallo_no_persistido", error=str(exc_rec))


async def evaluar_sla(
    db: AsyncSession,
    *,
    dias: int = DEFAULT_SLA_DIAS,
    forzar: bool = False,
    ratio_riesgo: float = DEFAULT_RIESGO_RATIO,
    max_reintentos: int = DEFAULT_MAX_REINTENTOS,
    backoff_base_s: float = DEFAULT_BACKOFF_BASE_S,
    stop_event: asyncio.Event | None = None,
    trace_id: str | None = None,
) -> dict[str, int]:
    """Trabajo periódico de evaluación SLA con backoff exponencial y registro de fallos."""
    cid = trace_id or f"tr_{uuid.uuid4().hex[:16]}"
    inicio = time.monotonic()
    reintentos_totales = max(1, max_reintentos)

    for intento in range(reintentos_totales):
        try:
            return await evaluar_sla_ciclo(
                db,
                dias=dias,
                forzar=forzar,
                ratio_riesgo=ratio_riesgo,
                trace_id=cid,
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            await _rollback_seguro(db)
            transitorio = es_error_transitorio_bd(exc)
            if transitorio and intento < reintentos_totales - 1:
                espera_s = backoff_base_s * (2**intento)
                log.warning(
                    "admin.workers.sla_reintento",
                    intento=intento + 1,
                    max_reintentos=reintentos_totales,
                    espera_s=espera_s,
                    error=str(exc),
                    trace_id=cid,
                )
                detenido = await _esperar_backoff(espera_s, stop_event)
                if detenido:
                    duracion_ms = max(0, int((time.monotonic() - inicio) * 1000))
                    return {
                        "refrescados": 0,
                        "activos_evaluados": 0,
                        "en_riesgo": 0,
                        "incumplidos": 0,
                        "en_curso": 0,
                        "duracion_ms": duracion_ms,
                        "fallido": 0,
                    }
                continue

            duracion_ms = max(0, int((time.monotonic() - inicio) * 1000))
            log.error(
                "admin.workers.sla_fallo",
                intentos=intento + 1,
                transitorio=transitorio,
                error=str(exc),
                trace_id=cid,
            )
            await _registrar_fallo_seguro(
                db,
                duracion_ms=duracion_ms,
                error_mensaje=str(exc),
            )
            return {
                "refrescados": 0,
                "activos_evaluados": 0,
                "en_riesgo": 0,
                "incumplidos": 0,
                "en_curso": 0,
                "duracion_ms": duracion_ms,
                "fallido": 1,
            }

    return {
        "refrescados": 0,
        "activos_evaluados": 0,
        "en_riesgo": 0,
        "incumplidos": 0,
        "en_curso": 0,
        "duracion_ms": 0,
        "fallido": 1,
    }


__all__ = [
    "DEFAULT_BACKOFF_BASE_S",
    "DEFAULT_MAX_REINTENTOS",
    "DEFAULT_RIESGO_RATIO",
    "DEFAULT_SLA_DIAS",
    "DEFAULT_SLA_INTERVAL_S",
    "SLA_AGGREGATES",
    "es_error_transitorio_bd",
    "evaluar_sla",
    "evaluar_sla_ciclo",
    "obtener_intervalo_sla_s",
    "registrar_estado_sla",
]
