"""§18.29 – §18.30 · Auditoría de las acciones del personal.

Vista interna equivalente a la que el cliente ve en su portal (§11.6). Su valor no
está en poder consultar una acción concreta, sino en detectar el patrón que
importa: acceso que deja de ser excepcional y se convierte en rutina. De ahí que
el listado devuelva el motivo íntegro y el contador de lecturas de cada concesión.

El registro es de solo lectura y proviene de una tabla append-only con cadena de
hash: no existe endpoint para modificarlo ni borrarlo, y ninguno podría existir
porque los disparadores de 001_admin_schema.sql lo impiden en la base.

El campo `verificado` no es decorativo. Se calcula verificando el tramo de cadena
correspondiente, y un valor falso es un incidente de integridad que dispara
alerta, no un detalle de la respuesta.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, status
from kallicode_core.errors import validacion
from kallicode_core.ids import nuevo
from kallicode_core.logging import log
from pydantic import BaseModel, ConfigDict, Field

from ..audit import registrar_accion, verificar_cadena
from ..db import admin_session, todos, uno
from ..deps import ADMIN, Staff, exigir, limite_rl4
from ..pagination import Pagina, paginacion, sobre
from ..settings import get_admin_settings

router = APIRouter(prefix="/admin/v1/audit", tags=["Auditoría del personal"])

_ACCIONES = (
    "grant_created",
    "grant_revoked",
    "read",
    "reveal",
    "report",
    "staff_managed",
    "admin_query",
)
_MAX_DIAS = 365


class _Base(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ExportIn(_Base):
    desde: date
    hasta: date
    tenant_id: str | None = Field(default=None, max_length=64)
    staff_id: str | None = Field(default=None, max_length=64)
    formato: str = "csv"


class ExportOut(_Base):
    export_id: str
    estado: str
    eventos_estimados: int


ALLOWLIST_ACCIONES_STAFF: dict[str, str] = {
    "ocurrido": "a.occurred_at",
    "occurred_at": "a.occurred_at",
    "creado_en": "a.occurred_at",
    "accion": "a.action",
    "action": "a.action",
    "tenant_id": "a.tenant_id",
    "staff_id": "a.staff_id",
}


# ------------------------------------------------------------------ §18.29
@router.get("/staff-actions", summary="Acciones del personal sobre datos de cliente")
async def acciones(
    st: Annotated[Staff, Depends(limite_rl4)],
    p: Annotated[Pagina, Depends(paginacion)],
    ambito: Annotated[str, Query(description="propias | todas.")] = "propias",
    staff_id: Annotated[
        str | None, Query(description="Filtra por empleado; solo en ámbito todas.")
    ] = None,
    tenant_id: Annotated[str | None, Query(description="Filtra por cliente afectado.")] = None,
    accion: Annotated[
        str | None, Query(description="grant_created | grant_revoked | read | reveal | report.")
    ] = None,
    desde: Annotated[date | None, Query()] = None,
    hasta: Annotated[date | None, Query()] = None,
) -> dict[str, Any]:
    """Registro de acciones, propias o de todo el personal."""
    if ambito not in ("propias", "todas"):
        raise validacion("Ámbito no válido.", {"ambito": ambito})
    if ambito == "todas" and st.role != "staff_admin":
        from ..errors import rol_staff_insuficiente

        raise rol_staff_insuficiente(
            "Solo el rol de administración puede ver las acciones de todo el personal."
        )
    if staff_id and staff_id != st.id and (ambito != "todas" or st.role != "staff_admin"):
        from ..errors import rol_staff_insuficiente

        raise rol_staff_insuficiente(
            "Filtrar por otro empleado exige ámbito 'todas' y rol de administración."
        )
    if accion is not None and accion not in _ACCIONES:
        raise validacion(
            "Acción desconocida.", {"accion": accion, "permitidas": list(_ACCIONES)}
        )

    hasta = hasta or date.today()
    desde = desde or (hasta - timedelta(days=90))
    if desde > hasta:
        raise validacion("El rango de fechas no es válido.")
    if (hasta - desde).days > _MAX_DIAS:
        raise validacion(
            f"El rango no puede superar {_MAX_DIAS} días.", {"dias": (hasta - desde).days}
        )

    cond = [
        "(:ambito = 'todas' OR a.staff_id = :yo)",
        "(CAST(:sid AS text) IS NULL OR a.staff_id = :sid)",
        "(CAST(:tid AS text) IS NULL OR a.tenant_id = :tid)",
        "(CAST(:acc AS text) IS NULL OR a.action = :acc)",
        "a.occurred_at >= CAST(:d AS date)",
        "a.occurred_at < CAST(:h AS date) + 1",
    ]
    where = "WHERE " + " AND ".join(cond)
    params = {
        "ambito": ambito,
        "yo": st.id,
        "sid": staff_id if ambito == "todas" else None,
        "tid": tenant_id,
        "acc": accion,
        "d": desde,
        "h": hasta,
        "lim": p.page_size,
        "off": p.offset,
    }
    orden = p.clausula_order(ALLOWLIST_ACCIONES_STAFF, "a.occurred_at DESC")

    async with admin_session() as db:
        total = await uno(
            db, f"SELECT count(*) AS n FROM admin.staff_actions a {where}", params
        )
        filas = await todos(
            db,
            f"""
            SELECT a.id::text AS id, a.occurred_at AS ocurrido_en,
                   a.action AS accion, a.tenant_id, a.scope AS alcance,
                   a.reason AS motivo, a.resource AS recurso, a.endpoint,
                   a.seal AS sello,
                   jsonb_build_object('id', a.staff_id, 'nombre', s.full_name,
                                      'rol', a.staff_role) AS staff
            FROM admin.staff_actions a
            JOIN admin.staff s ON s.id = a.staff_id
            {where}
            ORDER BY {orden} LIMIT :lim OFFSET :off
        """,
            params,
        )

        # La verificación se hace sobre el tramo consultado, no sobre toda la
        # cadena: el coste no debe crecer con la historia (lección de BE-F32).
        rupturas = await verificar_cadena(db, str(desde), str(hasta + timedelta(days=1)))
        integra = not rupturas
        for f in filas:
            f["verificado"] = integra

        if ambito == "todas":
            await registrar_accion(
                db,
                staff_id=st.id,
                staff_role=st.role,
                action="admin_query",
                endpoint="GET /admin/v1/audit/staff-actions",
                ip=st.ip,
                user_agent=st.user_agent,
                request_id=st.request_id,
                payload={
                    "ambito": "todas",
                    "rango": [str(desde), str(hasta)],
                    "resultados": len(filas),
                },
            )

    if rupturas:
        log.critical(
            "admin.audit.no_verificado",
            rupturas=len(rupturas),
            primera=rupturas[0]["motivo"],
            rango=[str(desde), str(hasta)],
        )

    salida = sobre(filas, int(total["n"]) if total else 0, p)
    salida["integridad"] = {
        "verificada": integra,
        "rupturas": [{"en": r["broken_at"], "motivo": r["motivo"]} for r in rupturas] or None,
    }
    return salida


# ------------------------------------------------------------------ §18.30
@router.post(
    "/staff-actions/exports",
    response_model=ExportOut,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Exportar el registro de acciones del personal",
)
async def exportar(
    cuerpo: ExportIn, st: Annotated[Staff, Depends(exigir(*ADMIN))]
) -> ExportOut:
    """Encola la exportación del registro para una auditoría externa.

    El fichero incluye el sello de cada evento y el resultado de la verificación
    de cadena: es el artefacto que se entrega a un cliente que pide constancia
    formal de quién ha accedido a sus datos.
    """
    s = get_admin_settings()
    if cuerpo.formato not in ("csv", "pdf"):
        raise validacion(
            "Formato no admitido.", {"formato": cuerpo.formato, "permitidos": ["csv", "pdf"]}
        )
    if cuerpo.desde > cuerpo.hasta:
        raise validacion("El rango de fechas no es válido.")
    meses = (cuerpo.hasta - cuerpo.desde).days / 30.0
    if meses > s.report_max_months:
        raise validacion(
            f"El rango no puede superar {s.report_max_months} meses.",
            {"meses": round(meses, 1)},
        )

    export_id = nuevo("ex")
    async with admin_session() as db:
        estimados = await uno(
            db,
            """
            SELECT count(*) AS n FROM admin.staff_actions a
            WHERE a.occurred_at >= CAST(:d AS date)
              AND a.occurred_at < CAST(:h AS date) + 1
              AND (CAST(:tid AS text) IS NULL OR a.tenant_id = :tid)
              AND (CAST(:sid AS text) IS NULL OR a.staff_id = :sid)
        """,
            {
                "d": cuerpo.desde,
                "h": cuerpo.hasta,
                "tid": cuerpo.tenant_id,
                "sid": cuerpo.staff_id,
            },
        )

        await uno(
            db,
            """
            INSERT INTO admin.reports
                (id, kind, format, params, requested_by, includes_pii, status,
                 expires_at)
            VALUES (:id, 'staff_actions', :fmt, CAST(:p AS jsonb), :by, true,
                    'en_cola', now() + make_interval(days => :ret))
            RETURNING id
        """,
            {
                "id": export_id,
                "fmt": cuerpo.formato,
                "p": cuerpo.model_dump_json(),
                "by": st.id,
                "ret": s.report_retention_days,
            },
        )

        await registrar_accion(
            db,
            staff_id=st.id,
            staff_role=st.role,
            action="report",
            endpoint="POST /admin/v1/audit/staff-actions/exports",
            tenant_id=cuerpo.tenant_id,
            ip=st.ip,
            user_agent=st.user_agent,
            request_id=st.request_id,
            payload={
                "export_id": export_id,
                "formato": cuerpo.formato,
                "rango": [str(cuerpo.desde), str(cuerpo.hasta)],
                "eventos_estimados": int(estimados["n"]) if estimados else 0,
            },
        )

    log.info(
        "admin.audit.export_solicitado",
        export_id=export_id,
        formato=cuerpo.formato,
        staff_id=st.id,
    )
    return ExportOut(
        export_id=export_id,
        estado="en_cola",
        eventos_estimados=int(estimados["n"]) if estimados else 0,
    )


__all__ = ["router"]
