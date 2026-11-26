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
import ipaddress
import json
import re
from datetime import UTC, date, datetime, timedelta
from typing import Any, Literal

from kallicode_core.logging import log
from sqlalchemy.ext.asyncio import AsyncSession

from .db import todos, uno
from .metrics import registrar_accion_personal_metrica

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

_GENESIS_CENTRAL: str = "0" * 64

CLAVES_PROHIBIDAS_AUDITORIA: frozenset[str] = frozenset(
    {
        "codigo",
        "contenido_codigo",
        "source_code",
        "archivo",
        "file_content",
        "password",
        "password_hash",
        "totp_secret",
        "email_raw",
        "token",
        "refresh_token",
        "access_token",
        "secret",
        "private_key",
    }
)

_RE_EMAIL = re.compile(r"([a-zA-Z0-9_.+-])[a-zA-Z0-9_.+-]*@([a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+)")


def validar_payload_sin_fuga(payload: dict[str, Any] | None) -> None:
    """Rechaza claves sensibles prohibidas por la política no-fuga en auditoría."""
    if not payload:
        return

    def _recorrer(valor: Any, ruta: str) -> None:
        if isinstance(valor, dict):
            for k, v in valor.items():
                clave = str(k)
                clave_norm = clave.lower()
                if clave_norm in CLAVES_PROHIBIDAS_AUDITORIA:
                    raise ValueError(
                        f"clave sensible prohibida en payload de auditoría: {ruta}{clave}"
                    )
                _recorrer(v, f"{ruta}{clave}.")
        elif isinstance(valor, list):
            for idx, item in enumerate(valor):
                _recorrer(item, f"{ruta}[{idx}].")

    _recorrer(payload, "")


def _enmascarar_emails_en_valor(valor: Any) -> Any:
    if isinstance(valor, str):
        return _RE_EMAIL.sub(r"\1***@\2", valor)
    if isinstance(valor, dict):
        return {
            str(k): _enmascarar_emails_en_valor(v)
            for k, v in valor.items()
            if str(k).lower() not in CLAVES_PROHIBIDAS_AUDITORIA
        }
    if isinstance(valor, list):
        return [_enmascarar_emails_en_valor(v) for v in valor]
    return valor


def sanitizar_metadata_auditoria(payload: dict[str, Any] | None) -> dict[str, Any]:
    """Elimina claves prohibidas y enmascara posibles emails antes de sellar."""
    if not payload:
        return {}
    resultado = _enmascarar_emails_en_valor(payload)
    return resultado if isinstance(resultado, dict) else {}


def _normalizar_occurred_at_utc(occurred_at: datetime | str | None) -> str:
    if occurred_at is None:
        dt = datetime.now(UTC)
    elif isinstance(occurred_at, datetime):
        dt = (
            occurred_at.astimezone(UTC)
            if occurred_at.tzinfo
            else occurred_at.replace(tzinfo=UTC)
        )
    else:
        raw = str(occurred_at).strip()
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        dt = datetime.fromisoformat(raw)
        dt = dt.astimezone(UTC) if dt.tzinfo else dt.replace(tzinfo=UTC)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def construir_evento_canonico_staff(
    *,
    tenant_id: str,
    staff_id: str,
    staff_role: str,
    action: str,
    endpoint: str,
    reason: str | None = None,
    resource: str | None = None,
    scope: str | None = None,
    grant_id: str | None = None,
    request_id: str | None = None,
    occurred_at: datetime | str | None = None,
    staff_action_id: int | None = None,
    staff_action_seal: str | None = None,
    metadata: dict[str, Any] | None = None,
    actor_typ: str = "staff",
    strict_no_leak: bool = True,
) -> dict[str, Any]:
    """Construye la representación canónica normalizada de un acceso de personal."""
    if actor_typ != "staff":
        raise ValueError(f"actor.typ inválido para evento de personal: {actor_typ!r}")
    if not staff_id or not staff_id.strip():
        raise ValueError("staff_id es obligatorio en el evento canónico de auditoría")
    if not staff_role or not staff_role.strip():
        raise ValueError("staff_role es obligatorio en el evento canónico de auditoría")
    if not tenant_id or not tenant_id.strip():
        raise ValueError("tenant_id es obligatorio en la cadena central del cliente")
    if action in _EXIGEN_TENANT and (not reason or not reason.strip()):
        raise ValueError(f"la acción {action} exige reason declarado para auditar acceso")

    if strict_no_leak:
        validar_payload_sin_fuga(metadata)
    metadata_segura = sanitizar_metadata_auditoria(metadata)

    recurso_efectivo = (
        resource.strip() if resource and resource.strip() else f"customer:{tenant_id}"
    )
    return {
        "schema_version": "1.0",
        "tenant_id": tenant_id,
        "occurred_at": _normalizar_occurred_at_utc(occurred_at),
        "actor": {
            "typ": "staff",
            "staff_id": staff_id,
            "rol": staff_role,
        },
        "action": action,
        "scope": scope,
        "grant_id": grant_id,
        "reason": reason,
        "resource": recurso_efectivo,
        "endpoint": endpoint,
        "request_id": request_id,
        "staff_action_id": staff_action_id,
        "staff_action_seal": staff_action_seal,
        "metadata": metadata_segura,
    }


def serializar_evento_canonico(evento: dict[str, Any]) -> str:
    """Serializa un evento canónico en JSON determinista con claves ordenadas."""
    return json.dumps(evento, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def calcular_sello_cadena_central(prev_seal: str, evento: dict[str, Any] | str) -> str:
    """Calcula SHA-256(sello_n-1 || canonico(evento_n)) en formato hex de 64 chars."""
    canonico = evento if isinstance(evento, str) else serializar_evento_canonico(evento)
    return hashlib.sha256((prev_seal + canonico).encode("utf-8")).hexdigest()


def _ip_postgres_valida(ip: str | None) -> str | None:
    if not ip:
        return None
    candidata = ip.split(",")[0].strip()
    try:
        return str(ipaddress.ip_address(candidata))
    except ValueError:
        return None


def _construir_resumen_publico(*, staff_role: str, action: str, reason: str | None) -> str:
    motivo = (reason or "").strip() or action
    return f"Acceso de personal ({staff_role}): {motivo}"


async def _esquema_auditoria_central_disponible(db: AsyncSession) -> tuple[bool, bool, bool]:
    """Comprueba sobre `db` la presencia de `audit.audit_events` y `audit.chain_heads`."""
    fila = await uno(
        db,
        """
        SELECT
            to_regclass('audit.audit_events') IS NOT NULL AS tiene_eventos,
            to_regclass('audit.chain_heads') IS NOT NULL AS tiene_cabezas,
            EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_schema = 'audit'
                  AND table_name = 'audit_events'
                  AND column_name = 'ip'
            ) AS tiene_procedencia,
            to_regprocedure('audit.verify_chain(text,timestamptz,timestamptz)') IS NOT NULL
                AS tiene_verify_chain
    """,
    )
    if not fila:
        return False, False, False
    disponible = bool(fila.get("tiene_eventos")) and bool(fila.get("tiene_cabezas"))
    return disponible, bool(fila.get("tiene_procedencia")), bool(fila.get("tiene_verify_chain"))


async def _conectar_evento_a_cadena_central(
    db: AsyncSession,
    *,
    tenant_id: str,
    staff_id: str,
    staff_role: str,
    action: str,
    endpoint: str,
    staff_action_id: int | None,
    staff_action_seal: str,
    occurred_at: datetime | str | None = None,
    grant_id: str | None = None,
    scope: str | None = None,
    reason: str | None = None,
    resource: str | None = None,
    ip: str | None = None,
    user_agent: str | None = None,
    request_id: str | None = None,
    payload: dict[str, Any] | None = None,
    migrado: bool = False,
) -> str | None:
    """Conecta el evento de personal a `audit.audit_events` reutilizando la sesión `db`."""
    disponible, tiene_procedencia, _ = await _esquema_auditoria_central_disponible(db)
    if not disponible:
        return None

    # Alinear el contexto de tenant en la transacción para compatibilidad RLS / triggers
    ctx_row = await uno(db, "SELECT current_setting('app.tenant_id', true) AS prev_tid")
    prev_ctx_tid = (ctx_row or {}).get("prev_tid") or ""
    await uno(db, "SELECT set_config('app.tenant_id', :tid, true)", {"tid": tenant_id})
    try:
        await uno(
            db,
            """
            INSERT INTO audit.chain_heads (tenant_id) VALUES (:tid)
            ON CONFLICT (tenant_id) DO NOTHING
            RETURNING tenant_id
        """,
            {"tid": tenant_id},
        )
        cabeza = await uno(
            db,
            "SELECT ultimo_sello FROM audit.chain_heads WHERE tenant_id = :tid FOR UPDATE",
            {"tid": tenant_id},
        )
        prev_central_seal = (
            str(cabeza["ultimo_sello"])
            if cabeza and cabeza.get("ultimo_sello")
            else _GENESIS_CENTRAL
        )

        motivo_efectivo = (reason or "").strip() or f"Acción de personal ({action})"
        evento_canonico = construir_evento_canonico_staff(
            tenant_id=tenant_id,
            staff_id=staff_id,
            staff_role=staff_role,
            action=action,
            endpoint=endpoint,
            reason=motivo_efectivo,
            resource=resource,
            scope=scope,
            grant_id=grant_id,
            request_id=request_id,
            occurred_at=occurred_at,
            staff_action_id=staff_action_id,
            staff_action_seal=staff_action_seal,
            metadata=payload,
            strict_no_leak=False,
        )
        canonical_seal = calcular_sello_cadena_central(prev_central_seal, evento_canonico)
        datos_central: dict[str, Any] = dict(evento_canonico)
        datos_central["canonical_prev_seal"] = prev_central_seal
        datos_central["canonical_seal"] = canonical_seal
        if migrado:
            datos_central["migrated_from_staff_actions"] = True

        resumen = _construir_resumen_publico(
            staff_role=staff_role, action=action, reason=motivo_efectivo
        )
        evento_codigo = action if action.startswith("staff_") else f"staff_{action}"

        if tiene_procedencia:
            insertado = await uno(
                db,
                """
                INSERT INTO audit.audit_events
                    (tenant_id, actor_tipo, actor_id, evento, resumen, datos,
                     ip, user_agent, request_id, sello_previo, sello)
                VALUES (:tid, 'staff', :sid, :ev, :res, CAST(:dat AS jsonb),
                        CAST(:ip AS inet), :ua, :rq, :prev, :seal)
                RETURNING sello
            """,
                {
                    "tid": tenant_id,
                    "sid": staff_id,
                    "ev": evento_codigo,
                    "res": resumen,
                    "dat": json.dumps(datos_central, sort_keys=True, ensure_ascii=False),
                    "ip": _ip_postgres_valida(ip),
                    "ua": user_agent,
                    "rq": request_id,
                    "prev": prev_central_seal,
                    "seal": canonical_seal,
                },
            )
        else:
            insertado = await uno(
                db,
                """
                INSERT INTO audit.audit_events
                    (tenant_id, actor_tipo, actor_id, evento, resumen, datos,
                     sello_previo, sello)
                VALUES (:tid, 'staff', :sid, :ev, :res, CAST(:dat AS jsonb),
                        :prev, :seal)
                RETURNING sello
            """,
                {
                    "tid": tenant_id,
                    "sid": staff_id,
                    "ev": evento_codigo,
                    "res": resumen,
                    "dat": json.dumps(datos_central, sort_keys=True, ensure_ascii=False),
                    "prev": prev_central_seal,
                    "seal": canonical_seal,
                },
            )
        return (
            str(insertado["sello"]) if insertado and insertado.get("sello") else canonical_seal
        )
    finally:
        await uno(db, "SELECT set_config('app.tenant_id', :tid, true)", {"tid": prev_ctx_tid})


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
    validar_payload_sin_fuga(payload)

    fila = await uno(
        db,
        """
        INSERT INTO admin.staff_actions
            (staff_id, staff_email, staff_role, action, tenant_id, grant_id, scope, reason,
             resource, endpoint, ip, user_agent, request_id, payload,
             prev_seal, seal)
        VALUES (:sid, :sem, :rol, :act, :tid, :gid, :sc, :rz, :res, :ep, :ip, :ua,
                :rq, CAST(:pl AS jsonb), '', '')
        RETURNING id, occurred_at, seal
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
    registrar_accion_personal_metrica(staff_role, action)

    if tenant_id:
        await _conectar_evento_a_cadena_central(
            db,
            tenant_id=tenant_id,
            staff_id=staff_id,
            staff_role=staff_role,
            action=action,
            endpoint=endpoint,
            staff_action_id=int(fila["id"]) if fila.get("id") is not None else None,
            staff_action_seal=sello,
            occurred_at=fila.get("occurred_at"),
            grant_id=grant_id,
            scope=scope,
            reason=reason,
            resource=resource,
            ip=ip,
            user_agent=user_agent,
            request_id=request_id,
            payload=payload,
        )

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
    recurso_efectivo = resource if resource and resource.strip() else f"customer:{tenant_id}"
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
        resource=recurso_efectivo,
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
    central = await verificar_cadena_central_tenant(db, tenant_id)
    integra = (not rupturas) and central.integra

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


_WRAPPER_CLAVES_CANONICAS: frozenset[str] = frozenset(
    {
        "canonical_prev_seal",
        "canonical_seal",
        "migrated_from_staff_actions",
    }
)


def _ordenar_cadena_central(
    eventos: list[dict[str, Any]],
    *,
    ancla_prev: str,
    desde_ventana: bool,
) -> list[dict[str, Any]]:
    if desde_ventana or not eventos:
        return eventos

    por_prev: dict[str, list[dict[str, Any]]] = {}
    for ev in eventos:
        por_prev.setdefault(str(ev.get("sello_previo") or ""), []).append(ev)

    ordenados: list[dict[str, Any]] = []
    vistos: set[int] = set()
    cursor = ancla_prev
    while cursor in por_prev:
        candidatos = por_prev[cursor]
        if len(candidatos) != 1:
            break
        ev = candidatos[0]
        if id(ev) in vistos:
            break
        vistos.add(id(ev))
        ordenados.append(ev)
        cursor = str(ev.get("sello") or "")

    for ev in eventos:
        if id(ev) not in vistos:
            ordenados.append(ev)
    return ordenados


def verificar_eventos_centrales_en_memoria(
    eventos: list[dict[str, Any]],
    chain_head: dict[str, Any] | None = None,
    *,
    desde_ventana: bool = False,
) -> ResultadoIntegridadCadena:
    """Verifica determinísticamente eventos centrales de un tenant y su chain_head."""
    roturas: list[dict[str, Any]] = []
    ancla_prev = (
        str(chain_head["ultimo_sello_descartado"])
        if chain_head and chain_head.get("ultimo_sello_descartado")
        else _GENESIS_CENTRAL
    )
    descartados = int(chain_head.get("eventos_descartados") or 0) if chain_head else 0
    secuencia = _ordenar_cadena_central(
        eventos,
        ancla_prev=ancla_prev,
        desde_ventana=desde_ventana,
    )

    esperado_prev: str | None = None if desde_ventana else ancla_prev
    vistos_prev: set[str] = set()

    for ev in secuencia:
        prev = str(ev.get("sello_previo") or "")
        if prev in vistos_prev:
            roturas.append(
                {
                    "broken_at": ev.get("creado_en"),
                    "broken_id": ev.get("id"),
                    "motivo": f"bifurcación de sello_previo duplicado ({prev[:12]})",
                }
            )
            break
        vistos_prev.add(prev)

        if esperado_prev is not None and prev != esperado_prev:
            roturas.append(
                {
                    "broken_at": ev.get("creado_en"),
                    "broken_id": ev.get("id"),
                    "motivo": f"encadenamiento central roto: se esperaba {esperado_prev[:12]}",
                }
            )
            break

        datos_raw = ev.get("datos")
        datos: dict[str, Any] | None
        if isinstance(datos_raw, str):
            datos = json.loads(datos_raw) if datos_raw else None
        elif isinstance(datos_raw, dict):
            datos = datos_raw
        else:
            datos = None

        if (
            ev.get("actor_tipo") == "staff"
            and isinstance(datos, dict)
            and "canonical_seal" in datos
        ):
            actor = datos.get("actor")
            if not isinstance(actor, dict) or actor.get("typ") != "staff":
                roturas.append(
                    {
                        "broken_at": ev.get("creado_en"),
                        "broken_id": ev.get("id"),
                        "motivo": "evento de staff sin actor.typ='staff' válido",
                    }
                )
                break
            if datos.get("canonical_prev_seal") != prev:
                roturas.append(
                    {
                        "broken_at": ev.get("creado_en"),
                        "broken_id": ev.get("id"),
                        "motivo": "canonical_prev_seal inconsistente con sello_previo real",
                    }
                )
                break
            evento_canonico = {
                k: v for k, v in datos.items() if k not in _WRAPPER_CLAVES_CANONICAS
            }
            sello_recalculado = calcular_sello_cadena_central(prev, evento_canonico)
            if str(datos.get("canonical_seal") or "") != sello_recalculado:
                roturas.append(
                    {
                        "broken_at": ev.get("creado_en"),
                        "broken_id": ev.get("id"),
                        "motivo": "sello canónico de staff no reproducible",
                    }
                )
                break

        esperado_prev = str(ev.get("sello") or "")

    if not roturas and chain_head is not None and not desde_ventana:
        ultimo_head = str(chain_head.get("ultimo_sello") or "")
        total_head = int(chain_head.get("eventos") or 0)
        esperado_ultimo: str = (esperado_prev or "") if eventos else ancla_prev
        if total_head != len(eventos) + descartados:
            roturas.append(
                {
                    "broken_at": None,
                    "broken_id": None,
                    "motivo": (
                        f"chain_heads.eventos ({total_head}) difiere de los eventos "
                        f"observados ({len(eventos) + descartados})"
                    ),
                }
            )
        elif ultimo_head != esperado_ultimo:
            roturas.append(
                {
                    "broken_at": None,
                    "broken_id": None,
                    "motivo": (
                        f"chain_heads.ultimo_sello ({ultimo_head[:12]}) difiere "
                        f"del último sello real ({esperado_ultimo[:12]})"
                    ),
                }
            )

    integro = len(roturas) == 0
    return ResultadoIntegridadCadena(
        integra=integro,
        verificado=integro,
        roturas=roturas,
        total_roturas=len(roturas),
        primer_evento_roto=roturas[0] if roturas else None,
    )


async def verificar_cadena_central_tenant(
    db: AsyncSession,
    tenant_id: str,
    *,
    desde: str | None = None,
    hasta: str | None = None,
) -> ResultadoIntegridadCadena:
    """Verifica la cadena central (`audit.audit_events` + `audit.chain_heads`) de un tenant."""
    disponible, _, tiene_verify = await _esquema_auditoria_central_disponible(db)
    if not disponible:
        return ResultadoIntegridadCadena(
            integra=True,
            verificado=True,
            roturas=[],
            total_roturas=0,
            primer_evento_roto=None,
        )

    roturas_sql: list[dict[str, Any]] = []
    if tiene_verify:
        verif = await uno(
            db,
            """
            SELECT integra, primer_evento_roto
            FROM audit.verify_chain(
                :tid,
                CAST(CAST(:d AS text) AS timestamptz),
                CAST(CAST(:h AS text) AS timestamptz)
            )
        """,
            {"tid": tenant_id, "d": desde, "h": hasta},
        )
        if verif is not None and not bool(verif.get("integra")):
            roturas_sql.append(
                {
                    "broken_at": None,
                    "broken_id": verif.get("primer_evento_roto"),
                    "motivo": "sello central de audit.verify_chain inválido",
                }
            )

    conds = ["tenant_id = :tid"]
    params: dict[str, Any] = {"tid": tenant_id, "d": desde, "h": hasta}
    if desde:
        conds.append("creado_en >= CAST(CAST(:d AS text) AS timestamptz)")
    if hasta:
        conds.append("creado_en < CAST(CAST(:h AS text) AS timestamptz)")

    eventos = await todos(
        db,
        f"""
        SELECT id, tenant_id, actor_tipo, actor_id, evento, resumen,
               datos, sello_previo, sello, creado_en
        FROM audit.audit_events
        WHERE {' AND '.join(conds)}
        ORDER BY creado_en ASC, id ASC
    """,
        params,
    )

    cabeza = await uno(
        db,
        "SELECT tenant_id, ultimo_sello, eventos FROM audit.chain_heads WHERE tenant_id = :tid",
        {"tid": tenant_id},
    )
    if cabeza is not None:
        ancla = await uno(
            db,
            """
            SELECT to_regclass('audit.chain_anchors') IS NOT NULL AS tiene_anchors
        """,
        )
        if ancla and ancla.get("tiene_anchors"):
            datos_anc = await uno(
                db,
                """
                SELECT eventos_descartados, ultimo_sello_descartado
                FROM audit.chain_anchors
                WHERE tenant_id = :tid
            """,
                {"tid": tenant_id},
            )
            if datos_anc:
                cabeza["eventos_descartados"] = datos_anc.get("eventos_descartados") or 0
                cabeza["ultimo_sello_descartado"] = datos_anc.get("ultimo_sello_descartado")
    elif eventos and not desde and not hasta:
        roturas_sql.append(
            {
                "broken_at": None,
                "broken_id": eventos[0].get("id"),
                "motivo": "eventos en audit.audit_events sin entrada en audit.chain_heads",
            }
        )

    res_py = verificar_eventos_centrales_en_memoria(
        eventos,
        cabeza,
        desde_ventana=bool(desde or hasta),
    )
    todas_roturas = [*roturas_sql, *res_py.roturas]
    integro = len(todas_roturas) == 0
    return ResultadoIntegridadCadena(
        integra=integro,
        verificado=integro,
        roturas=todas_roturas,
        total_roturas=len(todas_roturas),
        primer_evento_roto=todas_roturas[0] if todas_roturas else None,
    )


async def migrar_historico_staff_a_cadena_central(
    db: AsyncSession,
    *,
    tenant_id: str | None = None,
) -> dict[str, int]:
    """Migra de forma idempotente `admin.staff_actions` hacia `audit.audit_events`.

    Reutiliza la sesión `db` proporcionada por el llamador y nunca ejecuta UPDATE ni DELETE
    sobre `admin.staff_actions` (estrictamente append-only).
    """
    disponible, _, _ = await _esquema_auditoria_central_disponible(db)
    if not disponible:
        return {"procesados": 0, "migrados": 0, "omitidos": 0}

    filas = await todos(
        db,
        """
        SELECT sa.id, sa.occurred_at, sa.staff_id, sa.staff_role, sa.action,
               sa.tenant_id, sa.grant_id, sa.scope, sa.reason, sa.resource,
               sa.endpoint, sa.ip, sa.user_agent, sa.request_id, sa.payload, sa.seal
        FROM admin.staff_actions sa
        WHERE sa.tenant_id IS NOT NULL
          AND (CAST(:tid AS text) IS NULL OR sa.tenant_id = :tid)
        ORDER BY sa.occurred_at ASC, sa.id ASC
    """,
        {"tid": tenant_id},
    )

    existentes_rows = await todos(
        db,
        """
        SELECT tenant_id,
               datos->>'staff_action_id' AS sa_id,
               datos->>'staff_action_seal' AS sa_seal
        FROM audit.audit_events
        WHERE actor_tipo = 'staff'
          AND (CAST(:tid AS text) IS NULL OR tenant_id = :tid)
          AND datos ? 'staff_action_id'
    """,
        {"tid": tenant_id},
    )
    ya_migrados: set[tuple[str, str, str]] = {
        (
            str(r["tenant_id"]),
            str(r.get("sa_id") or ""),
            str(r.get("sa_seal") or ""),
        )
        for r in existentes_rows
    }

    migrados = 0
    omitidos = 0
    for f in filas:
        clave = (str(f["tenant_id"]), str(f["id"]), str(f["seal"]))
        if clave in ya_migrados:
            omitidos += 1
            continue

        payload_raw = f.get("payload")
        if isinstance(payload_raw, str):
            payload_dict: dict[str, Any] | None = (
                json.loads(payload_raw) if payload_raw else None
            )
        elif isinstance(payload_raw, dict):
            payload_dict = payload_raw
        else:
            payload_dict = None

        await _conectar_evento_a_cadena_central(
            db,
            tenant_id=str(f["tenant_id"]),
            staff_id=str(f["staff_id"]),
            staff_role=str(f["staff_role"]),
            action=str(f["action"]),
            endpoint=str(f["endpoint"]),
            staff_action_id=int(f["id"]),
            staff_action_seal=str(f["seal"]),
            occurred_at=f.get("occurred_at"),
            grant_id=f.get("grant_id"),
            scope=f.get("scope"),
            reason=f.get("reason"),
            resource=f.get("resource"),
            ip=f.get("ip"),
            user_agent=f.get("user_agent"),
            request_id=f.get("request_id"),
            payload=payload_dict,
            migrado=True,
        )
        ya_migrados.add(clave)
        migrados += 1

    return {
        "procesados": len(filas),
        "migrados": migrados,
        "omitidos": omitidos,
    }


__all__ = [
    "CLAVES_PROHIBIDAS_AUDITORIA",
    "Accion",
    "ResultadoIntegridadCadena",
    "calcular_sello_cadena_central",
    "calcular_sello_staff_action",
    "construir_evento_canonico_staff",
    "consultar_accesos_staff_para_portal",
    "formatear_nombre_publico",
    "migrar_historico_staff_a_cadena_central",
    "recalcular_y_verificar_cadena",
    "registrar_accion",
    "registrar_accion_staff",
    "registrar_lectura",
    "sanitizar_metadata_auditoria",
    "serializar_evento_canonico",
    "validar_payload_sin_fuga",
    "verificar_cadena",
    "verificar_cadena_central_tenant",
    "verificar_cadena_staff_actions",
    "verificar_eventos_centrales_en_memoria",
]
