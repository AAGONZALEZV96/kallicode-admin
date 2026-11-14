"""Workers de la consola de administración.

Tres trabajos programados, todos idempotentes y con elección de líder, porque los
ejecutan varias réplicas y el defecto BE-F18 del backend fue precisamente que el
worker de facturación corría en todas a la vez y podía avanzar el aniversario dos
meses:

  · `refrescar_agregados` · recalcula los agregados de negocio y los casos de
    nivel de servicio, y registra frescura y resultado por agregado. Un agregado
    que falla no impide refrescar los demás, y su fallo hace que la API devuelva
    503 en lugar de servir un dato viejo como si fuera actual.
  · `generar_informes` · toma los informes en cola, los genera respetando el
    enmascarado del solicitante, los sube al almacenamiento y solo entonces los
    marca como listos. El orden importa: el defecto BE-F19 fue marcar la
    exportación como lista tras descartar el contenido.
  · `caducar_concesiones` · cierra las concesiones vencidas y registra la
    caducidad en la auditoría, de modo que el registro refleje el fin del acceso y
    no solo su concesión.
"""

from __future__ import annotations

import asyncio
import signal
import uuid
from typing import Any

from admin_api.audit import registrar_accion
from admin_api.db import cerrar, read_session, todos, uno
from admin_api.servicios.blob import ruta_informe, subir_informe
from admin_api.settings import get_admin_settings
from kallicode_core.logging import bind_contexto, configurar_logging, log
from sqlalchemy import text

from admin_workers.lider import LOCK_IDS, ejecutar_con_lider
from admin_workers.sla import evaluar_sla, obtener_intervalo_sla_s

_parar = asyncio.Event()

# Bloqueo de asesoramiento por trabajo: solo la réplica que lo obtiene ejecuta.
_LOCKS: dict[str, int] = LOCK_IDS


async def _con_lider(nombre: str, cuerpo: Any) -> None:
    """Ejecuta el trabajo solo si esta réplica obtiene el bloqueo."""
    await ejecutar_con_lider(nombre, cuerpo)


# ------------------------------------------------------------------ agregados
async def comprobar_frescura_agregados(
    db: Any | None = None, max_antiguedad_s: int = 21_600
) -> list[dict[str, Any]]:
    """Verifica si algún agregado excede el umbral de antigüedad máxima.

    Emite alerta WARN admin.business.frescura_alta por cada agregado obsoleto.
    """
    if db is not None:
        filas = await todos(
            db,
            """
            SELECT agregado, rows_total, duration_ms,
                   refreshed_at, status, error,
                   EXTRACT(EPOCH FROM (now() - refreshed_at))::int AS antiguedad_s
            FROM admin.aggregate_state
            """,
        )
    else:
        async with read_session() as rdb:
            filas = await todos(
                rdb,
                """
                SELECT agregado, rows_total, duration_ms,
                       refreshed_at, status, error,
                       EXTRACT(EPOCH FROM (now() - refreshed_at))::int AS antiguedad_s
                FROM admin.aggregate_state
                """,
            )

    desactualizados: list[dict[str, Any]] = []
    for f in filas:
        antiguedad = f.get("antiguedad_s")
        if antiguedad is not None and antiguedad > max_antiguedad_s:
            minutos = antiguedad // 60
            log.warning(
                "admin.business.frescura_alta",
                agregado=f["agregado"],
                minutos_transcurridos=minutos,
                antiguedad_s=antiguedad,
                estado=f["status"],
            )
            desactualizados.append(f)
    return desactualizados


async def refrescar_agregados(db: Any) -> None:
    """Recalcula los agregados de negocio y los casos de nivel de servicio."""
    bind_contexto(worker="refrescar_agregados", trace_id=f"tr_{uuid.uuid4().hex[:16]}")
    s = get_admin_settings()

    filas = await todos(db, "SELECT * FROM admin.refresh_all_business_aggregates()")
    for f in filas:
        nivel = log.info if f["estado"] == "ok" else log.error
        nivel(
            "admin.agregado.refrescado",
            agregado=f["agregado"],
            filas=f["filas"],
            ms=f["ms"],
            estado=f["estado"],
        )
    fallidos = [f["agregado"] for f in filas if f["estado"] != "ok"]
    if fallidos:
        # No se lanza excepción: el resto de agregados sí se refrescó y la API ya
        # devuelve 503 para los que fallaron. Lanzar aquí solo perdería la traza.
        log.critical("admin.agregado.fallidos", agregados=fallidos)

    n = await uno(db, "SELECT admin.refresh_sla(95, false) AS n")
    log.info("admin.sla.recalculado", casos=int(n["n"]) if n else 0)

    await comprobar_frescura_agregados(max_antiguedad_s=s.aggregate_max_age_s)


# ------------------------------------------------------------------- informes
async def generar_informes(db: Any) -> None:
    """Genera los informes en cola, los sube y solo entonces los marca listos."""
    while True:
        pendientes = await todos(
            db,
            """
            UPDATE admin.reports SET status = 'generando'
            WHERE id IN (SELECT id FROM admin.reports
                          WHERE status = 'en_cola'
                          ORDER BY requested_at LIMIT 10 FOR UPDATE SKIP LOCKED)
            RETURNING id, kind, format, params, requested_by, includes_pii
        """,
        )
        if not pendientes:
            break
        for r in pendientes:
            await _generar_uno(r, db)


async def _generar_uno(r: dict[str, Any], db: Any) -> None:
    import json

    from admin_api.reports import generar_contenido_informe

    bind_contexto(report_id=r["id"])
    try:
        params = dict(r["params"] or {})
        if isinstance(r["params"], str):
            params = json.loads(r["params"])
        params.setdefault("report_id", r["id"])
        if r.get("requested_by"):
            params.setdefault("solicitante_id", r["requested_by"])

        formato = (r.get("format") or "csv").lower()
        datos, content_type, num_filas = await generar_contenido_informe(
            r["kind"],
            formato,
            params,
            r["includes_pii"],
        )

        blob_ref = ruta_informe(r["id"], formato)
        # La subida va ANTES de marcar como listo: si falla, el informe queda
        # fallido y no se entrega una URL a un fichero inexistente.
        digest = await subir_informe(blob_ref, datos, content_type)

        await uno(
            db,
            """
            UPDATE admin.reports
            SET status = 'listo', blob_ref = :b, sha256 = :h,
                rows_total = :n, completed_at = now(), error = NULL
            WHERE id = :i RETURNING id
        """,
            {"b": blob_ref, "h": digest, "n": num_filas, "i": r["id"]},
        )
        if hasattr(db, "commit"):
            await db.commit()
        log.info(
            "admin.informe.generado",
            report_id=r["id"],
            filas=num_filas,
            bytes=len(datos),
            identificables=r["includes_pii"],
        )

    except Exception as exc:
        await db.execute(
            text(
                """
            UPDATE admin.reports
            SET status = 'fallido', blob_ref = NULL,
                error = jsonb_build_object(
                    'codigo', 'GENERACION_FALLIDA',
                    'mensaje', CAST(:m AS text),
                    'tipo', CAST(:t AS text),
                    'cuando', now()::text
                ),
                completed_at = now()
            WHERE id = :i
        """
            ),
            {"m": str(exc), "t": type(exc).__name__, "i": r["id"]},
        )
        if hasattr(db, "commit"):
            await db.commit()
        log.error("admin.informe.fallido", report_id=r["id"], excepcion=type(exc).__name__)


# --------------------------------------------------------------- concesiones
async def caducar_concesiones(db: Any) -> None:
    """Registra la caducidad de las concesiones vencidas.

    La concesión ya no es válida por su propio vencimiento —las consultas filtran
    por `expires_at > now()`—, pero el registro de auditoría debe reflejar también
    el fin del acceso: un registro que solo anota concesiones y nunca su cierre
    cuenta media historia.
    """
    vencidas = await todos(
        db,
        """
        SELECT g.id, g.staff_id, g.tenant_id, g.scope, g.reason, g.reads,
               s.role AS staff_role
        FROM admin.access_grants g
        JOIN admin.staff s ON s.id = g.staff_id
        WHERE g.revoked_at IS NULL AND g.expires_at <= now()
          AND NOT EXISTS (
              SELECT 1 FROM admin.staff_actions a
               WHERE a.grant_id = g.id AND a.action = 'grant_revoked')
    """,
    )
    for g in vencidas:
        await registrar_accion(
            db,
            staff_id=g["staff_id"],
            staff_role=g["staff_role"],
            action="grant_revoked",
            endpoint="worker:caducar_concesiones",
            tenant_id=g["tenant_id"],
            grant_id=g["id"],
            scope=g["scope"],
            reason=g["reason"],
            payload={"causa": "vencimiento", "lecturas": g["reads"]},
        )
    if vencidas:
        log.info("admin.grants.caducadas", n=len(vencidas))


async def _evaluar_sla_programado(db: Any) -> dict[str, int]:
    """Ejecuta la evaluación SLA propagando el evento global de parada."""
    return await evaluar_sla(db, stop_event=_parar)


# ------------------------------------------------------------------ runner
_TRABAJOS: dict[str, tuple[Any, int]] = {
    "refrescar_agregados": (refrescar_agregados, 900),
    "generar_informes": (generar_informes, 30),
    "caducar_concesiones": (caducar_concesiones, 300),
    "evaluar_sla": (_evaluar_sla_programado, 300),
}


async def _bucle(nombre: str, cuerpo: Any, intervalo: int) -> None:
    while not _parar.is_set():
        try:
            await _con_lider(nombre, cuerpo)
        except Exception:
            pass  # ya registrado; el bucle no muere por un fallo
        try:
            await asyncio.wait_for(_parar.wait(), timeout=intervalo)
        except TimeoutError:
            continue


async def main() -> None:
    configurar_logging()
    s = get_admin_settings()
    log.info("admin.workers.arrancando", env=s.env, trabajos=sorted(_TRABAJOS))

    bucle = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        bucle.add_signal_handler(sig, _parar.set)

    intervalo_refresco = s.refresh_interval_s
    intervalo_sla = obtener_intervalo_sla_s()
    intervalos_override = {
        "refrescar_agregados": intervalo_refresco,
        "evaluar_sla": intervalo_sla,
    }
    tareas = [
        asyncio.create_task(_bucle(n, c, intervalos_override.get(n, i)))
        for n, (c, i) in _TRABAJOS.items()
    ]
    await _parar.wait()
    for t in tareas:
        t.cancel()
    await asyncio.gather(*tareas, return_exceptions=True)
    await cerrar()
    log.info("admin.workers.apagado")


if __name__ == "__main__":
    asyncio.run(main())
