"""§18.9 – §18.12 · Gestión del personal de KalliCode.

El alta es siempre por invitación: no existe registro ni autoservicio. El riesgo
real de este bloque no es el habitual —que alguien no pueda entrar— sino el
contrario: que todo el personal acabe con rol de administración porque nadie
definió los grados y nadie revisa las cuentas dormidas. De ahí que §18.10
devuelva el último acceso y el número de concesiones vigentes: es la vista desde
la que se detecta lo que importa.

La operación crítica del bloque es la desactivación (§18.12). Revoca sesiones,
invalida los tokens de acceso por la lista de denegación y **revoca de inmediato
todas las concesiones de acceso vigentes**, de modo que el empleado deje de poder
leer datos de cliente en el mismo momento y no al caducar la concesión.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Path, Query
from kallicode_core.errors import conflicto, no_encontrado, validacion
from kallicode_core.ids import nuevo
from kallicode_core.logging import hash_email, log
from pydantic import BaseModel, ConfigDict, EmailStr, Field

from ..audit import registrar_accion
from ..db import admin_session, todos, uno
from ..deps import ADMIN, Staff, exigir, limite_rl4
from ..pagination import Pagina, paginacion, sobre
from ..security import STAFF_ROLES, generar_token_opaco
from ..settings import get_admin_settings

router = APIRouter(prefix="/admin/v1/staff", tags=["Gestión del personal"])


class _Base(BaseModel):
    model_config = ConfigDict(extra="forbid")


class InvitarIn(_Base):
    email: EmailStr
    rol: str
    nota: str | None = Field(default=None, max_length=280)


class InvitarOut(_Base):
    invitacion_id: str
    email: str
    rol: str
    caduca_el: Any


class ActualizarIn(_Base):
    rol: str | None = None
    estado: str | None = None
    motivo: str | None = Field(default=None, min_length=10, max_length=280)


class ActualizarOut(_Base):
    id: str
    rol: str
    estado: str
    sesiones_revocadas: int
    concesiones_revocadas: int


# ------------------------------------------------------------------- §18.9
@router.get("/me", summary="Perfil del empleado autenticado")
async def perfil(st: Annotated[Staff, Depends(limite_rl4)]) -> dict[str, Any]:
    """Devuelve rol, permisos efectivos y concesiones vigentes.

    La consola lo consulta al arrancar para decidir qué pantallas muestra y qué
    datos puede pedir sin solicitar una concesión nueva. Los permisos se derivan
    del rol y no se almacenan, para que no puedan divergir de la matriz.
    """
    async with admin_session() as db:
        concesiones = await todos(db, """
            SELECT id AS grant_id, tenant_id, scope AS alcance,
                   expires_at AS caduca_en, reads AS lecturas
            FROM admin.access_grants
            WHERE staff_id = :s AND revoked_at IS NULL AND expires_at > now()
            ORDER BY expires_at
        """, {"s": st.id})
    return {
        "id": st.id, "nombre": st.full_name, "email": st.email, "rol": st.role,
        "mfa_verificado_en": st.mfa_at,
        "permisos": sorted(_PERMISOS.get(st.role, ())),
        "concesiones_vigentes": concesiones,
    }


# Matriz de permisos efectivos por rol. Es la traducción de la tabla de roles del
# capítulo 18 y la única fuente: los routers declaran roles, no permisos.
_PERMISOS: dict[str, tuple[str, ...]] = {
    "staff_soporte": ("negocio.clientes.leer", "expediente.leer",
                      "concesiones.propias"),
    "staff_operaciones": ("operaciones.leer", "sla.leer", "concesiones.propias"),
    "staff_negocio": ("negocio.leer", "negocio.clientes.leer", "informes.crear",
                      "sla.leer", "concesiones.propias"),
    "staff_admin": ("negocio.leer", "negocio.clientes.leer", "operaciones.leer",
                    "sla.leer", "informes.crear", "personal.gestionar",
                    "concesiones.todas", "auditoria.todas"),
}


# ------------------------------------------------------------------ §18.10
@router.get("", summary="Listar personal de KalliCode")
async def listar(
    st: Annotated[Staff, Depends(exigir(*ADMIN))],
    p: Annotated[Pagina, Depends(paginacion)],
    rol: Annotated[str | None, Query(description="Filtra por rol de staff.")] = None,
    estado: Annotated[str | None, Query(
        description="invited | active | deactivated.")] = None,
) -> dict[str, Any]:
    """Listado con rol, estado, último acceso y segundo factor inscrito."""
    if rol is not None and rol not in STAFF_ROLES:
        raise validacion("Rol de staff desconocido.", {"rol": rol})
    if estado is not None and estado not in ("invited", "active", "deactivated"):
        raise validacion("Estado desconocido.", {"estado": estado})

    orden = p.clausula_order(
        {"ultimo_acceso": "st.last_login_at", "nombre": "st.full_name",
         "alta": "st.created_at"},
        "st.last_login_at DESC NULLS LAST")
    filtros = "WHERE (:rol IS NULL OR st.role = :rol) " \
              "AND (:est IS NULL OR st.status = :est)"
    params = {"rol": rol, "est": estado, "lim": p.page_size, "off": p.offset}

    async with admin_session() as db:
        total = await uno(db, f"SELECT count(*) AS n FROM admin.staff st {filtros}",
                          params)
        filas = await todos(db, f"""
            SELECT st.id, st.full_name AS nombre, st.email, st.role AS rol,
                   st.status AS estado,
                   st.totp_secret IS NOT NULL AS mfa_inscrito,
                   st.last_login_at AS ultimo_acceso,
                   (SELECT count(*) FROM admin.access_grants g
                     WHERE g.staff_id = st.id AND g.revoked_at IS NULL
                       AND g.expires_at > now()) AS concesiones_vigentes
            FROM admin.staff st {filtros}
            ORDER BY {orden} LIMIT :lim OFFSET :off
        """, params)
        await registrar_accion(
            db, staff_id=st.id, staff_role=st.role, action="admin_query",
            endpoint="GET /admin/v1/staff", ip=st.ip, user_agent=st.user_agent,
            request_id=st.request_id,
            payload={"filtros": {"rol": rol, "estado": estado}})
    return sobre(filas, int(total["n"]) if total else 0, p)


# ------------------------------------------------------------------ §18.11
@router.post("/invitations", response_model=InvitarOut,
             summary="Invitar a un empleado")
async def invitar(cuerpo: InvitarIn,
                  st: Annotated[Staff, Depends(exigir(*ADMIN))]) -> InvitarOut:
    """Crea la invitación y envía el enlace al correo corporativo."""
    s = get_admin_settings()
    email = cuerpo.email.lower()
    if email.rsplit("@", 1)[-1] not in s.dominios_permitidos:
        raise validacion("El correo debe pertenecer a un dominio corporativo "
                         "autorizado.", {"dominios": list(s.dominios_permitidos)})
    if cuerpo.rol not in STAFF_ROLES:
        raise validacion("Rol de staff desconocido.", {"rol": cuerpo.rol})

    async with admin_session() as db:
        activo = await uno(db, "SELECT id FROM admin.staff "
                               "WHERE lower(email) = :e AND status = 'active'",
                           {"e": email})
        if activo is not None:
            raise conflicto("CONFLICTO_ESTADO",
                            "Ese correo ya tiene una cuenta activa.",
                            {"sugerencia": "usa PATCH /admin/v1/staff/{id} "
                                           "para cambiar el rol"})

        # Reemitir invalida cualquier invitación anterior no aceptada.
        await todos(db, """
            UPDATE admin.staff_invitations SET revoked_at = now()
            WHERE lower(email) = :e AND accepted_at IS NULL AND revoked_at IS NULL
            RETURNING id
        """, {"e": email})

        claro, hashed = generar_token_opaco("inv")
        inv_id = nuevo("inv")
        fila = await uno(db, """
            INSERT INTO admin.staff_invitations
                (id, email, role, token_hash, note, invited_by, expires_at)
            VALUES (:id, :e, :r, :h, :n, :by,
                    now() + make_interval(days => :d))
            RETURNING id, email, role, expires_at
        """, {"id": inv_id, "e": cuerpo.email, "r": cuerpo.rol, "h": hashed,
              "n": cuerpo.nota, "by": st.id, "d": s.invitation_ttl_days})
        assert fila is not None

        await registrar_accion(
            db, staff_id=st.id, staff_role=st.role, action="staff_managed",
            endpoint="POST /admin/v1/staff/invitations", ip=st.ip,
            user_agent=st.user_agent, request_id=st.request_id,
            payload={"evento": "invitacion_creada", "rol": cuerpo.rol,
                     "email_hash": hash_email(email), "nota": cuerpo.nota})

    # Por el stream de notificación viaja el identificador, nunca el token.
    log.info("staff.invitacion.creada", invitacion_id=inv_id, rol=cuerpo.rol,
             email=hash_email(email), token_ref=hashed[:12])
    if cuerpo.rol == "staff_admin":
        log.warning("staff.invitacion.rol_admin", invitacion_id=inv_id,
                    invitado_por=st.id)
    return InvitarOut(invitacion_id=fila["id"], email=fila["email"],
                      rol=fila["role"], caduca_el=fila["expires_at"])


# ------------------------------------------------------------------ §18.12
@router.patch("/{staff_id}", response_model=ActualizarOut,
              summary="Actualizar rol o estado de un empleado")
async def actualizar(
    cuerpo: ActualizarIn,
    st: Annotated[Staff, Depends(exigir(*ADMIN))],
    staff_id: Annotated[str, Path(description="Empleado a modificar.")],
) -> ActualizarOut:
    """Cambia el rol o desactiva. La desactivación corta el acceso de inmediato."""
    from ..errors import motivo_insuficiente

    if cuerpo.rol is None and cuerpo.estado is None:
        raise validacion("Indica al menos el rol o el estado.")
    if cuerpo.rol is not None and cuerpo.rol not in STAFF_ROLES:
        raise validacion("Rol de staff desconocido.", {"rol": cuerpo.rol})
    if cuerpo.estado is not None and cuerpo.estado not in ("active", "deactivated"):
        raise validacion("Estado no admitido.", {"estado": cuerpo.estado})
    if staff_id == st.id:
        from kallicode_core.errors import permiso_denegado

        raise permiso_denegado(
            "No puedes modificar tu propia cuenta por esta vía.")
    if cuerpo.estado == "deactivated" and not cuerpo.motivo:
        raise motivo_insuficiente("la desactivación exige motivo")

    async with admin_session() as db:
        objetivo = await uno(db, """
            SELECT id, role, status FROM admin.staff WHERE id = :i FOR UPDATE
        """, {"i": staff_id})
        if objetivo is None:
            raise no_encontrado("El empleado")

        # No se puede dejar la plataforma sin rol de administración.
        if (objetivo["role"] == "staff_admin"
                and (cuerpo.estado == "deactivated"
                     or (cuerpo.rol and cuerpo.rol != "staff_admin"))):
            restantes = await uno(db, """
                SELECT count(*) AS n FROM admin.staff
                WHERE role = 'staff_admin' AND status = 'active' AND id <> :i
            """, {"i": staff_id})
            if restantes and int(restantes["n"]) == 0:
                raise conflicto("CONFLICTO_ESTADO",
                                "No puedes desactivar al último administrador.")

        rol_final = cuerpo.rol or objetivo["role"]
        estado_final = cuerpo.estado or objetivo["status"]
        await uno(db, """
            UPDATE admin.staff
            SET role = :r, status = :e, updated_at = now(),
                deactivated_at = CASE WHEN :e = 'deactivated'
                    THEN now() ELSE NULL END,
                deactivated_reason = CASE WHEN :e = 'deactivated'
                    THEN :m ELSE NULL END,
                -- reactivar exige nueva inscripción del segundo factor
                totp_secret = CASE WHEN :e = 'active' AND :prev = 'deactivated'
                    THEN NULL ELSE totp_secret END
            WHERE id = :i RETURNING id
        """, {"r": rol_final, "e": estado_final, "m": cuerpo.motivo,
              "i": staff_id, "prev": objetivo["status"]})

        # Un cambio de rol revoca las sesiones para que el rol nuevo se resuelva
        # en el siguiente inicio y no quede el anterior en un token vigente.
        motivo_rev = ("desactivado" if estado_final == "deactivated"
                      else "cambio_de_rol")
        sesiones = await todos(db, """
            UPDATE admin.staff_refresh_tokens
            SET revoked = true, revoked_reason = :m
            WHERE staff_id = :s AND NOT revoked AND expires_at > now()
            RETURNING id
        """, {"s": staff_id, "m": motivo_rev})

        # La desactivación revoca también las concesiones vigentes: el acceso a
        # datos de cliente cesa en el mismo momento, no al caducar.
        concesiones: list[dict[str, Any]] = []
        if estado_final == "deactivated":
            concesiones = await todos(db, """
                UPDATE admin.access_grants
                SET revoked_at = now(), revoked_by = :by,
                    revoked_reason = 'personal desactivado'
                WHERE staff_id = :s AND revoked_at IS NULL AND expires_at > now()
                RETURNING id, tenant_id
            """, {"s": staff_id, "by": st.id})

        await registrar_accion(
            db, staff_id=st.id, staff_role=st.role, action="staff_managed",
            endpoint=f"PATCH /admin/v1/staff/{staff_id}", ip=st.ip,
            user_agent=st.user_agent, request_id=st.request_id,
            payload={"objetivo": staff_id, "rol": rol_final,
                     "estado": estado_final, "motivo": cuerpo.motivo,
                     "sesiones_revocadas": len(sesiones),
                     "concesiones_revocadas": len(concesiones)})

    if estado_final == "deactivated":
        log.critical("staff.desactivado", staff_id=staff_id, por=st.id,
                     sesiones=len(sesiones), concesiones=len(concesiones))
    else:
        log.info("staff.actualizado", staff_id=staff_id, rol=rol_final,
                 estado=estado_final, por=st.id)

    return ActualizarOut(id=staff_id, rol=rol_final, estado=estado_final,
                         sesiones_revocadas=len(sesiones),
                         concesiones_revocadas=len(concesiones))


__all__ = ["router"]
