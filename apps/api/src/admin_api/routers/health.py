"""§18.31 · Salud del servicio de administración.

Devuelve 503 cuando una dependencia crítica no responde, para que el orquestador
de contenedores no envíe tráfico a una réplica que no puede servir. El defecto
BE-F29 del backend fue lo contrario: la sonda devolvía 200 informando de que
PostgreSQL no respondía, así que la réplica se marcaba como lista con la base
caída.

Distingue tres estados y no dos, porque no todas las degradaciones son iguales:

  · `no_disponible` (503) · base de datos o almacenamiento inaccesibles.
  · `degradado` (200) · solo falla la telemetría del pipeline: las cuatro
    pantallas de negocio siguen siendo útiles y cortar el tráfico sería peor.
  · `ok` (200) · todo responde y los agregados están dentro de su frescura.

No expone detalles de infraestructura más allá del estado booleano de cada
dependencia, y no genera log de acceso para no inundar: solo registra el cambio
de estado.
"""

from __future__ import annotations

from typing import Any

import httpx
from fastapi import APIRouter, Response, status
from kallicode_core.logging import log
from sqlalchemy import text

from ..db import admin_session, read_session, uno
from ..deps import redis
from ..settings import get_admin_settings

router = APIRouter(prefix="/admin/v1", tags=["Salud"])

# Último estado servido, para registrar solo las transiciones.
_ultimo_estado: str | None = None


async def _postgres() -> bool:
    try:
        async with admin_session() as db:
            await db.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


async def _lectura() -> bool:
    """El pool analítico se comprueba por separado: usa otro rol y otro pool."""
    try:
        async with read_session() as db:
            await db.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


async def _redis() -> bool:
    try:
        return bool(await redis().ping())
    except Exception:
        return False


async def _telemetria() -> bool:
    s = get_admin_settings()
    try:
        async with httpx.AsyncClient(timeout=s.telemetry_timeout_s) as c:
            r = await c.get(
                f"{s.telemetry_base_url}/telemetry/agents", params={"ventana": "5m"}
            )
        return r.status_code < 500
    except Exception:
        return False


async def _frescura_agregados() -> int | None:
    """Antigüedad en segundos del refresco más viejo entre las vistas."""
    try:
        async with admin_session() as db:
            fila = await uno(
                db,
                """
                SELECT coalesce(max(extract(epoch FROM now() - refreshed_at)), 0)
                       AS edad
                FROM admin.aggregate_state
            """,
            )
        return int(fila["edad"]) if fila else None
    except Exception:
        # La tabla de estado de agregados llega con las vistas materializadas.
        return None


@router.get("/health", summary="Salud del servicio de administración")
async def health(response: Response) -> dict[str, Any]:
    """Sonda de disponibilidad. 503 si una dependencia crítica no responde."""
    global _ultimo_estado
    s = get_admin_settings()

    postgres = await _postgres()
    lectura = await _lectura()
    cache = await _redis()
    telemetria = await _telemetria()
    edad = await _frescura_agregados()

    criticas_ok = postgres and lectura and cache
    agregados_ok = edad is None or edad <= s.aggregate_stale_s

    if not criticas_ok:
        estado = "no_disponible"
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    elif not telemetria or not agregados_ok:
        estado = "degradado"
    else:
        estado = "ok"

    if estado != _ultimo_estado:
        nivel = log.warning if estado != "ok" else log.info
        nivel(
            "admin.health.cambio_de_estado",
            desde=_ultimo_estado,
            hacia=estado,
            postgres=postgres,
            lectura=lectura,
            cache=cache,
            telemetria=telemetria,
        )
        _ultimo_estado = estado

    return {
        "estado": estado,
        "dependencias": {
            "postgres": postgres,
            "lectura_analitica": lectura,
            "cache": cache,
            "telemetria": telemetria,
            "agregados": agregados_ok,
        },
        "agregados_frescura_s": edad,
        "version": s.app_version,
    }


__all__ = ["router"]
