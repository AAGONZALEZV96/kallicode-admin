"""Elección de líder mediante bloqueos de asesoramiento en transacción (Leader Election).

Garantiza que múltiples réplicas del worker no ejecuten tareas concurrentes pesadas
sobre PostgreSQL, utilizando pg_try_advisory_xact_lock con identificadores estables y dedicados.
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from typing import Any

from admin_api.db import admin_session, uno
from kallicode_core.logging import log
from sqlalchemy.ext.asyncio import AsyncSession

LOCK_ID_AGREGADOS: int = 918_401
LOCK_ID_INFORMES: int = 918_402
LOCK_ID_CONCESIONES: int = 918_403

LOCK_IDS: dict[str, int] = {
    "refrescar_agregados": LOCK_ID_AGREGADOS,
    "generar_informes": LOCK_ID_INFORMES,
    "caducar_concesiones": LOCK_ID_CONCESIONES,
}


async def intentar_liderazgo_xact(db: AsyncSession, lock_id: int) -> bool:
    """Intenta adquirir el bloqueo consultivo a nivel de transacción.

    Devuelve True si esta sesión es líder durante la transacción actual,
    o False si otra réplica ya mantiene el bloqueo.
    """
    fila = await uno(db, "SELECT pg_try_advisory_xact_lock(:k) AS ok", {"k": lock_id})
    return bool(fila and fila.get("ok"))


async def ejecutar_con_lider(
    nombre: str,
    cuerpo: Callable[[AsyncSession], Awaitable[Any]],
    lock_id: int | None = None,
) -> bool:
    """Ejecuta el trabajo únicamente si la réplica obtiene el liderazgo.

    Si otra réplica ya es líder, omite silenciosamente el ciclo registrando:
    INFO admin.worker.skipping_not_leader sin lanzar excepciones.
    """
    k = lock_id or LOCK_IDS.get(nombre)
    if k is None:
        raise ValueError(f"No existe LOCK_ID registrado para el trabajo '{nombre}'.")

    async with admin_session() as db:
        es_lider = await intentar_liderazgo_xact(db, k)
        if not es_lider:
            log.info("admin.worker.skipping_not_leader", trabajo=nombre, lock_id=k)
            return False

        t0 = time.perf_counter()
        try:
            await cuerpo(db)
            ms = int((time.perf_counter() - t0) * 1000)
            log.info("admin.worker.ok", trabajo=nombre, lock_id=k, ms=ms)
            return True
        except Exception as exc:
            ms = int((time.perf_counter() - t0) * 1000)
            log.error(
                "admin.worker.fallido",
                trabajo=nombre,
                lock_id=k,
                excepcion=type(exc).__name__,
                ms=ms,
            )
            raise


__all__ = [
    "LOCK_IDS",
    "LOCK_ID_AGREGADOS",
    "LOCK_ID_CONCESIONES",
    "LOCK_ID_INFORMES",
    "ejecutar_con_lider",
    "intentar_liderazgo_xact",
]
