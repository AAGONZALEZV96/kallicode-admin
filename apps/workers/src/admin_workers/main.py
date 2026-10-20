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
import csv
import io
import signal
from typing import Any

from admin_api.audit import registrar_accion
from admin_api.db import admin_session, cerrar, read_session, todos, uno
from admin_api.servicios.blob import ruta_informe, subir_informe
from admin_api.settings import get_admin_settings
from kallicode_core.logging import Cronometro, bind_contexto, configurar_logging, log
from sqlalchemy import text

_parar = asyncio.Event()

# Bloqueo de asesoramiento por trabajo: solo la réplica que lo obtiene ejecuta.
_LOCKS: dict[str, int] = {
    "refrescar_agregados": 918_401,
    "generar_informes": 918_402,
    "caducar_concesiones": 918_403,
}


async def _con_lider(nombre: str, cuerpo: Any) -> None:
    """Ejecuta el trabajo solo si esta réplica obtiene el bloqueo."""
    async with admin_session() as db:
        obtenido = await uno(
            db, "SELECT pg_try_advisory_xact_lock(:k) AS ok",
            {"k": _LOCKS[nombre]})
        if not obtenido or not obtenido["ok"]:
            log.debug("admin.worker.sin_liderazgo", trabajo=nombre)
            return
        cron = Cronometro()
        try:
            await cuerpo(db)
            log.info("admin.worker.ok", trabajo=nombre, ms=cron.ms())
        except Exception as exc:
            log.error("admin.worker.fallido", trabajo=nombre,
                      excepcion=type(exc).__name__, ms=cron.ms())
            raise


# ------------------------------------------------------------------ agregados
async def refrescar_agregados(db: Any) -> None:
    """Recalcula los agregados de negocio y los casos de nivel de servicio."""
    filas = await todos(db, "SELECT * FROM admin.refresh_all()")
    for f in filas:
        nivel = log.info if f["estado"] == "ok" else log.error
        nivel("admin.agregado.refrescado", agregado=f["agregado"],
              filas=f["filas"], ms=f["ms"], estado=f["estado"])
    fallidos = [f["agregado"] for f in filas if f["estado"] != "ok"]
    if fallidos:
        # No se lanza excepción: el resto de agregados sí se refrescó y la API ya
        # devuelve 503 para los que fallaron. Lanzar aquí solo perdería la traza.
        log.critical("admin.agregado.fallidos", agregados=fallidos)

    n = await uno(db, "SELECT admin.refresh_sla(95, false) AS n")
    log.info("admin.sla.recalculado", casos=int(n["n"]) if n else 0)


# ------------------------------------------------------------------- informes
_COLUMNAS: dict[str, tuple[str, str]] = {
    "consumo": ("tenant_id, ciclo, loc_consumidas, tokens_in, tokens_out, "
                "tokens_flash, tokens_pro, tokens_fable, coste",
                "admin.agg_usage_cycle"),
    "suscripciones": ("tenant_id, plan_codigo, suscripcion_estado, inicia_el, "
                      "renueva_el, finaliza_el, importe_mes, moneda",
                      "admin.agg_customer_state"),
    "clientes": ("tenant_id, plan_codigo, suscripcion_estado, alta_el, "
                 "lineas_contratadas, lineas_activas, usuarios_activos, "
                 "tickets_abiertos, ultima_actividad",
                 "admin.agg_customer_state"),
    "sla": ("tenant_id, ticket_numero, plan_codigo, objetivo_h, transcurrido_h, "
            "bruto_h, resultado, iniciado_en, terminado_en",
            "admin.sla_cases"),
    "staff_actions": ("occurred_at, staff_id, staff_role, action, tenant_id, "
                      "scope, reason, resource, endpoint, seal",
                      "admin.staff_actions"),
}

# Columnas identificables: solo se incluyen si el informe las autoriza.
_PII = {"razon_social", "ticket_numero", "reason", "comentario"}


async def generar_informes(db: Any) -> None:
    """Genera los informes en cola, los sube y solo entonces los marca listos."""
    pendientes = await todos(db, """
        UPDATE admin.reports SET status = 'generando'
        WHERE id IN (SELECT id FROM admin.reports
                      WHERE status = 'en_cola'
                      ORDER BY requested_at LIMIT 5 FOR UPDATE SKIP LOCKED)
        RETURNING id, kind, format, params, requested_by, includes_pii
    """)
    for r in pendientes:
        await _generar_uno(r)


async def _generar_uno(r: dict[str, Any]) -> None:
    s = get_admin_settings()
    bind_contexto(report_id=r["id"])
    try:
        cols, tabla = _COLUMNAS[r["kind"]]
        seleccion = [c.strip() for c in cols.split(",")]
        if not r["includes_pii"]:
            seleccion = [c for c in seleccion if c not in _PII]

        params = r["params"] or {}
        campo_fecha = {"consumo": "to_date(ciclo || '-01', 'YYYY-MM-DD')",
                       "sla": "iniciado_en",
                       "staff_actions": "occurred_at"}.get(r["kind"], "alta_el")
        filtro = f"WHERE {campo_fecha} >= CAST(:d AS date) " \
                 f"AND {campo_fecha} < CAST(:h AS date) + 1"
        if params.get("tenant_id"):
            filtro += " AND tenant_id = :t"

        async with read_session() as rdb:
            filas = await todos(rdb, f"""
                SELECT {', '.join(seleccion)} FROM {tabla} {filtro}
                ORDER BY 1 LIMIT :chunk
            """, {"d": params.get("desde"), "h": params.get("hasta"),
                  "t": params.get("tenant_id"), "chunk": s.export_chunk_events})

        buf = io.StringIO()
        w = csv.DictWriter(buf, fieldnames=seleccion, extrasaction="ignore")
        w.writeheader()
        for f in filas:
            w.writerow({k: f.get(k) for k in seleccion})
        datos = buf.getvalue().encode("utf-8")

        blob_ref = ruta_informe(r["id"], r["format"])
        # La subida va ANTES de marcar como listo: si falla, el informe queda
        # fallido y no se entrega una URL a un fichero inexistente.
        digest = await subir_informe(blob_ref, datos, "text/csv; charset=utf-8")

        async with admin_session() as db:
            await uno(db, """
                UPDATE admin.reports
                SET status = 'listo', blob_ref = :b, sha256 = :h,
                    rows_total = :n, completed_at = now(), error = NULL
                WHERE id = :i RETURNING id
            """, {"b": blob_ref, "h": digest, "n": len(filas), "i": r["id"]})
        log.info("admin.informe.generado", report_id=r["id"], filas=len(filas),
                 bytes=len(datos), identificables=r["includes_pii"])

    except Exception as exc:
        async with admin_session() as db:
            await db.execute(text("""
                UPDATE admin.reports
                SET status = 'fallido', blob_ref = NULL,
                    error = jsonb_build_object('tipo', :t, 'cuando', now()::text),
                    completed_at = now()
                WHERE id = :i
            """), {"t": type(exc).__name__, "i": r["id"]})
        log.error("admin.informe.fallido", report_id=r["id"],
                  excepcion=type(exc).__name__)


# --------------------------------------------------------------- concesiones
async def caducar_concesiones(db: Any) -> None:
    """Registra la caducidad de las concesiones vencidas.

    La concesión ya no es válida por su propio vencimiento —las consultas filtran
    por `expires_at > now()`—, pero el registro de auditoría debe reflejar también
    el fin del acceso: un registro que solo anota concesiones y nunca su cierre
    cuenta media historia.
    """
    vencidas = await todos(db, """
        SELECT g.id, g.staff_id, g.tenant_id, g.scope, g.reason, g.reads,
               s.role AS staff_role
        FROM admin.access_grants g
        JOIN admin.staff s ON s.id = g.staff_id
        WHERE g.revoked_at IS NULL AND g.expires_at <= now()
          AND NOT EXISTS (
              SELECT 1 FROM admin.staff_actions a
               WHERE a.grant_id = g.id AND a.action = 'grant_revoked')
    """)
    for g in vencidas:
        await registrar_accion(
            db, staff_id=g["staff_id"], staff_role=g["staff_role"],
            action="grant_revoked",
            endpoint="worker:caducar_concesiones",
            tenant_id=g["tenant_id"], grant_id=g["id"], scope=g["scope"],
            reason=g["reason"],
            payload={"causa": "vencimiento", "lecturas": g["reads"]})
    if vencidas:
        log.info("admin.grants.caducadas", n=len(vencidas))


# ------------------------------------------------------------------ runner
_TRABAJOS: dict[str, tuple[Any, int]] = {
    "refrescar_agregados": (refrescar_agregados, 900),
    "generar_informes": (generar_informes, 30),
    "caducar_concesiones": (caducar_concesiones, 300),
}


async def _bucle(nombre: str, cuerpo: Any, intervalo: int) -> None:
    while not _parar.is_set():
        try:
            await _con_lider(nombre, cuerpo)
        except Exception:
            pass                     # ya registrado; el bucle no muere por un fallo
        try:
            await asyncio.wait_for(_parar.wait(), timeout=intervalo)
        except TimeoutError:
            continue


async def main() -> None:
    configurar_logging()
    s = get_admin_settings()
    log.info("admin.workers.arrancando", env=s.env,
             trabajos=sorted(_TRABAJOS))

    bucle = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        bucle.add_signal_handler(sig, _parar.set)

    intervalo_refresco = s.refresh_interval_s
    tareas = [
        asyncio.create_task(_bucle(
            n, c, intervalo_refresco if n == "refrescar_agregados" else i))
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
