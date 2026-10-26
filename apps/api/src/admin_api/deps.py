"""Dependencias de FastAPI: identidad del personal, roles, concesiones y RL-4.

Cuatro decisiones de diseño que corrigen defectos encontrados en el backend:

  · El rol y el estado del empleado se resuelven **en base de datos** en cada
    petición, no se leen del token. El defecto BE-F11 fue que desactivar a un
    usuario o cambiarle el rol no invalidaba su token de acceso, que seguía
    siendo válido treinta minutos con el rol antiguo.
  · El identificador del token (`jti`) se consulta contra una lista de
    denegación en Redis, de modo que el cierre de sesión y la desactivación
    surtan efecto de inmediato. En el backend el claim se emitía y no se usaba.
  · Las concesiones vigentes se cargan una sola vez por petición y se pasan a la
    capa de enmascarado. Sin concesión no hay dato identificable, y eso no
    depende de que el router se acuerde de comprobarlo.
  · El límite RL-4 es propio de esta superficie y distingue los endpoints de
    refresco en vivo, que se consultan de forma continuada durante una guardia.
"""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

import redis.asyncio as aioredis
from fastapi import Depends, Request
from kallicode_core.config import get_settings
from kallicode_core.errors import AppError, no_autenticado, rate_limit
from kallicode_core.logging import bind_contexto
from sqlalchemy.ext.asyncio import AsyncSession

from .db import admin_session, read_session, todos, uno
from .errors import (
    acceso_no_justificado,
    concesion_caducada,
    rol_staff_insuficiente,
    staff_desactivado,
)
from .masking import alcance_suficiente
from .security import (
    PERMISOS_ROL,
    exigir_mfa_vigente,
    exigir_rol_staff,
    verificar_token_staff,
)
from .settings import get_admin_settings

_redis: aioredis.Redis | None = None


def redis() -> aioredis.Redis:
    global _redis
    import asyncio

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if _redis is None or (
        loop is not None
        and getattr(_redis, "_custom_loop", None) is not None
        and getattr(_redis, "_custom_loop", None) != loop
    ):
        _redis = aioredis.from_url(  # type: ignore[no-untyped-call]
            get_settings().redis_url,
            decode_responses=True,
        )
        _redis._custom_loop = loop  # type: ignore[union-attr]
    return _redis


def clave_denylist(jti: str) -> str:
    return f"admin:denylist:{jti}"


# --------------------------------------------------------------- contexto
@dataclass(slots=True)
class Staff:
    """Identidad efectiva del empleado en esta petición."""

    id: str
    role: str
    full_name: str
    email: str
    mfa_at: datetime
    jti: str
    ip: str | None = None
    user_agent: str | None = None
    request_id: str | None = None
    # tenant_id -> alcances vigentes; se carga una vez por petición
    grants: dict[str, list[str]] = field(default_factory=dict)
    # tenant_id -> (grant_id, scope, reason) del alcance mayor vigente
    grant_detalle: dict[str, tuple[str, str, str]] = field(default_factory=dict)

    def concedidos(self, tenant_id: str) -> list[str]:
        return self.grants.get(tenant_id, [])

    def puede(self, tenant_id: str, alcance: str) -> bool:
        return alcance_suficiente(self.concedidos(tenant_id), alcance)


def _ip_cliente(request: Request) -> str | None:
    """Dirección real del cliente tras el proxy.

    El defecto BE-F13 del backend fue usar la dirección de la conexión, que tras
    el ingress es siempre la misma: el límite pasaba a ser global y bastaba un
    atacante para bloquear el acceso de todos.
    """
    reenviada = request.headers.get("x-forwarded-for")
    if reenviada:
        return reenviada.split(",")[0].strip()
    return request.client.host if request.client else None


# ------------------------------------------------------- identidad del personal
def validar_token_staff(request: Request) -> dict[str, Any]:
    """Extrae y valida el JWT de la cabecera Authorization (Bearer).

    Comprueba firma, emisor ('kallicode-admin'), audiencia ('admin-v1'),
    tipo ('staff') y claims obligatorios sin consultar base de datos.
    """
    cabecera = request.headers.get("authorization", "")
    if not cabecera.lower().startswith("bearer "):
        raise no_autenticado()
    return verificar_token_staff(cabecera[7:].strip())


async def staff_actual(request: Request) -> Staff:
    """Resuelve el empleado autenticado. Es la dependencia base del capítulo 18."""
    claims = validar_token_staff(request)

    jti = str(claims["jti"])
    if await redis().exists(clave_denylist(jti)):
        raise no_autenticado("La sesión ha sido cerrada.")

    sub = str(claims["sub"])
    revocado_en = await redis().get(f"admin:staff:{sub}:revoked_at")
    if revocado_en is not None and int(str(claims.get("iat", 0))) <= int(revocado_en):
        raise no_autenticado("La sesión ha sido cerrada.")

    mfa_at = exigir_mfa_vigente(claims)

    # El estado y el rol se resuelven en base de datos, nunca desde el token.
    async with admin_session() as db:
        fila = await uno(
            db,
            """
            SELECT id, email, full_name, role, status
            FROM admin.staff WHERE id = :id
        """,
            {"id": str(claims["sub"])},
        )
    if fila is None:
        raise no_autenticado()
    if fila["status"] != "active":
        raise staff_desactivado()

    st = Staff(
        id=fila["id"],
        role=fila["role"],
        full_name=fila["full_name"],
        email=fila["email"],
        mfa_at=mfa_at,
        jti=jti,
        ip=_ip_cliente(request),
        user_agent=request.headers.get("user-agent"),
        request_id=request.headers.get("x-trace-id")
        or getattr(request.state, "trace_id", None),
    )
    await _cargar_concesiones(st)
    bind_contexto(staff_id=st.id, rol=st.role, request_id=st.request_id)
    return st


async def _cargar_concesiones(st: Staff) -> None:
    """Carga las concesiones vigentes del empleado, una vez por petición."""
    async with admin_session() as db:
        filas = await todos(
            db,
            """
            SELECT id, tenant_id, scope, reason
            FROM admin.access_grants
            WHERE staff_id = :s AND revoked_at IS NULL AND expires_at > now()
            ORDER BY tenant_id, granted_at
        """,
            {"s": st.id},
        )
    for f in filas:
        st.grants.setdefault(f["tenant_id"], []).append(f["scope"])
        st.grant_detalle[f["tenant_id"]] = (f["id"], f["scope"], f["reason"])


StaffDep = Annotated[Staff, Depends(staff_actual)]
obtener_staff_actual = staff_actual


# ------------------------------------------------------------------ roles
def exigir(*roles: str) -> Callable[[Staff], Coroutine[Any, Any, Staff]]:
    """Fábrica de dependencia que restringe el endpoint a ciertos roles.

    Se usa como `Depends(exigir("staff_admin"))`, y la matriz de permisos del
    capítulo 18 se lee directamente de las firmas de los routers.
    """

    async def _guard(st: StaffDep) -> Staff:
        exigir_rol_staff(st.role, roles)
        s = get_admin_settings()
        if datetime.now(UTC) - st.mfa_at > timedelta(minutes=s.staff_idle_timeout_min):
            from .errors import mfa_requerido

            raise mfa_requerido("Verificación de segundo factor requerida.")
        return st

    return _guard


exigir_rol = exigir


def exigir_permiso(*permisos: str) -> Callable[[Staff], Coroutine[Any, Any, Staff]]:
    """Fábrica de dependencia que restringe el endpoint a empleados cuyo rol
    posee todos los permisos canónicos especificados.
    """

    async def _guard(st: StaffDep) -> Staff:
        rol_perms = set(PERMISOS_ROL.get(st.role, ()))
        if not set(permisos).issubset(rol_perms):
            raise rol_staff_insuficiente()
        s = get_admin_settings()
        if datetime.now(UTC) - st.mfa_at > timedelta(minutes=s.staff_idle_timeout_min):
            from .errors import mfa_requerido

            raise mfa_requerido("Verificación de segundo factor requerida.")
        return st

    return _guard


SOPORTE = ("staff_soporte", "staff_operaciones", "staff_negocio", "staff_admin")
NEGOCIO = ("staff_negocio", "staff_admin")
OPS = ("staff_operaciones", "staff_admin")
OPS_NEGOCIO = ("staff_operaciones", "staff_negocio", "staff_admin")
ADMIN = ("staff_admin",)


# ------------------------------------------------------------- concesiones
async def exigir_concesion(st: Staff, tenant_id: str, alcance: str) -> str:
    """Comprueba concesión vigente y devuelve su identificador.

    Lanza `ACCESO_NO_JUSTIFICADO` si no hay ninguna, y `CONCESION_CADUCADA` si
    hubo una pero ya venció. La distinción importa: el segundo caso le dice al
    empleado que vuelva a solicitarla con motivo nuevo, no que no tenía derecho.
    """
    if st.puede(tenant_id, alcance):
        return st.grant_detalle[tenant_id][0]

    async with admin_session() as db:
        vencida = await uno(
            db,
            """
            SELECT id FROM admin.access_grants
            WHERE staff_id = :s AND tenant_id = :t AND scope = :sc
              AND (revoked_at IS NOT NULL OR expires_at <= now())
            ORDER BY granted_at DESC LIMIT 1
        """,
            {"s": st.id, "t": tenant_id, "sc": alcance},
        )
    if vencida:
        raise concesion_caducada()
    raise acceso_no_justificado(tenant_id, alcance)


# ------------------------------------------------------------------ sesiones
async def db_admin() -> Any:
    """Sesión de escritura sobre el esquema admin."""
    async with admin_session() as db:
        yield db


async def db_lectura() -> Any:
    """Sesión de lectura analítica cross-tenant, en el pool separado."""
    async with read_session() as db:
        yield db


DbAdmin = Annotated[AsyncSession, Depends(db_admin)]
DbLectura = Annotated[AsyncSession, Depends(db_lectura)]


# ------------------------------------------------------------------- RL-4
async def _consumir(clave: str, limite: int, ventana_s: int = 60) -> None:
    r = redis()
    actual = await r.incr(clave)
    if actual == 1:
        await r.expire(clave, ventana_s)
    if actual > limite:
        ttl = await r.ttl(clave)
        raise rate_limit(max(ttl, 1))


async def limite_rl4(st: StaffDep) -> Staff:
    """Límite general de la API de administración: por empleado y global."""
    s = get_admin_settings()
    minuto = datetime.now(UTC).strftime("%Y%m%d%H%M")
    await _consumir(f"admin:rl4:{st.id}:{minuto}", s.rate_limit_staff)
    await _consumir(f"admin:rl4:global:{minuto}", s.rate_limit_global)
    return st


async def limite_vivo(st: StaffDep) -> Staff:
    """Límite de los endpoints de refresco en vivo de operaciones (§18.24-18.26)."""
    s = get_admin_settings()
    minuto = datetime.now(UTC).strftime("%Y%m%d%H%M")
    await _consumir(f"admin:rl4live:{st.id}:{minuto}", s.rate_limit_live)
    return st


async def limite_login(request: Request, email: str) -> None:
    """Contador de intentos de acceso por par de correo y dirección de origen.

    Por par y no por correo: bloquear por correo permitiría dejar fuera a
    cualquier empleado conocido durante la ventana de bloqueo (defecto BE-F13).
    """
    s = get_admin_settings()
    ip = _ip_cliente(request) or "sin-ip"
    clave = f"admin:login:{email.lower()}:{ip}"
    r = redis()
    intentos = int(await r.get(clave) or 0)
    if intentos >= s.login_max_attempts:
        raise rate_limit(s.login_lock_window_s)


async def registrar_fallo_login(request: Request, email: str) -> int:
    s = get_admin_settings()
    ip = _ip_cliente(request) or "sin-ip"
    clave = f"admin:login:{email.lower()}:{ip}"
    r = redis()
    n = await r.incr(clave)
    if n == 1:
        await r.expire(clave, s.login_lock_window_s)
    return int(n)


async def limpiar_fallos_login(request: Request, email: str) -> None:
    ip = _ip_cliente(request) or "sin-ip"
    await redis().delete(f"admin:login:{email.lower()}:{ip}")


async def revocar_jti(jti: str, ttl_s: int) -> None:
    """Añade el token de acceso a la lista de denegación hasta su expiración."""
    await redis().setex(clave_denylist(jti), max(ttl_s, 1), "1")


async def revocar_todas_sesiones_redis(staff_id: str) -> None:
    """Invalida inmediatamente en Redis todos los access tokens emitidos para el empleado."""
    s = get_admin_settings()
    ttl = s.staff_refresh_token_ttl_h * 3600
    ahora_ts = int(datetime.now(UTC).timestamp())
    await redis().set(f"admin:staff:{staff_id}:revoked_at", ahora_ts, ex=ttl)


async def cerrar_redis() -> None:
    global _redis
    if _redis is not None:
        await _redis.aclose()
        _redis = None


__all__ = [
    "ADMIN",
    "NEGOCIO",
    "OPS",
    "OPS_NEGOCIO",
    "SOPORTE",
    "AppError",
    "DbAdmin",
    "DbLectura",
    "Staff",
    "StaffDep",
    "cerrar_redis",
    "db_admin",
    "db_lectura",
    "exigir",
    "exigir_concesion",
    "exigir_permiso",
    "exigir_rol",
    "limite_login",
    "limite_rl4",
    "limite_vivo",
    "limpiar_fallos_login",
    "obtener_staff_actual",
    "redis",
    "registrar_fallo_login",
    "revocar_jti",
    "revocar_todas_sesiones_redis",
    "staff_actual",
    "validar_token_staff",
]
