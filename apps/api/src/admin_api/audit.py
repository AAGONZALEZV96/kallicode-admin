"""Auditoría de las acciones del personal (§18.29, brecha ADM-G04).

Toda acción del personal sobre datos de cliente se registra en
`admin.staff_actions`, tabla append-only con cadena de hash propia. El sellado y
el encadenamiento los hace el disparador de 001_admin_schema.sql, de modo que ni
esta capa ni ninguna otra puedan alterar el orden ni recalcular un sello.

Sobre la cadena central: la de la plataforma (`audit.audit_events`) asume un
actor perteneciente al tenant, y su extensión para admitir actores de personal la
entrega E5. Hasta entonces el registro vive aquí con la misma semántica —actor,
motivo, alcance, tenant afectado y vencimiento— para que la migración no pierda
información. Es una decisión declarada, no una omisión: la garantía existe desde
el primer día y lo único que cambia después es dónde vive el registro.

Y una diferencia deliberada con la cadena central: aquí el sello previo se toma
de la cabeza de cadena y no del propio evento, de modo que la verificación pueda
comprobar el encadenamiento real. Es la corrección de origen del defecto DB-F04.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Literal

from kallicode_core.logging import log
from sqlalchemy.ext.asyncio import AsyncSession

from .db import todos, uno

Accion = Literal["grant_created", "grant_revoked", "read", "reveal", "report",
                 "staff_managed", "admin_query"]

# Acciones que exigen tenant afectado: son las que tocan datos de un cliente.
_EXIGEN_TENANT: frozenset[str] = frozenset({"grant_created", "grant_revoked",
                                            "read", "reveal"})


async def registrar_accion(
    db: AsyncSession,
    *,
    staff_id: str,
    staff_role: str,
    action: Accion,
    endpoint: str,
    tenant_id: str | None = None,
    grant_id: str | None = None,
    scope: str | None = None,
    reason: str | None = None,
    resource: str | None = None,
    ip: str | None = None,
    user_agent: str | None = None,
    request_id: str | None = None,
    payload: dict[str, Any] | None = None,
) -> str:
    """Registra una acción del personal y devuelve su sello.

    Parámetros:
        action: tipo del catálogo; las de lectura y revelación exigen tenant.
        payload: datos estructurados de la acción. Nunca contenido de código ni
                 datos personales del cliente: aquí van filtros, recuentos y
                 referencias, no el material leído.

    Devuelve el sello hexadecimal de 64 caracteres que calcula el disparador.
    """
    if action in _EXIGEN_TENANT and not tenant_id:
        raise ValueError(
            f"la acción {action} exige tenant_id: sin cliente afectado el "
            f"registro no es auditable")

    fila = await uno(db, """
        INSERT INTO admin.staff_actions
            (staff_id, staff_role, action, tenant_id, grant_id, scope, reason,
             resource, endpoint, ip, user_agent, request_id, payload,
             prev_seal, seal)
        VALUES (:sid, :rol, :act, :tid, :gid, :sc, :rz, :res, :ep, :ip, :ua,
                :rq, CAST(:pl AS jsonb), '', '')
        RETURNING seal
    """, {
        "sid": staff_id, "rol": staff_role, "act": action, "tid": tenant_id,
        "gid": grant_id, "sc": scope, "rz": reason, "res": resource,
        "ep": endpoint, "ip": ip, "ua": user_agent, "rq": request_id,
        "pl": json.dumps(payload) if payload is not None else None,
    })
    assert fila is not None
    sello: str = fila["seal"]
    log.info("admin.audit.accion", accion=action, staff_id=staff_id,
             tenant_id=tenant_id, alcance=scope, sello=sello[:12])
    return sello


async def registrar_lectura(
    db: AsyncSession,
    *,
    staff_id: str,
    staff_role: str,
    endpoint: str,
    tenant_id: str,
    grant_id: str,
    scope: str,
    reason: str,
    resource: str | None = None,
    ip: str | None = None,
    user_agent: str | None = None,
    request_id: str | None = None,
    revelado: list[str] | None = None,
) -> str:
    """Registra una lectura al amparo de una concesión e incrementa su contador.

    Se llama una vez por petición servida con concesión, no una vez por fila
    devuelta: lo que se audita es el acceso, no el recuento de registros.
    """
    sello = await registrar_accion(
        db, staff_id=staff_id, staff_role=staff_role,
        action="reveal" if revelado else "read",
        endpoint=endpoint, tenant_id=tenant_id, grant_id=grant_id,
        scope=scope, reason=reason, resource=resource, ip=ip,
        user_agent=user_agent, request_id=request_id,
        payload={"bloques_revelados": revelado} if revelado else None,
    )
    # El contador de lecturas de la concesión es lo que permite detectar el
    # patrón que importa: acceso que deja de ser excepcional y se vuelve rutina.
    await uno(db, """
        UPDATE admin.access_grants SET reads = reads + 1
        WHERE id = :g RETURNING id
    """, {"g": grant_id})
    return sello


async def verificar_cadena(
    db: AsyncSession,
    desde: datetime | str | None = None,
    hasta: datetime | str | None = None,
) -> list[dict[str, Any]]:
    """Verifica sello y encadenamiento del registro de acciones.

    Devuelve la lista de rupturas encontradas; una lista vacía significa que la
    cadena es íntegra. Un resultado no vacío es un incidente de integridad y no
    un detalle de la respuesta: el llamador debe registrarlo como CRITICAL.
    """
    return await todos(db, """
        SELECT broken_at, broken_id, motivo
        FROM admin.verify_staff_action_chain(
            CAST(:d AS timestamptz), CAST(:h AS timestamptz))
    """, {"d": desde, "h": hasta})
