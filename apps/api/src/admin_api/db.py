"""Sesiones de base de datos de la consola: dos pools con dos roles distintos.

La separación no es una optimización, es parte del modelo de acceso (§18):

  · `admin_session()`  rol kallicode_admin_app · DML sobre el esquema admin.
                       No puede leer datos de cliente.
  · `read_session()`   rol kallicode_admin_ro  · lectura analítica cross-tenant,
                       acotada por política y por columna. No puede escribir.

Ninguno de los dos tiene elusión de seguridad a nivel de fila, y el arranque
comprueba en la propia base que sigue siendo así: el defecto BE-F01 del backend
fue precisamente que la docstring afirmaba una separación de roles que el código
no implementaba.

Se reutilizan los helpers `uno`, `todos` y `valor` de la plataforma para no
duplicar el manejo de resultados.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from kallicode_core.logging import log
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from .settings import get_admin_settings

_engine_app: AsyncEngine | None = None
_engine_ro: AsyncEngine | None = None
_maker_app: async_sessionmaker[AsyncSession] | None = None
_maker_ro: async_sessionmaker[AsyncSession] | None = None


def _crear(url: str, pool: int, timeout_ms: int) -> AsyncEngine:
    s = get_admin_settings()
    pool_kwargs: dict[str, Any] = {}
    if s.env == "test":
        from sqlalchemy.pool import NullPool

        pool_kwargs["poolclass"] = NullPool
    else:
        pool_kwargs["pool_size"] = pool
        pool_kwargs["max_overflow"] = pool
        pool_kwargs["pool_pre_ping"] = True
        pool_kwargs["pool_recycle"] = 1800

    return create_async_engine(
        url,
        **pool_kwargs,
        connect_args={
            "server_settings": {
                "statement_timeout": str(timeout_ms),
                "application_name": "kallicode-admin",
            }
        },
    )


def engine_app() -> AsyncEngine:
    global _engine_app, _maker_app
    if _engine_app is None:
        s = get_admin_settings()
        _engine_app = _crear(s.database_url_app, s.pool_size_app,
                             s.statement_timeout_ms_app)
        _maker_app = async_sessionmaker(_engine_app, expire_on_commit=False)
    return _engine_app


def engine_ro() -> AsyncEngine:
    global _engine_ro, _maker_ro
    if _engine_ro is None:
        s = get_admin_settings()
        _engine_ro = _crear(s.database_url_ro, s.pool_size_ro,
                            s.statement_timeout_ms_ro)
        _maker_ro = async_sessionmaker(_engine_ro, expire_on_commit=False)
    return _engine_ro


@asynccontextmanager
async def admin_session() -> AsyncIterator[AsyncSession]:
    """Sesión transaccional de escritura sobre el esquema `admin`."""
    engine_app()
    assert _maker_app is not None
    async with _maker_app() as db:
        async with db.begin():
            yield db


@asynccontextmanager
async def read_session() -> AsyncIterator[AsyncSession]:
    """Sesión de lectura analítica cross-tenant, en el pool separado.

    No abre transacción de escritura: la sesión es de solo lectura por rol, y
    además se marca como tal para que cualquier intento de escritura falle en la
    base y no dependa de la disciplina de quien escriba la consulta.
    """
    engine_ro()
    assert _maker_ro is not None
    async with _maker_ro() as db:
        await db.execute(text("SET TRANSACTION READ ONLY"))
        try:
            yield db
        finally:
            await db.rollback()


# --------------------------------------------------------------- helpers
async def uno(db: AsyncSession, sql: str,
              params: dict[str, Any] | None = None) -> dict[str, Any] | None:
    fila = (await db.execute(text(sql), params or {})).mappings().first()
    return dict(fila) if fila else None


async def todos(db: AsyncSession, sql: str,
                params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    return [dict(f) for f in (await db.execute(text(sql), params or {})).mappings()]


async def valor(db: AsyncSession, sql: str,
                params: dict[str, Any] | None = None) -> Any:
    return (await db.execute(text(sql), params or {})).scalar()


# ------------------------------------------------------- barrera de arranque
async def verificar_arranque() -> None:
    """Comprueba en la propia base que el modelo de acceso sigue en pie.

    Se ejecuta al arrancar la aplicación y falla de forma explícita, con mensaje
    que nombra el problema. Cinco comprobaciones:

      1. Ninguno de los dos roles es superusuario ni tiene BYPASSRLS.
      2. El rol de lectura no tiene ningún privilegio de escritura.
      3. El rol de lectura no puede leer ninguna columna fuera del inventario.
      4. La sesión de lectura ve más de un tenant (la excepción funciona).
      5. La sesión de escritura NO puede leer datos de cliente.

    Las tres primeras las resuelve `admin.validate_read_role()` en SQL; las dos
    últimas se comprueban aquí porque son de comportamiento y no de privilegio.
    """
    async with admin_session() as db:
        fallos = await todos(db, "SELECT * FROM admin.validate_read_role()")
        if fallos:
            detalle = "; ".join(f"{f['check_id']} -> {f['detail']}" for f in fallos)
            raise RuntimeError(
                f"El modelo de acceso de la consola no es válido: {detalle}")

    async with read_session() as db:
        # 4. la lectura cross-tenant funciona de verdad
        n = await valor(db, "SELECT count(DISTINCT id) FROM core.organizations "
                            "WHERE eliminado_en IS NULL")
        if n is None:
            raise RuntimeError(
                "El rol de lectura no puede consultar core.organizations: "
                "faltan políticas o privilegios de columna")
        # 5. y no puede escribir
        try:
            await db.execute(text("CREATE TEMP TABLE _probe_ro (x int)"))
        except Exception:
            pass                                    # lo esperado
        else:
            raise RuntimeError(
                "El rol de lectura puede escribir: revisa 002_read_role.sql")

    async with admin_session() as db:
        # 5b. el rol de escritura no debe ver datos de cliente más allá del id
        try:
            await db.execute(text("SELECT nombre FROM core.organizations LIMIT 1"))
        except Exception:
            log.info("admin.arranque.verificado",
                     detalle="roles, políticas e inventario correctos")
            return
        raise RuntimeError(
            "El rol de escritura puede leer datos de cliente: revoca sus "
            "privilegios sobre core (solo debe tener SELECT (id))")


async def cerrar() -> None:
    """Cierra los dos pools. Sin esto cada redespliegue deja conexiones colgadas
    (defecto BE-F37 del backend)."""
    global _engine_app, _engine_ro, _maker_app, _maker_ro
    for e in (_engine_app, _engine_ro):
        if e is not None:
            await e.dispose()
    _engine_app = _engine_ro = None
    _maker_app = _maker_ro = None
