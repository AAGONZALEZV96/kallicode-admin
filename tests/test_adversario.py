"""Suite de pruebas adversarias de seguridad cross-tenant (KC-ADM-B6-02).

Ejecuta escenarios de hacking ético interno conjuntamente con los criterios del
Equipo 5 (Testing & Seguridad) sobre PostgreSQL 16 con RLS real, validando:
  - ADV-01: Manipulación de filtros y rutas cross-tenant (aislamiento entre tenants).
  - ADV-02: Inyección SQL y manipulación de ordenamiento/paginación/bloques.
  - ADV-03: Bypass de enmascaramiento con concesión expirada o revocada.
  - ADV-04: Bypass con concesión perteneciente a otro empleado o alcance inferior.
  - ADV-05: Abuso en solicitud de concesiones (motivos genéricos, duración, concurrencia).
  - ADV-06: Escritura cruzada DML/DDL con kallicode_admin_ro y restricción RLS en audit.
  - ADV-07: Confusión de identidad JWT (token cliente, sin MFA, inactivo) y escalada de rol.
  - ADV-08: Trazabilidad e inmutabilidad de admin.staff_actions y audit.audit_events.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
import pytest
from admin_api.audit import verificar_cadena_central_tenant
from admin_api.security import _claves, emitir_tokens_staff
from kallicode_core.ids import nuevo
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, InternalError, ProgrammingError

pytestmark = pytest.mark.integracion

TENANT_A = "org_acme"
TENANT_B = "org_globex"
MOTIVO_CASO = "Investigación forense autorizada por cliente en ticket SUP-01 / KC-9021"


def _headers_staff(staff_id: str, rol: str, mfa_offset_min: int = -1) -> dict[str, str]:
    """Emite un JWT real de staff con marca temporal MFA configurable."""
    mfa_at = datetime.now(UTC) + timedelta(minutes=mfa_offset_min)
    token = emitir_tokens_staff(staff_id, rol, mfa_at)
    return {"Authorization": f"Bearer {token}"}


# =============================================================================
# ADV-01: Manipulación de filtros y rutas cross-tenant
# =============================================================================
async def test_adv01_concesion_en_un_tenant_no_desenmascara_otro_tenant(
    cliente: Any,
    como: Any,
    sin_limite: None,
    dos_clientes: list[str],
    db: Any,
) -> None:
    """Con concesión activa en TENANT_A, TENANT_B sigue enmascarado en negocio y SLA."""
    ciclo_actual = datetime.now(UTC).strftime("%Y-%m")
    job_b = f"job_adv01_{nuevo('jb')}"
    ticket_b = f"tk_adv01_{nuevo('tk')}"

    # Sembrar un tramo de reloj SLA para TENANT_B en el ciclo actual
    await db.execute(
        text(
            """
            INSERT INTO admin.sla_clock_segments (
                tenant_id, job_id, ticket_id, etapa, inicio, fin, computa, causa_pausa
            )
            VALUES (
                :tenant, :jid, :tid, 'build',
                now() - interval '3 hours', now() - interval '1 hour',
                true, NULL
            )
            """
        ),
        {"jid": job_b, "tid": ticket_b, "tenant": TENANT_B},
    )
    await db.execute(
        text(
            """
            INSERT INTO admin.aggregate_state (
                agregado, refreshed_at, duration_ms, rows_total, status
            )
            VALUES ('sla_cases', now(), 10, 1, 'ok')
            ON CONFLICT (agregado) DO UPDATE SET refreshed_at = now(), status = 'ok'
            """
        )
    )
    await db.execute(
        text(
            """
            INSERT INTO admin.access_grants (
                id, staff_id, tenant_id, scope, reason, granted_at, expires_at
            )
            VALUES (
                'gr_org_acme', 'st_prueba', :tid, 'expediente', :motivo,
                now(), now() + interval '1 hour'
            )
            ON CONFLICT (id) DO UPDATE
                SET revoked_at = NULL,
                    expires_at = now() + interval '1 hour'
            """
        ),
        {"tid": TENANT_A, "motivo": MOTIVO_CASO},
    )
    await db.commit()

    try:
        # Empleado con concesión SOLO sobre TENANT_A
        como("staff_admin", {TENANT_A: ["datos_negocio", "expediente"]})

        # 1) Listado general de clientes: TENANT_A en claro, TENANT_B enmascarado
        r_list = await cliente.get("/admin/v1/business/customers")
        assert r_list.status_code == 200
        cuerpo_list = r_list.json()
        assert cuerpo_list["alguna_enmascarada"] is True
        por_tenant = {f["tenant_id"]: f for f in cuerpo_list["items"]}
        assert por_tenant[TENANT_A]["razon_social"] == "Acme Logística S.L."
        assert por_tenant[TENANT_A]["enmascarado"] is False
        assert por_tenant[TENANT_B]["razon_social"] == "G•••• S.A."
        assert por_tenant[TENANT_B]["enmascarado"] is True

        # 2) Acceso directo por ruta a CustomerDetail de TENANT_B
        r_ficha_b = await cliente.get(f"/admin/v1/business/customers/{TENANT_B}")
        assert r_ficha_b.status_code == 200
        ficha_b = r_ficha_b.json()
        assert ficha_b["razon_social"] == "G•••• S.A."
        assert "razon_social" in ficha_b["enmascarado"]

        # 3) Listado de suscripciones: TENANT_B permanece enmascarado
        r_subs = await cliente.get("/admin/v1/business/subscriptions")
        assert r_subs.status_code == 200
        por_sub = {f["tenant_id"]: f for f in r_subs.json()["items"]}
        assert por_sub[TENANT_A]["razon_social"] == "Acme Logística S.L."
        assert por_sub[TENANT_B]["razon_social"] == "G•••• S.A."
        assert por_sub[TENANT_B]["enmascarado"] is True

        # 4) /ops/sla y /ops/sla/cases/{job_id} para TENANT_B: tenant_id enmascarado
        r_sla = await cliente.get(
            "/admin/v1/ops/sla",
            params={"ciclo": ciclo_actual, "tenant_id": TENANT_B},
        )
        assert r_sla.status_code == 200
        items_sla = r_sla.json()["items"]
        assert items_sla, "El resumen SLA de TENANT_B debe figurar pero enmascarado"
        assert items_sla[0]["tenant_id"] == "o••••"
        assert items_sla[0]["razon_social"] == "G•••• S.A."

        r_case = await cliente.get(f"/admin/v1/ops/sla/cases/{job_b}")
        assert r_case.status_code == 200
        case_b = r_case.json()
        assert case_b["tenant_id"] == "o••••"
        assert "tenant_id" in case_b["enmascarado"]
    finally:
        await db.execute(
            text("DELETE FROM admin.sla_clock_segments WHERE job_id = :jid"),
            {"jid": job_b},
        )
        await db.commit()


# =============================================================================
# ADV-02: Inyección SQL y manipulación de paginación, ordenamiento y bloques
# =============================================================================
@pytest.mark.parametrize(
    ("ruta", "params", "codigo_esperado"),
    [
        (
            "/admin/v1/business/customers",
            {"sort": "razon_social; DROP TABLE core.organizations--"},
            422,
        ),
        (
            "/admin/v1/business/customers",
            {"sort": "columna_inyeccion_sql-asc"},
            422,
        ),
        (
            "/admin/v1/business/customers",
            {"page_size": "50000"},
            422,
        ),
        (
            f"/admin/v1/business/customers/{TENANT_A}",
            {"incluir": "usuarios,codigo_fuente_secreto"},
            422,
        ),
        (
            "/admin/v1/ops/sla",
            {"ciclo": "2026-11' OR '1'='1"},
            422,
        ),
    ],
)
async def test_adv02_inyeccion_en_orden_paginacion_y_bloques_es_rechazada(
    cliente: Any,
    como: Any,
    sin_limite: None,
    dos_clientes: list[str],
    ruta: str,
    params: dict[str, str],
    codigo_esperado: int,
) -> None:
    """Las allowlists y validadores rechazan payloads de inyección con 422 sin fugas SQL."""
    como("staff_admin")
    resp = await cliente.get(ruta, params=params)
    assert resp.status_code == codigo_esperado
    texto = resp.text.lower()
    assert "select " not in texto
    assert "traceback" not in texto
    assert "sqlalchemy" not in texto


async def test_adv02_busqueda_q_con_payload_sqli_no_filtra_ni_rompe(
    cliente: Any,
    como: Any,
    sin_limite: None,
    dos_clientes: list[str],
) -> None:
    """Búsqueda por nombre sin concesión da 403 y payload SQLi con prefijo org_ da 0 filas."""
    como("staff_admin")
    # 1) Búsqueda libre (no empieza por org_) sin concesión activa se rechaza con 403
    r_sin_grant = await cliente.get(
        "/admin/v1/business/customers",
        params={"q": "' OR 1=1 UNION SELECT id, email FROM core.users --"},
    )
    assert r_sin_grant.status_code == 403

    # 2) Payload SQLi camuflado con prefijo org_ se parametriza como literal y devuelve 0 filas
    r_org = await cliente.get(
        "/admin/v1/business/customers",
        params={"q": "org_' OR 1=1 UNION SELECT id, email FROM core.users --"},
    )
    assert r_org.status_code == 200
    cuerpo = r_org.json()
    assert cuerpo["items"] == []
    assert cuerpo["total"] == 0


# =============================================================================
# ADV-03: Bypass de enmascaramiento con concesión expirada o revocada
# =============================================================================
async def test_adv03_concesion_expirada_o_revocada_no_desenmascara_datos(
    cliente: Any,
    dos_clientes: list[str],
    staff_factory: Any,
    db: Any,
) -> None:
    """Concesiones con expires_at <= now() o revoked_at != NULL jamás revelan PII."""
    emp = await staff_factory("staff_soporte")
    sid = emp["id"]

    # Insertar una concesión ya expirada y otra revocada para TENANT_A
    await db.execute(
        text(
            """
            INSERT INTO admin.access_grants (
                id, staff_id, tenant_id, scope, reason,
                granted_at, expires_at, revoked_at, revoked_by, revoked_reason
            )
            VALUES
            (
                :g_exp, :sid, :tid, 'datos_negocio', :motivo,
                now() - interval '3 hours', now() - interval '5 minutes',
                NULL, NULL, NULL
            ),
            (
                :g_rev, :sid, :tid, 'expediente', :motivo,
                now() - interval '1 hour', now() + interval '2 hours',
                now() - interval '2 minutes', :sid, 'Revocada antes de consulta'
            )
            """
        ),
        {
            "g_exp": nuevo("gr"),
            "g_rev": nuevo("gr"),
            "sid": sid,
            "tid": TENANT_A,
            "motivo": MOTIVO_CASO,
        },
    )
    await db.commit()

    headers = _headers_staff(sid, "staff_soporte")
    r_ficha = await cliente.get(
        f"/admin/v1/business/customers/{TENANT_A}",
        headers=headers,
    )
    assert r_ficha.status_code == 200
    ficha = r_ficha.json()
    assert ficha["razon_social"] == "A•••• S.L."
    assert "razon_social" in ficha["enmascarado"]


# =============================================================================
# ADV-04: Bypass con concesión de otro empleado o alcance insuficiente
# =============================================================================
async def test_adv04_concesion_de_otro_empleado_no_es_transferible(
    cliente: Any,
    dos_clientes: list[str],
    staff_factory: Any,
    db: Any,
) -> None:
    """Un empleado no puede aprovechar el grant_id activo de otro compañero."""
    titular = await staff_factory("staff_negocio")
    atacante = await staff_factory("staff_negocio")

    await db.execute(
        text(
            """
            INSERT INTO admin.access_grants (
                id, staff_id, tenant_id, scope, reason, granted_at, expires_at
            )
            VALUES (
                :gid, :sid, :tid, 'datos_negocio', :motivo,
                now(), now() + interval '1 hour'
            )
            """
        ),
        {
            "gid": nuevo("gr"),
            "sid": titular["id"],
            "tid": TENANT_A,
            "motivo": MOTIVO_CASO,
        },
    )
    await db.commit()

    # El titular ve TENANT_A desenmascarado
    r_titular = await cliente.get(
        f"/admin/v1/business/customers/{TENANT_A}",
        headers=_headers_staff(titular["id"], "staff_negocio"),
    )
    assert r_titular.status_code == 200
    assert r_titular.json()["razon_social"] == "Acme Logística S.L."

    # El atacante sigue viendo TENANT_A enmascarado
    r_atacante = await cliente.get(
        f"/admin/v1/business/customers/{TENANT_A}",
        headers=_headers_staff(atacante["id"], "staff_negocio"),
    )
    assert r_atacante.status_code == 200
    assert r_atacante.json()["razon_social"] == "A•••• S.L."

    # Y si el atacante intenta exportar un informe con PII para TENANT_A, recibe 403
    r_rep = await cliente.post(
        "/admin/v1/business/reports",
        headers=_headers_staff(atacante["id"], "staff_negocio"),
        json={
            "tipo": "consumo",
            "formato": "csv",
            "desde": "2026-10-01",
            "hasta": "2026-11-25",
            "tenant_id": TENANT_A,
            "incluir_identificables": True,
        },
    )
    assert r_rep.status_code == 403


# =============================================================================
# ADV-05: Abuso en solicitud de concesiones (motivos, duración y concurrencia)
# =============================================================================
async def test_adv05_solicitud_concesion_rechaza_motivo_generico_y_exceso_cupo(
    cliente: Any,
    dos_clientes: list[str],
    staff_factory: Any,
    db: Any,
) -> None:
    """Rechaza motivos pobres/sin referencia en código, duración fuera de rango y >3 activas."""
    emp = await staff_factory("staff_soporte")
    headers = _headers_staff(emp["id"], "staff_soporte")

    # 1) Motivo pobre (< 5 palabras distintas)
    r_gen = await cliente.post(
        "/admin/v1/access-grants",
        headers=headers,
        json={
            "tenant_id": TENANT_A,
            "alcance": "datos_negocio",
            "motivo": "revision revision revision revision revision",
        },
    )
    assert r_gen.status_code == 422

    # 2) Alcance contenido_codigo sin referencia a ticket/caso verificable
    r_sin_ref = await cliente.post(
        "/admin/v1/access-grants",
        headers=headers,
        json={
            "tenant_id": TENANT_A,
            "alcance": "contenido_codigo",
            "motivo": "Analisis detallado del fallo reportado por el cliente en produccion",
        },
    )
    assert r_sin_ref.status_code == 422

    # 3) Duración superior al máximo permitido (> 480 min)
    r_dur = await cliente.post(
        "/admin/v1/access-grants",
        headers=headers,
        json={
            "tenant_id": TENANT_A,
            "alcance": "contenido_codigo",
            "motivo": "Análisis de fallo en generación de patch para caso KC-3310",
            "duracion_min": 600,
            "referencia": "KC-3310",
        },
    )
    assert r_dur.status_code == 422

    # 4) Techo de 3 concesiones simultáneas por empleado
    for idx, (tid_item, alcance_item, ref_sup) in enumerate(
        (
            (TENANT_A, "datos_negocio", "SUP-01"),
            (TENANT_A, "expediente", "SUP-01"),
            (TENANT_B, "datos_negocio", "SUP-02"),
        )
    ):
        await db.execute(
            text(
                """
                INSERT INTO admin.access_grants (
                    id, staff_id, tenant_id, scope, reason, granted_at, expires_at
                )
                VALUES (
                    :gid, :sid, :tid, :sc, :motivo,
                    now(), now() + interval '1 hour'
                )
                """
            ),
            {
                "gid": nuevo("gr"),
                "sid": emp["id"],
                "tid": tid_item,
                "sc": alcance_item,
                "motivo": f"Atención de incidencia verificada caso {ref_sup} / KC-70{idx}",
            },
        )
    await db.commit()

    r_cuarta = await cliente.post(
        "/admin/v1/access-grants",
        headers=headers,
        json={
            "tenant_id": TENANT_B,
            "alcance": "expediente",
            "motivo": "Intento de cuarta concesión simultánea en caso KC-7099",
        },
    )
    assert r_cuarta.status_code in (409, 422, 429)


# =============================================================================
# ADV-06: Escritura cruzada DML/DDL en BD y barrera RLS de actor_tipo='staff'
# =============================================================================
@pytest.mark.parametrize(
    "sql_prohibido",
    [
        "INSERT INTO core.organizations (id, nombre) VALUES ('org_hack', 'Hack')",
        "UPDATE core.subscriptions SET plan_codigo = 'enterprise'",
        "DELETE FROM core.usage_tokens",
        "TRUNCATE core.organizations CASCADE",
        "UPDATE admin.access_grants SET expires_at = now() + interval '10 years'",
        "DELETE FROM admin.staff_actions",
        "INSERT INTO audit.audit_events (tenant_id, actor_tipo, actor_id, evento, sello) "
        "VALUES ('org_acme', 'staff', 'st_x', 'fake', '00')",
    ],
)
async def test_adv06_rol_ro_rechaza_toda_escritura_en_core_admin_y_audit(
    db_ro: Any,
    sql_prohibido: str,
) -> None:
    """kallicode_admin_ro falla a nivel de motor PostgreSQL ante cualquier DML."""
    with pytest.raises((ProgrammingError, InternalError, DBAPIError)):
        await db_ro.execute(text(sql_prohibido))
    await db_ro.rollback()


async def test_adv06_rol_app_no_puede_falsificar_actor_no_staff_en_audit_events(
    db: Any,
) -> None:
    """La política RLS admin_app_audit_insert bloquea actor_tipo != 'staff'."""
    with pytest.raises((ProgrammingError, DBAPIError)) as exc:
        await db.execute(
            text(
                """
                INSERT INTO audit.audit_events (
                    tenant_id, actor_tipo, actor_id, evento, resumen, datos, sello_previo, sello
                )
                VALUES (
                    'org_acme', 'humano', 'usr_suplantado', 'admin.staff.read',
                    'Intento de falsificar evento humano desde consola',
                    '{}'::jsonb, NULL, :sello
                )
                """
            ),
            {"sello": "f" * 64},
        )
    await db.rollback()
    mensaje = str(exc.value).lower()
    assert "row-level security" in mensaje or "permission denied" in mensaje


# =============================================================================
# ADV-07: Confusión de identidad JWT y escalada horizontal de roles
# =============================================================================
async def test_adv07_rechaza_token_de_cliente_portal_mfa_caducado_y_escalada_rol(
    cliente: Any,
    staff_factory: Any,
) -> None:
    """Tokens con typ/iss/aud de cliente o MFA > 30m son rechazados con 401/403."""
    clave_privada, _ = _claves()
    ahora = datetime.now(UTC)

    # 1) Token válido criptográficamente pero con typ='access' (portal de cliente)
    token_cliente = jwt.encode(
        {
            "sub": "st_prueba",
            "rol": "staff_admin",
            "typ": "access",
            "iss": "kallicode-admin",
            "aud": "admin-v1",
            "mfa": int(ahora.timestamp()),
            "iat": int(ahora.timestamp()),
            "exp": int((ahora + timedelta(minutes=15)).timestamp()),
            "jti": nuevo("jti"),
        },
        clave_privada,
        algorithm="RS256",
    )
    r_typ = await cliente.get(
        "/admin/v1/business/overview",
        headers={"Authorization": f"Bearer {token_cliente}"},
    )
    assert r_typ.status_code == 401

    # 2) Token staff con MFA superado hace 45 minutos (> 30 min idle timeout)
    emp_ops = await staff_factory("staff_operaciones")
    r_mfa_vencido = await cliente.get(
        "/admin/v1/ops/agents",
        headers=_headers_staff(emp_ops["id"], "staff_operaciones", mfa_offset_min=-45),
    )
    assert r_mfa_vencido.status_code in (401, 403)

    # 3) Escalada horizontal: staff_operaciones intentando consultar clientes o staff
    headers_ops = _headers_staff(emp_ops["id"], "staff_operaciones")
    r_esc_clientes = await cliente.get(
        "/admin/v1/business/customers",
        headers=headers_ops,
    )
    assert r_esc_clientes.status_code == 403
    assert r_esc_clientes.json()["error"]["codigo"] == "ROL_STAFF_INSUFICIENTE"

    r_esc_staff = await cliente.get("/admin/v1/staff", headers=headers_ops)
    assert r_esc_staff.status_code == 403


# =============================================================================
# ADV-08: Sellado inmutable en admin.staff_actions y cadena central audit_events
# =============================================================================
async def test_adv08_lectura_con_concesion_sella_ambas_cadenas_y_bloquea_mutacion(
    cliente: Any,
    dos_clientes: list[str],
    staff_factory: Any,
    db: Any,
) -> None:
    """Toda lectura revelada queda encadenada en admin.staff_actions y audit.audit_events."""
    emp = await staff_factory("staff_soporte")
    gid = nuevo("gr")
    await db.execute(
        text(
            """
            INSERT INTO admin.access_grants (
                id, staff_id, tenant_id, scope, reason, granted_at, expires_at
            )
            VALUES (:gid, :sid, :tid, 'expediente', :motivo, now(), now() + interval '1 hour')
            """
        ),
        {"gid": gid, "sid": emp["id"], "tid": TENANT_A, "motivo": MOTIVO_CASO},
    )
    await db.commit()

    r_ok = await cliente.get(
        f"/admin/v1/business/customers/{TENANT_A}",
        headers=_headers_staff(emp["id"], "staff_soporte"),
    )
    assert r_ok.status_code == 200
    assert r_ok.json()["razon_social"] == "Acme Logística S.L."

    # 1) Verificar registro en admin.staff_actions con grant_id y motivo
    res_sa = await db.execute(
        text(
            """
            SELECT id, action, tenant_id, grant_id, reason, seal
            FROM admin.staff_actions
            WHERE staff_id = :sid AND tenant_id = :tid AND grant_id = :gid
            ORDER BY id DESC LIMIT 1
            """
        ),
        {"sid": emp["id"], "tid": TENANT_A, "gid": gid},
    )
    fila_sa = res_sa.mappings().first()
    assert fila_sa is not None
    assert fila_sa["reason"] == MOTIVO_CASO
    assert len(fila_sa["seal"]) == 64

    # 2) Verificar réplica encadenada en audit.audit_events con actor_tipo = 'staff'
    res_ae = await db.execute(
        text(
            """
            SELECT actor_tipo, actor_id, evento, datos, sello
            FROM audit.audit_events
            WHERE tenant_id = :tid
              AND actor_tipo = 'staff'
              AND datos->>'staff_action_id' = :said
            """
        ),
        {"tid": TENANT_A, "said": str(fila_sa["id"])},
    )
    fila_ae = res_ae.mappings().first()
    assert fila_ae is not None
    assert fila_ae["actor_tipo"] == "staff"
    assert fila_ae["actor_id"] == emp["id"]
    assert fila_ae["datos"]["actor"]["typ"] == "staff"
    assert len(fila_ae["sello"]) == 64

    # 3) Integridad criptográfica de la cadena local y central
    res_local = await db.execute(text("SELECT * FROM admin.verify_staff_action_chain()"))
    assert res_local.fetchall() == []

    verificacion_central = await verificar_cadena_central_tenant(db, TENANT_A)
    assert verificacion_central["integra"] is True

    # 4) Intento adversario de borrar o alterar la huella en admin.staff_actions
    with pytest.raises((ProgrammingError, DBAPIError)):
        await db.execute(
            text("UPDATE admin.staff_actions SET reason = 'borrado' WHERE id = :id"),
            {"id": fila_sa["id"]},
        )
    await db.rollback()

    with pytest.raises((ProgrammingError, DBAPIError)):
        await db.execute(
            text("DELETE FROM admin.staff_actions WHERE id = :id"),
            {"id": fila_sa["id"]},
        )
    await db.rollback()
