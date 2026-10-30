"""§11.6 · Exposición de accesos del personal hacia el portal del cliente (ADM-G04).

Proyección de auditoría de solo lectura y alta transparencia que permite a los
roles autorizados del cliente (owner, admin, architect, approver) verificar qué
empleados han accedido a sus datos organizacionales, con qué alcance y bajo qué
motivo verificado, sin exponer identificadores internos del personal.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, status
from kallicode_core.errors import validacion
from pydantic import BaseModel, ConfigDict

from ..audit import consultar_accesos_staff_para_portal
from ..db import admin_session
from ..deps import UsuarioPortal, usuario_portal_actual

router = APIRouter(tags=["Auditoría del portal cliente"])

_MAX_DIAS = 365


class ActorPublico(BaseModel):
    model_config = ConfigDict(extra="forbid")
    nombre: str
    rol: str


class StaffAccessItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    actor: ActorPublico
    motivo: str
    alcance: str
    concedido_en: str
    caduca_en: str
    accesos: int
    verificado: bool


class StaffAccessesOut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    items: list[StaffAccessItem]
    total: int
    page: int
    page_size: int


@router.get(
    "/api/v1/audit/staff-accesses",
    response_model=StaffAccessesOut,
    status_code=status.HTTP_200_OK,
    summary="Accesos del personal de KalliCode a datos del tenant",
    include_in_schema=False,
)
@router.get(
    "/audit/staff-accesses",
    response_model=StaffAccessesOut,
    status_code=status.HTTP_200_OK,
    summary="Accesos del personal de KalliCode a datos del tenant (alias)",
    include_in_schema=False,
)
async def listar_accesos_staff_portal(
    usuario: Annotated[UsuarioPortal, Depends(usuario_portal_actual)],
    desde: Annotated[date | None, Query(description="Fecha inicio (YYYY-MM-DD)")] = None,
    hasta: Annotated[date | None, Query(description="Fecha fin (YYYY-MM-DD)")] = None,
    ticket_id: Annotated[
        str | None, Query(description="Filtra por identificador de caso/incidencia (KC-####)")
    ] = None,
    page: Annotated[int, Query(ge=1, description="Número de página, >= 1")] = 1,
    page_size: Annotated[int, Query(ge=1, le=100, description="Tamaño de página, 1..100")] = 25,
) -> dict[str, Any]:
    """Consulta los accesos de staff registrados sobre los datos del cliente autenticado."""
    hoy = datetime.now(UTC).date()
    fecha_hasta = hasta or hoy
    fecha_desde = desde or (fecha_hasta - timedelta(days=90))

    if fecha_desde > fecha_hasta:
        raise validacion(
            "El rango de fechas no es válido: 'desde' no puede ser posterior a 'hasta'.",
            {"desde": str(fecha_desde), "hasta": str(fecha_hasta)},
        )

    dias = (fecha_hasta - fecha_desde).days
    if dias > _MAX_DIAS:
        raise validacion(
            f"El rango no puede superar {_MAX_DIAS} días.",
            {"dias": dias, "maximo": _MAX_DIAS},
        )

    offset = (page - 1) * page_size

    async with admin_session() as db:
        items, total = await consultar_accesos_staff_para_portal(
            db,
            tenant_id=usuario.tenant_id,
            desde=fecha_desde,
            hasta=fecha_hasta,
            ticket_id=ticket_id,
            limit=page_size,
            offset=offset,
        )

    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
    }


__all__ = ["router"]
