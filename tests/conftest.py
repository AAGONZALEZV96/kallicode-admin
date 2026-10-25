"""Fixtures de la suite de la consola de administración.

La suite tiene dos niveles y se distinguen con marcas, porque su coste es muy
distinto:

  · **unitarias** — enmascarado, paginación, validación de motivos, jerarquía de
    alcances. No tocan base de datos y corren en milisegundos.
  · **integración** (`@pytest.mark.integracion`) — levantan un PostgreSQL 16 con
    pgvector real, aplican el esquema de la plataforma y las cuatro migraciones de
    la consola, y crean los tres roles. Es la única forma de probar lo que
    importa: que el rol de lectura no puede leer más de lo autorizado y que la
    cadena de auditoría detecta una supresión.

Nunca se usa SQLite ni un doble de base de datos. La lección de la auditoría de la
plataforma es precisamente esa: los cinco defectos más graves del programa
—aislamiento inoperante, fuga en el kanban, cadena que no verifica— son todos
defectos que solo una suite de integración con RLS real detecta.
"""

from __future__ import annotations

import os
import subprocess
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio

RAIZ = Path(__file__).resolve().parents[1]
# El esquema de la plataforma vive en el repositorio del backend; la suite lo
# aplica en orden antes de las migraciones de la consola.
BACKEND_DB = RAIZ.parent / "kallicode-backend" / "db"
ADMIN_DB = RAIZ / "db"

TENANT_A = "org_acme"
TENANT_B = "org_globex"

ROLES = ("staff_soporte", "staff_operaciones", "staff_negocio", "staff_admin")


def pytest_configure(config: Any) -> None:
    config.addinivalue_line(
        "markers", "integracion: exige un PostgreSQL real; se omite si no está disponible."
    )


# ============================================================ base de datos
@pytest.fixture(scope="session")
def dsn() -> Iterator[str]:
    """DSN de un PostgreSQL 16 con pgvector, por contenedor o por variable.

    Si `KC_ADMIN_TEST_DSN` está definida se usa esa base —útil en local para no
    levantar un contenedor en cada ejecución—; si no, se arranca uno con
    testcontainers. Sin ninguna de las dos, las pruebas de integración se omiten.
    """
    externo = os.getenv("KC_ADMIN_TEST_DSN")
    if externo:
        yield externo
        return
    try:
        from testcontainers.postgres import PostgresContainer
    except ImportError:  # pragma: no cover
        pytest.skip("testcontainers no instalado y KC_ADMIN_TEST_DSN sin definir")
    with PostgresContainer("pgvector/pgvector:pg16", driver=None) as pg:
        yield pg.get_connection_url().replace("postgresql://", "postgresql://")


def _psql(dsn_url: str, sql: str) -> None:
    """Ejecuta SQL con psql. Falla la prueba si el script no aplica limpio."""
    r = subprocess.run(
        ["psql", dsn_url, "-v", "ON_ERROR_STOP=1", "-q", "-c", sql],
        capture_output=True,
        text=True,
    )
    if r.returncode != 0:
        pytest.fail(f"psql falló: {r.stderr[:2000]}")


def _psql_file(dsn_url: str, ruta: Path) -> None:
    r = subprocess.run(
        [
            "psql",
            dsn_url,
            "-v",
            "ON_ERROR_STOP=1",
            "-v",
            "pw_app=test",
            "-v",
            "pw_worker=test",
            "-v",
            "pw_admin=test",
            "-q",
            "-f",
            str(ruta),
        ],
        capture_output=True,
        text=True,
    )
    if r.returncode != 0:
        pytest.fail(f"psql falló aplicando {ruta.name}: {r.stderr[-2000:]}")


@pytest.fixture(scope="session")
def esquema(dsn: str) -> str:
    """Aplica el esquema de la plataforma, las migraciones de la consola y los roles.

    El orden no es negociable: primero core, luego los roles y las políticas, y
    solo después los agregados, que dependen del inventario de acceso.
    """
    if not BACKEND_DB.is_dir():
        pytest.skip(f"no se encuentra el esquema de la plataforma en {BACKEND_DB}")

    _psql(
        dsn,
        """
        DROP SCHEMA IF EXISTS admin, core, vec, audit CASCADE;
        CREATE EXTENSION IF NOT EXISTS vector;
        CREATE EXTENSION IF NOT EXISTS pg_trgm;
    """,
    )
    # Contraseñas de prueba de los roles: las crea el propio script y aquí solo se
    # fijan para poder conectarse con cada uno.
    for f in sorted(BACKEND_DB.glob("0[0-5]_*.sql")):
        _psql_file(dsn, f)
    for f in sorted(ADMIN_DB.glob("00*.sql")):
        _psql_file(dsn, f)
    _psql(
        dsn,
        """
        ALTER ROLE kallicode_admin_app WITH PASSWORD 'test';
        ALTER ROLE kallicode_admin_ro  WITH PASSWORD 'test';
        ALTER ROLE kallicode_app       WITH PASSWORD 'test';
        INSERT INTO admin.staff (id, email, full_name, role, status,
                                 password_hash, totp_secret, totp_enrolled_at)
        VALUES ('st_prueba', 'st_prueba@kallicode.com', 'Empleado Prueba',
                'staff_admin', 'active', 'hash', 'totp', now())
        ON CONFLICT (id) DO NOTHING;
    """,
    )
    return dsn


def _dsn_como(dsn_url: str, usuario: str) -> str:
    """Reescribe el DSN para conectarse con otro rol, en modo asyncpg."""
    resto = dsn_url.split("@", 1)[-1]
    return f"postgresql+asyncpg://{usuario}:test@{resto}"


@pytest.fixture(scope="session")
def entorno(esquema: str) -> Iterator[None]:
    """Configura las variables de entorno de la aplicación para la sesión."""
    previo = dict(os.environ)
    redis_test = (
        os.getenv("KC_ADMIN_REDIS_URL")
        or os.getenv("KC_REDIS_URL")
        or "redis://localhost:6380/1"
    )
    os.environ.update(
        {
            "KC_ADMIN_ENV": "test",
            "KC_ADMIN_ALLOWED_HOSTS": "localhost,127.0.0.1,admin.test,testserver",
            "KC_ADMIN_DATABASE_URL_APP": _dsn_como(esquema, "kallicode_admin_app"),
            "KC_ADMIN_DATABASE_URL_RO": _dsn_como(esquema, "kallicode_admin_ro"),
            "KC_ADMIN_STAFF_EMAIL_DOMAINS": "kallicode.com",
            "KC_ADMIN_REDIS_URL": redis_test,
            "KC_REDIS_URL": redis_test,
            "KC_ENV": "test",
            "KC_DATABASE_URL": _dsn_como(esquema, "kallicode_app"),
            "KC_DATABASE_URL_ADMIN": _dsn_como(esquema, "kallicode_admin"),
        }
    )
    # La caché de configuración se limpia para que tome el entorno de prueba.
    from admin_api.settings import get_admin_settings

    get_admin_settings.cache_clear()
    yield
    os.environ.clear()
    os.environ.update(previo)
    get_admin_settings.cache_clear()


@pytest_asyncio.fixture
async def db(entorno: None) -> AsyncIterator[Any]:
    """Sesión de escritura sobre el esquema admin, con rollback al terminar."""
    from admin_api.db import admin_session

    async with admin_session() as sesion:
        yield sesion
        await sesion.rollback()


@pytest_asyncio.fixture
async def db_ro(entorno: None) -> AsyncIterator[Any]:
    """Sesión con el rol de solo lectura, tal como la usa el pool analítico."""
    from admin_api.db import read_session

    async with read_session() as sesion:
        yield sesion


# ============================================================ datos de prueba
@pytest_asyncio.fixture
async def dos_clientes(db: Any) -> list[str]:
    """Dos organizaciones con plan y consumo, para probar la no-fuga entre ellas."""
    from sqlalchemy import text

    for tid, nombre in (
        (TENANT_A, "Acme Logística S.L."),
        (TENANT_B, "Globex Industrial S.A."),
    ):
        await db.execute(
            text("""
            INSERT INTO core.organizations (id, nombre, idioma, timezone,
                                            despliegue, fabrica_activa)
            VALUES (:i, :n, 'es', 'Europe/Madrid', 'cloud', true)
            ON CONFLICT (id) DO NOTHING
        """),
            {"i": tid, "n": nombre},
        )
        await db.execute(
            text("""
            INSERT INTO core.subscriptions (id, tenant_id, plan_codigo, estado,
                                            inicia_el, renueva_el)
            VALUES (:s, :i, 'growth', 'activa', current_date - 90,
                    current_date + 30)
            ON CONFLICT DO NOTHING
        """),
            {"s": f"sub_{tid}", "i": tid},
        )
    return [TENANT_A, TENANT_B]


@pytest_asyncio.fixture
async def staff_factory(db: Any):
    """Crea empleados activos de cualquier rol, con segundo factor ya inscrito."""
    from admin_api.db import admin_session
    from admin_api.security import hashear_password, nuevo_secreto_totp
    from kallicode_core.ids import nuevo
    from sqlalchemy import text

    creados: list[str] = []

    async def _crear(rol: str = "staff_admin", estado: str = "active") -> dict[str, Any]:
        sid = nuevo("st")
        email = f"{sid.lower()}@kallicode.com"
        secreto = nuevo_secreto_totp()
        await db.execute(
            text("""
            INSERT INTO admin.staff (id, email, full_name, role, status,
                                     password_hash, totp_secret,
                                     totp_enrolled_at)
            VALUES (:i, :e, :n, :r, :s, :p, :t,
                    CASE WHEN :s = 'active' THEN now() END)
        """),
            {
                "i": sid,
                "e": email,
                "n": f"Empleado {rol}",
                "r": rol,
                "s": estado,
                "p": hashear_password("Prueba-Segura-2026"),
                "t": secreto,
            },
        )
        await db.commit()
        creados.append(sid)
        return {
            "id": sid,
            "email": email,
            "rol": rol,
            "secreto": secreto,
            "password": "Prueba-Segura-2026",
        }

    return _crear


# ============================================================ cliente HTTP
@pytest_asyncio.fixture
async def app(entorno: None) -> Any:
    """La aplicación, sin ejecutar el ciclo de vida (que exige toda la infra)."""
    from admin_api.main import app as aplicacion

    return aplicacion


@pytest_asyncio.fixture
async def cliente(app: Any) -> AsyncIterator[Any]:
    """Cliente HTTP contra la aplicación en memoria."""
    import httpx

    transporte = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transporte, base_url="http://admin.test") as c:
        yield c


@pytest.fixture
def como(app: Any):
    """Sustituye la identidad del empleado por una fija, para probar autorización.

    Devuelve una función que recibe el rol y, opcionalmente, las concesiones
    vigentes, y deja la dependencia sobrescrita durante la prueba. Es la fixture
    que hace posible recorrer la matriz de permisos completa sin ejecutar ocho
    endpoints de login por combinación.
    """
    from admin_api.deps import Staff, staff_actual

    def _como(
        rol: str, grants: dict[str, list[str]] | None = None, staff_id: str = "st_prueba"
    ) -> Staff:
        st = Staff(
            id=staff_id,
            role=rol,
            full_name=f"Empleado {rol}",
            email=f"{rol}@kallicode.com",
            mfa_at=datetime.now(UTC) - timedelta(minutes=1),
            jti="jti_prueba",
            ip="10.0.0.7",
            user_agent="pytest",
            request_id="tr_prueba",
            grants=dict(grants or {}),
            grant_detalle={
                t: (f"gr_{t}", a[-1], "motivo de prueba con caso SUP-1")
                for t, a in (grants or {}).items()
                if a
            },
        )

        async def _override() -> Staff:
            return st

        app.dependency_overrides[staff_actual] = _override
        return st

    yield _como
    app.dependency_overrides.clear()


@pytest.fixture
def sin_limite(app: Any) -> Iterator[None]:
    """Desactiva RL-4 y el límite de refresco en vivo.

    Las pruebas de autorización hacen más de 300 peticiones por minuto por diseño;
    el límite se prueba aparte y no debe contaminar el resto de la matriz.
    """
    from admin_api.deps import limite_rl4, limite_vivo, staff_actual

    async def _passthrough() -> Any:
        # Delega en la identidad sobrescrita por la fixture `como`.
        return await app.dependency_overrides[staff_actual]()

    app.dependency_overrides[limite_rl4] = _passthrough
    app.dependency_overrides[limite_vivo] = _passthrough
    yield
    app.dependency_overrides.pop(limite_rl4, None)
    app.dependency_overrides.pop(limite_vivo, None)
