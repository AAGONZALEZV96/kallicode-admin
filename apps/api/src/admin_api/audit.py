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

import hashlib
import json
from datetime import date, datetime, timedelta
from typing import Any, Literal

from kallicode_core.logging import log
from sqlalchemy.ext.asyncio import AsyncSession

from .db import todos, uno

Accion = Literal[
    "grant_created",
    "grant_revoked",
    "read",
    "reveal",
    "report",
    "staff_managed",
    "admin_query",
    "grant_creado",
    "grant_revocado",
    "lectura",
    "revelacion",
    "informe",
    "login",
    "logout",
]

# Acciones que exigen tenant afectado: son las que tocan datos de un cliente.
_EXIGEN_TENANT: frozenset[str] = frozenset(
    {
        "grant_created",
        "grant_revoked",
        "read",
        "reveal",
        "grant_creado",
        "grant_revocado",
        "lectura",
        "revelacion",
    }
)


class ResultadoIntegridadCadena(dict[str, Any]):
    """Resultado estructurado de la verificación criptográfica de la cadena."""

    @property
    def integra(self) -> bool:
        return bool(self.get("integra", False))

    @property
    def verificado(self) -> bool:
        return bool(self.get("verificado", self.integra))

    @property
    def roturas(self) -> list[dict[str, Any]]:
        return list(self.get("roturas", []))

    @property
    def total_roturas(self) -> int:
        return int(self.get("total_roturas", 0))

    @property
    def primer_evento_roto(self) -> dict[str, Any] | None:
        primer = self.get("primer_evento_roto")
        if primer is not None:
            return primer  # type: ignore[no-any-return]
        roturas = self.roturas
        return roturas[0] if roturas else None


async def registrar_accion(
    db: AsyncSession,
    *,
    staff_id: str,
    staff_role: str,
    action: Accion,
    endpoint: str,
    staff_email: str | None = None,
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
            f"registro no es auditable"
        )

    fila = await uno(
        db,
        """
        INSERT INTO admin.staff_actions
            (staff_id, staff_email, staff_role, action, tenant_id, grant_id, scope, reason,
             resource, endpoint, ip, user_agent, request_id, payload,
             prev_seal, seal)
        VALUES (:sid, :sem, :rol, :act, :tid, :gid, :sc, :rz, :res, :ep, :ip, :ua,
                :rq, CAST(:pl AS jsonb), '', '')
        RETURNING seal
    """,
        {
            "sid": staff_id,
            "sem": staff_email,
            "rol": staff_role,
            "act": action,
            "tid": tenant_id,
            "gid": grant_id,
            "sc": scope,
            "rz": reason,
            "res": resource,
            "ep": endpoint,
            "ip": ip,
            "ua": user_agent,
            "rq": request_id,
            "pl": json.dumps(payload) if payload is not None else None,
        },
    )
    assert fila is not None
    sello: str = fila["seal"]
    log.info(
        "admin.audit.accion",
        accion=action,
        staff_id=staff_id,
        tenant_id=tenant_id,
        alcance=scope,
        sello=sello[:12],
    )
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
        db,
        staff_id=staff_id,
        staff_role=staff_role,
        action="reveal" if revelado else "read",
        endpoint=endpoint,
        tenant_id=tenant_id,
        grant_id=grant_id,
        scope=scope,
        reason=reason,
        resource=resource,
        ip=ip,
        user_agent=user_agent,
        request_id=request_id,
        payload={"bloques_revelados": revelado} if revelado else None,
    )
    # El contador de lecturas de la concesión es lo que permite detectar el
    # patrón que importa: acceso que deja de ser excepcional y se vuelve rutina.
    await uno(
        db,
        """
        UPDATE admin.access_grants SET reads = reads + 1
        WHERE id = :g RETURNING id
    """,
        {"g": grant_id},
    )
    return sello


async def verificar_cadena(
    db: AsyncSession,
    desde: str | None = None,
    hasta: str | None = None,
) -> list[dict[str, Any]]:
    """Verifica sello y encadenamiento del registro de acciones.

    Devuelve la lista de rupturas encontradas; una lista vacía significa que la
    cadena es íntegra. Un resultado no vacío es un incidente de integridad y no
    un detalle de la respuesta: el llamador debe registrarlo como CRITICAL.
    """
    return await todos(
        db,
        """
        SELECT broken_at, broken_id, motivo
        FROM admin.verify_staff_action_chain(
            CAST(CAST(:d AS text) AS timestamptz), CAST(CAST(:h AS text) AS timestamptz))
    """,
        {"d": desde, "h": hasta},
    )


async def registrar_accion_staff(
    db: AsyncSession,
    *,
    staff_id: str,
    staff_email: str | None = None,
    staff_rol: str | None = None,
    staff_role: str | None = None,
    accion: str | None = None,
    action: str | None = None,
    tenant_id: str | None = None,
    alcance: str | None = None,
    scope: str | None = None,
    motivo: str | None = None,
    reason: str | None = None,
    recurso: str | None = None,
    resource: str | None = None,
    endpoint: str = "/admin/v1",
    grant_id: str | None = None,
    ip: str | None = None,
    user_agent: str | None = None,
    request_id: str | None = None,
    datos: dict[str, Any] | None = None,
    payload: dict[str, Any] | None = None,
) -> str:
    """Registra atómicamente una acción del personal bajo la transacción DML.

    Acepta parámetros tanto en nomenclatura en español como en inglés para
    garantizar consistencia con los contratos funcionales y el backlog E6.
    """
    final_role = staff_rol or staff_role or "staff_admin"
    final_action = accion or action or "admin_query"
    final_scope = alcance if alcance is not None else scope
    final_reason = motivo if motivo is not None else reason
    final_resource = recurso if recurso is not None else resource
    final_payload = datos if datos is not None else payload

    return await registrar_accion(
        db,
        staff_id=staff_id,
        staff_email=staff_email,
        staff_role=final_role,
        action=final_action,  # type: ignore[arg-type]
        endpoint=endpoint,
        tenant_id=tenant_id,
        grant_id=grant_id,
        scope=final_scope,
        reason=final_reason,
        resource=final_resource,
        ip=ip,
        user_agent=user_agent,
        request_id=request_id,
        payload=final_payload,
    )


async def verificar_cadena_staff_actions(
    db: AsyncSession,
    desde: str | None = None,
    hasta: str | None = None,
) -> ResultadoIntegridadCadena:
    """Verifica la integridad criptográfica de la cadena completa o del rango indicado.

    Retorna un objeto ResultadoIntegridadCadena con:
      - integra = True si la cadena es íntegra y no ha sido alterada.
      - verificado = True solo si el tramo evaluado es íntegro.
      - roturas = lista de incidentes detectados si hay inconsistencias.
      - total_roturas = número de incidentes.
      - primer_evento_roto = primer incidente detectado (o None si es íntegra).
    """
    roturas = await verificar_cadena(db, desde=desde, hasta=hasta)
    integro = len(roturas) == 0
    primer = roturas[0] if roturas else None
    return ResultadoIntegridadCadena(
        integra=integro,
        verificado=integro,
        roturas=roturas,
        total_roturas=len(roturas),
        primer_evento_roto=primer,
    )


def calcular_sello_staff_action(
    *,
    prev_seal: str,
    occurred_at: datetime | str,
    staff_id: str,
    action: str,
    endpoint: str,
    tenant_id: str | None = None,
    scope: str | None = None,
    reason: str | None = None,
    resource: str | None = None,
    payload: dict[str, Any] | str | None = None,
) -> str:
    """Recalcula de forma determinista el sello SHA-256 de una acción de personal.

    Reproduce de manera idéntica la lógica del trigger PostgreSQL admin.seal_staff_action():
      sello = SHA-256(
          prev_seal || occurred_at::text || staff_id || action
          || coalesce(tenant_id, '') || coalesce(scope, '')
          || coalesce(reason, '') || coalesce(resource, '')
          || endpoint || coalesce(payload::text, '')
      )
    """
    ts_str = str(occurred_at)

    if payload is None:
        pl_str = ""
    elif isinstance(payload, str):
        pl_str = payload
    else:
        pl_str = json.dumps(payload, separators=(", ", ": "))

    raw = (
        prev_seal
        + ts_str
        + staff_id
        + action
        + (tenant_id or "")
        + (scope or "")
        + (reason or "")
        + (resource or "")
        + endpoint
        + pl_str
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


async def recalcular_y_verificar_cadena(
    db: AsyncSession,
    *,
    desde: str | None = None,
    hasta: str | None = None,
    tenant_id: str | None = None,
) -> ResultadoIntegridadCadena:
    """Recorre secuencialmente admin.staff_actions recalculando en Python los sellos SHA-256.

    Comprueba:
      1. Coincidencia estricta de cada sello almacenado con el hash recalculado.
      2. Continuidad criptográfica (prev_seal coincide con el seal anterior).
      3. Aislamiento opcional por cliente (tenant_id) y rango temporal (desde, hasta).
    """
    conds: list[str] = []
    params: dict[str, Any] = {
        "d": desde,
        "h": hasta,
        "tid": tenant_id,
    }
    if desde:
        conds.append("occurred_at >= CAST(CAST(:d AS text) AS timestamptz)")
    if hasta:
        conds.append("occurred_at < CAST(CAST(:h AS text) AS timestamptz)")
    if tenant_id:
        conds.append("tenant_id = :tid")

    where_clause = f"WHERE {' AND '.join(conds)}" if conds else ""
    filas = await todos(
        db,
        f"""
        SELECT id, occurred_at, occurred_at::text AS ts, staff_id, action,
               tenant_id, scope, reason, resource, endpoint,
               payload::text AS pl, prev_seal, seal
        FROM admin.staff_actions
        {where_clause}
        ORDER BY occurred_at, id
    """,
        params,
    )

    roturas: list[dict[str, Any]] = []
    expected_seal: str | None = None

    for r in filas:
        prev = r.get("prev_seal") or ""
        # Si es verificación de continuidad global (sin filtro de tenant), verificar enlace
        if tenant_id is None and expected_seal is not None and prev != expected_seal:
            roturas.append(
                {
                    "broken_at": r["occurred_at"],
                    "broken_id": r["id"],
                    "motivo": f"encadenamiento roto: se esperaba {expected_seal[:12]}",
                }
            )
            break

        sello_calculado = calcular_sello_staff_action(
            prev_seal=prev,
            occurred_at=r["ts"],
            staff_id=r["staff_id"],
            action=r["action"],
            endpoint=r["endpoint"],
            tenant_id=r.get("tenant_id"),
            scope=r.get("scope"),
            reason=r.get("reason"),
            resource=r.get("resource"),
            payload=r.get("pl") or "",
        )

        if r["seal"] != sello_calculado:
            roturas.append(
                {
                    "broken_at": r["occurred_at"],
                    "broken_id": r["id"],
                    "motivo": "sello no reproducible",
                }
            )
            break

        expected_seal = r["seal"]

    integro = len(roturas) == 0
    primer = roturas[0] if roturas else None
    return ResultadoIntegridadCadena(
        integra=integro,
        verificado=integro,
        roturas=roturas,
        total_roturas=len(roturas),
        primer_evento_roto=primer,
    )


def formatear_nombre_publico(nombre_completo: str | None) -> str:
    """Convierte el nombre completo del empleado en un identificador público seguro.

    Maneja limpiamente nombres de una sola palabra, cadenas vacías o valores None
    devolviendo 'Staff KalliCode' para proteger la privacidad y evitar excepciones.

    Ejemplos:
      - 'Laura Prieto' -> 'L. Prieto'
      - 'Laura Prieto González' -> 'L. Prieto González'
      - 'L. Prieto' -> 'L. Prieto'
      - 'Laura' -> 'Laura'
      - '' / '   ' / None -> 'Staff KalliCode'
    """
    if not nombre_completo:
        return "Staff KalliCode"
    limpio = nombre_completo.strip()
    if not limpio:
        return "Staff KalliCode"
    partes = limpio.split()
    if not partes:
        return "Staff KalliCode"
    if len(partes) == 1:
        return partes[0]
    inicial = partes[0][0].upper()
    resto = " ".join(partes[1:])
    if partes[0].endswith("."):
        return f"{partes[0].upper()} {resto}"
    return f"{inicial}. {resto}"


async def consultar_accesos_staff_para_portal(
    db: AsyncSession,
    *,
    tenant_id: str,
    desde: date,
    hasta: date,
    ticket_id: str | None = None,
    limit: int = 25,
    offset: int = 0,
) -> tuple[list[dict[str, Any]], int]:
    """Consulta las concesiones de acceso del personal sobre los datos del cliente (§11.6).

    Aplica aislamiento estricto por tenant_id, paginación, filtros de fecha y ticket_id,
    enmascaramiento del personal en el objeto actor y verificación forense SHA-256.
    """
    cond = [
        "g.tenant_id = :tid",
        "g.granted_at >= CAST(:d AS date)",
        "g.granted_at < CAST(:h AS date) + 1",
    ]
    params: dict[str, Any] = {
        "tid": tenant_id,
        "d": desde,
        "h": hasta,
        "lim": limit,
        "off": offset,
    }
    if ticket_id and ticket_id.strip():
        cond.append("(g.reference ILIKE :tid_pat OR g.reason ILIKE :tid_pat)")
        params["tid_pat"] = f"%{ticket_id.strip()}%"

    where = "WHERE " + " AND ".join(cond)

    total_row = await uno(
        db,
        f"SELECT count(*) AS n FROM admin.access_grants g {where}",
        params,
    )
    total = int(total_row["n"]) if total_row else 0

    filas = await todos(
        db,
        f"""
        SELECT g.id, g.scope AS alcance, g.reason AS motivo, g.reference AS referencia,
               g.granted_at AS concedido_en, g.expires_at AS caduca_en,
               g.reads AS accesos,
               s.full_name AS staff_nombre, s.role AS staff_rol
        FROM admin.access_grants g
        JOIN admin.staff s ON s.id = g.staff_id
        {where}
        ORDER BY g.granted_at DESC
        LIMIT :lim OFFSET :off
    """,
        params,
    )

    # Verificación de integridad criptográfica de la cadena en la ventana
    rupturas = await verificar_cadena(db, str(desde), str(hasta + timedelta(days=1)))
    integra = not rupturas

    items: list[dict[str, Any]] = []
    for f in filas:
        concedido = f["concedido_en"]
        caduca = f["caduca_en"]
        concedido_str = (
            concedido.isoformat().replace("+00:00", "Z")
            if hasattr(concedido, "isoformat")
            else str(concedido)
        )
        caduca_str = (
            caduca.isoformat().replace("+00:00", "Z")
            if hasattr(caduca, "isoformat")
            else str(caduca)
        )

        items.append(
            {
                "id": str(f["id"]),
                "actor": {
                    "nombre": formatear_nombre_publico(f.get("staff_nombre")),
                    "rol": str(f.get("staff_rol") or "staff_soporte"),
                },
                "motivo": str(f.get("motivo") or ""),
                "alcance": str(f.get("alcance") or "datos_negocio"),
                "concedido_en": concedido_str,
                "caduca_en": caduca_str,
                "accesos": int(f.get("accesos") or 0),
                "verificado": integra,
            }
        )

    return items, total


__all__ = [
    "Accion",
    "ResultadoIntegridadCadena",
    "calcular_sello_staff_action",
    "consultar_accesos_staff_para_portal",
    "formatear_nombre_publico",
    "recalcular_y_verificar_cadena",
    "registrar_accion",
    "registrar_accion_staff",
    "registrar_lectura",
    "verificar_cadena",
    "verificar_cadena_staff_actions",
]
