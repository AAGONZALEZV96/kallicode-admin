"""§18.13 – §18.15 · Concesiones de acceso a datos de cliente.

Es el bloque que hace defendible la excepción de aislamiento de §3.3.1. Sin él, la
consola sería un rol con acceso permanente a todos los clientes; con él, el acceso
a datos identificables es un acto declarado, acotado en el tiempo y visible para
el cliente afectado en su propio portal (§11.6).

Cuatro decisiones de diseño que importan más que el código:

  · El motivo se valida en longitud **y en contenido**: se rechaza si es genérico.
    La auditoría vale lo que valga el motivo, y un registro lleno de «revisión»
    no es una garantía, es un trámite.
  · El alcance `contenido_codigo` dura como máximo 60 minutos y exige referencia
    a un caso, porque es el que expone propiedad intelectual del cliente.
  · Máximo tres concesiones simultáneas por empleado, para que el acceso amplio
    no se normalice.
  · Una concesión no se prorroga. Caducada, se solicita otra con motivo nuevo.
"""

from __future__ import annotations

import re
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Path, Query, Response, status
from kallicode_core.errors import no_encontrado, rate_limit, validacion
from kallicode_core.ids import nuevo
from kallicode_core.logging import log
from pydantic import BaseModel, ConfigDict, Field

from ..audit import registrar_accion
from ..db import admin_session, read_session, todos, uno
from ..deps import SOPORTE, Staff, StaffDep, exigir, limite_rl4
from ..errors import concesion_duplicada, motivo_insuficiente, rol_staff_insuficiente
from ..masking import JERARQUIA
from ..pagination import Pagina, paginacion, sobre
from ..settings import get_admin_settings

router = APIRouter(prefix="/admin/v1/access-grants", tags=["Concesiones de acceso"])

# Motivos que no justifican nada. Un motivo debe describir el caso concreto.
_PATRONES_VACIOS = re.compile(
    r"^(revisi[oó]n|prueba|test|soporte|comprobaci[oó]n|an[aá]lisis|consulta|"
    r"verificaci[oó]n|mirar|ver|debug|depuraci[oó]n)\W*$",
    re.IGNORECASE,
)
# Al menos una referencia verificable: un código de caso o un identificador.
_TIENE_REFERENCIA = re.compile(r"[A-Z]{2,}-\d+|#\d+|\bKC-\d+\b")


class _Base(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CrearIn(_Base):
    tenant_id: str = Field(min_length=3, max_length=64)
    alcance: str
    motivo: str = Field(min_length=20, max_length=500)
    duracion_min: int | None = Field(default=None, ge=15, le=480)
    referencia: str | None = Field(default=None, max_length=64)


class CrearOut(_Base):
    grant_id: str
    tenant_id: str
    alcance: str
    motivo: str
    concedido_en: Any
    caduca_en: Any
    visible_para_cliente_en: Any


class RevocarIn(_Base):
    motivo: str | None = Field(default=None, min_length=10, max_length=280)


class RevocarOut(_Base):
    grant_id: str
    revocada_en: Any


def _validar_motivo(motivo: str, alcance: str, referencia: str | None) -> None:
    """Rechaza motivos que no describen un caso concreto."""
    limpio = motivo.strip()
    if _PATRONES_VACIOS.match(limpio):
        raise motivo_insuficiente(
            "el motivo es genérico: describe el caso, la incidencia o la "
            "solicitud que justifica el acceso"
        )
    if len(set(limpio.lower().split())) < 5:
        raise motivo_insuficiente("el motivo no describe un caso concreto")
    if alcance == "contenido_codigo" and not (referencia or _TIENE_REFERENCIA.search(limpio)):
        raise motivo_insuficiente(
            "el acceso a contenido de código exige referencia a un caso verificable"
        )


# ------------------------------------------------------------------ §18.13
@router.post(
    "",
    response_model=CrearOut,
    status_code=status.HTTP_201_CREATED,
    summary="Solicitar acceso a los datos de un cliente",
)
async def crear(cuerpo: CrearIn, st: Annotated[Staff, Depends(exigir(*SOPORTE))]) -> CrearOut:
    """Crea una concesión justificada y temporal.

    La concesión no amplía el rol: un empleado con rol de soporte no obtiene por
    esta vía acceso a los agregados globales de negocio.
    """
    s = get_admin_settings()
    if cuerpo.alcance not in JERARQUIA:
        raise validacion(
            "Alcance desconocido.", {"alcance": cuerpo.alcance, "permitidos": list(JERARQUIA)}
        )
    _validar_motivo(cuerpo.motivo, cuerpo.alcance, cuerpo.referencia)

    minutos = cuerpo.duracion_min or s.grant_default_minutes
    if cuerpo.alcance == "contenido_codigo":
        minutos = min(minutos, s.grant_code_max_minutes)

    async with read_session() as db_ro:
        org = await uno(
            db_ro, "SELECT id FROM core.organizations WHERE id = :t", {"t": cuerpo.tenant_id}
        )
        if org is None:
            raise no_encontrado("La organización")

    async with admin_session() as db:
        vigente = await uno(
            db,
            """
            SELECT id FROM admin.access_grants
            WHERE staff_id = :s AND tenant_id = :t AND scope = :sc
              AND revoked_at IS NULL AND expires_at > now()
        """,
            {"s": st.id, "t": cuerpo.tenant_id, "sc": cuerpo.alcance},
        )
        if vigente is not None:
            raise concesion_duplicada(vigente["id"])

        activas = await uno(
            db,
            """
            SELECT count(*) AS n FROM admin.access_grants
            WHERE staff_id = :s AND revoked_at IS NULL AND expires_at > now()
        """,
            {"s": st.id},
        )
        if activas and int(activas["n"]) >= s.grant_max_concurrent:
            raise rate_limit(60)

        grant_id = nuevo("gr")
        fila = await uno(
            db,
            """
            INSERT INTO admin.access_grants
                (id, staff_id, tenant_id, scope, reason, reference,
                 granted_at, expires_at)
            VALUES (:id, :s, :t, :sc, :rz, :rf, now(),
                    now() + make_interval(mins => :m))
            RETURNING id, tenant_id, scope, reason, granted_at, expires_at
        """,
            {
                "id": grant_id,
                "s": st.id,
                "t": cuerpo.tenant_id,
                "sc": cuerpo.alcance,
                "rz": cuerpo.motivo,
                "rf": cuerpo.referencia,
                "m": minutos,
            },
        )
        assert fila is not None

        # El evento que el cliente verá en su portal (§11.6).
        await registrar_accion(
            db,
            staff_id=st.id,
            staff_role=st.role,
            action="grant_created",
            endpoint="POST /admin/v1/access-grants",
            tenant_id=cuerpo.tenant_id,
            grant_id=grant_id,
            scope=cuerpo.alcance,
            reason=cuerpo.motivo,
            ip=st.ip,
            user_agent=st.user_agent,
            request_id=st.request_id,
            payload={"duracion_min": minutos, "referencia": cuerpo.referencia},
        )

    log.info(
        "admin.grant.creado",
        grant_id=grant_id,
        tenant_id=cuerpo.tenant_id,
        alcance=cuerpo.alcance,
        duracion_min=minutos,
        staff_id=st.id,
    )
    if cuerpo.alcance == "contenido_codigo":
        log.critical(
            "admin.grant.contenido_codigo",
            grant_id=grant_id,
            tenant_id=cuerpo.tenant_id,
            staff_id=st.id,
            referencia=cuerpo.referencia,
        )

    return CrearOut(
        grant_id=fila["id"],
        tenant_id=fila["tenant_id"],
        alcance=fila["scope"],
        motivo=fila["reason"],
        concedido_en=fila["granted_at"],
        caduca_en=fila["expires_at"],
        visible_para_cliente_en=fila["granted_at"],
    )


# ------------------------------------------------------------------ §18.14
@router.get("", summary="Listar concesiones de acceso")
async def listar(
    st: Annotated[Staff, Depends(limite_rl4)],
    p: Annotated[Pagina, Depends(paginacion)],
    ambito: Annotated[str, Query(description="propias | todas.")] = "propias",
    tenant_id: Annotated[str | None, Query()] = None,
    estado: Annotated[str | None, Query(description="vigente | caducada | revocada.")] = None,
    desde: Annotated[str | None, Query()] = None,
    hasta: Annotated[str | None, Query()] = None,
) -> dict[str, Any]:
    """Lista las concesiones. El ámbito `todas` exige rol de administración.

    Con otro rol se devuelve 403 y no un listado recortado, para que el
    comportamiento sea inequívoco.
    """
    if ambito not in ("propias", "todas"):
        raise validacion("Ámbito no válido.", {"ambito": ambito})
    if ambito == "todas" and st.role != "staff_admin":
        raise rol_staff_insuficiente(
            "Solo el rol de administración puede ver las concesiones de todo el personal."
        )
    if estado is not None and estado not in ("vigente", "caducada", "revocada"):
        raise validacion("Estado no válido.", {"estado": estado})

    cond = [
        "(:ambito = 'todas' OR g.staff_id = :yo)",
        "(CAST(:t AS text) IS NULL OR g.tenant_id = :t)",
        "(CAST(:d AS text) IS NULL OR g.granted_at >= CAST(:d AS date))",
        "(CAST(:h AS text) IS NULL OR g.granted_at < CAST(:h AS date) + 1)",
    ]
    if estado == "vigente":
        cond.append("g.revoked_at IS NULL AND g.expires_at > now()")
    elif estado == "caducada":
        cond.append("g.revoked_at IS NULL AND g.expires_at <= now()")
    elif estado == "revocada":
        cond.append("g.revoked_at IS NOT NULL")
    where = "WHERE " + " AND ".join(cond)
    params = {
        "ambito": ambito,
        "yo": st.id,
        "t": tenant_id,
        "d": desde,
        "h": hasta,
        "lim": p.page_size,
        "off": p.offset,
    }
    orden = p.clausula_order(
        {"concedido": "g.granted_at", "caduca": "g.expires_at", "lecturas": "g.reads"},
        "g.granted_at DESC",
    )

    async with admin_session() as db:
        total = await uno(
            db, f"SELECT count(*) AS n FROM admin.access_grants g {where}", params
        )
        filas = await todos(
            db,
            f"""
            SELECT g.id AS grant_id, g.tenant_id, g.scope AS alcance,
                   g.reason AS motivo, g.reference AS referencia,
                   g.granted_at AS concedido_en, g.expires_at AS caduca_en,
                   g.reads AS lecturas,
                   CASE WHEN g.revoked_at IS NOT NULL THEN 'revocada'
                        WHEN g.expires_at <= now() THEN 'caducada'
                        ELSE 'vigente' END AS estado,
                   CASE WHEN g.revoked_at IS NULL THEN NULL ELSE
                        jsonb_build_object('staff_id', g.revoked_by,
                                           'nombre', rv.full_name,
                                           'en', g.revoked_at,
                                           'motivo', g.revoked_reason)
                   END AS revocada_por,
                   CASE WHEN :ambito = 'todas' THEN
                        jsonb_build_object('id', s.id, 'nombre', s.full_name,
                                           'rol', s.role)
                   ELSE NULL END AS staff
            FROM admin.access_grants g
            JOIN admin.staff s ON s.id = g.staff_id
            LEFT JOIN admin.staff rv ON rv.id = g.revoked_by
            {where}
            ORDER BY {orden} LIMIT :lim OFFSET :off
        """,
            params,
        )

        if ambito == "todas":
            await registrar_accion(
                db,
                staff_id=st.id,
                staff_role=st.role,
                action="admin_query",
                endpoint="GET /admin/v1/access-grants",
                ip=st.ip,
                user_agent=st.user_agent,
                request_id=st.request_id,
                payload={"ambito": "todas", "resultados": len(filas)},
            )
    return sobre(filas, int(total["n"]) if total else 0, p)


# ------------------------------------------------------------------ §18.15
@router.delete(
    "/{grant_id}", response_model=RevocarOut, summary="Revocar una concesión de acceso"
)
async def revocar(
    st: StaffDep,
    grant_id: Annotated[str, Path(description="Concesión a revocar.")],
    cuerpo: RevocarIn | None = None,
) -> RevocarOut | Response:
    """Revoca una concesión antes de su vencimiento.

    Cerrar la propia concesión al terminar la investigación es la práctica
    esperada, no una excepción. Revocar una ajena exige rol de administración y
    motivo, y notifica al empleado afectado.
    """
    motivo = cuerpo.motivo if cuerpo else None
    async with admin_session() as db:
        g = await uno(
            db,
            """
            SELECT id, staff_id, tenant_id, scope, reason, revoked_at, expires_at
            FROM admin.access_grants WHERE id = :i FOR UPDATE
        """,
            {"i": grant_id},
        )
        if g is None:
            raise no_encontrado("La concesión")

        ajena = g["staff_id"] != st.id
        if ajena and st.role != "staff_admin":
            # No se revela la existencia de una concesión ajena.
            raise no_encontrado("La concesión")
        if ajena and not motivo:
            raise motivo_insuficiente("revocar una concesión ajena exige motivo")

        # Idempotente: revocar una ya revocada o caducada no es un error.
        if g["revoked_at"] is not None:
            return Response(status_code=status.HTTP_204_NO_CONTENT)

        fila = await uno(
            db,
            """
            UPDATE admin.access_grants
            SET revoked_at = now(), revoked_by = :by, revoked_reason = :m
            WHERE id = :i RETURNING id, revoked_at
        """,
            {"i": grant_id, "by": st.id, "m": motivo or "cerrada por el propio empleado"},
        )
        assert fila is not None

        await registrar_accion(
            db,
            staff_id=st.id,
            staff_role=st.role,
            action="grant_revoked",
            endpoint=f"DELETE /admin/v1/access-grants/{grant_id}",
            tenant_id=g["tenant_id"],
            grant_id=grant_id,
            scope=g["scope"],
            reason=motivo or "cerrada por el propio empleado",
            ip=st.ip,
            user_agent=st.user_agent,
            request_id=st.request_id,
            payload={"ajena": ajena, "titular": g["staff_id"]},
        )

    log.info("admin.grant.revocado", grant_id=grant_id, por=st.id, ajena=ajena)
    return RevocarOut(grant_id=fila["id"], revocada_en=fila["revoked_at"])


__all__ = ["router"]
