"""Suite de Pruebas de Auditoría de Personal para el Portal Cliente (§11.6, ADM-G04).

Ticket [KC-ADM-B2-07]: Exposición de Accesos de Staff en el Portal del Cliente.

Verifica:
  1. Aislamiento estricto por tenant (cada cliente ve solo sus accesos).
  2. Privacidad inquebrantable del personal (cero fugas de staff_id, email, o prefijo st_).
  3. Formateo seguro de actor (L. Prieto) y casos borde (vacío, None, mono-palabra).
  4. Validaciones de negocio: fechas invertidas, ventana > 365 días, límites de paginación.
  5. Respuesta vacía por defecto HTTP 200 con {items: [], total: 0}, nunca 404.
  6. Autorización estricta por roles de portal (owner, admin, architect, approver).
  7. Rechazo de tokens inválidos, expirados o realm de staff (typ=staff).
  8. Verificación forense real de la cadena de sellos SHA-256 (campo verificado).
"""

from __future__ import annotations

import re
import time
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import patch

import jwt
import pytest
from admin_api.audit import (
    calcular_sello_staff_action,
    formatear_nombre_publico,
    recalcular_y_verificar_cadena,
    registrar_accion_staff,
    verificar_cadena_staff_actions,
)
from admin_api.security import _claves
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, InternalError, ProgrammingError
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

pytestmark = pytest.mark.integracion

ROLES_PERMITIDOS = ("owner", "admin", "architect", "approver")
ROLES_DENEGADOS = ("developer", "viewer", "operator")


# ========================================================= 1. Casos Borde Formateo
def test_formatear_nombre_publico_casos_borde() -> None:
    """Verifica manejo limpio de nombres de una sola palabra, vacíos o None."""
    assert formatear_nombre_publico(None) == "Staff KalliCode"
    assert formatear_nombre_publico("") == "Staff KalliCode"
    assert formatear_nombre_publico("   ") == "Staff KalliCode"
    assert formatear_nombre_publico("Laura") == "Laura"
    assert formatear_nombre_publico("Admin") == "Admin"
    assert formatear_nombre_publico("Laura Prieto") == "L. Prieto"
    assert formatear_nombre_publico("Laura Prieto González") == "L. Prieto González"
    assert formatear_nombre_publico("L. Prieto") == "L. Prieto"
    assert formatear_nombre_publico("Empleado staff_soporte") == "E. staff_soporte"


# ========================================================= 2. Fixtures y Helpers
async def _crear_concesion_y_accion(
    db: Any,
    staff_id: str,
    tenant_id: str,
    scope: str = "datos_negocio",
    reason: str = "Revision del caso de soporte SUP-10020",
    reference: str = "KC-10020",
    duracion_min: int = 60,
    reads: int = 2,
) -> str:
    from admin_api.audit import registrar_accion
    from kallicode_core.ids import nuevo

    grant_id = nuevo("gr")
    ahora = datetime.now(UTC)
    caduca = ahora + timedelta(minutes=duracion_min)

    await db.execute(
        text(
            """
        INSERT INTO admin.access_grants
            (id, staff_id, tenant_id, scope, reason, reference, granted_at, expires_at, reads)
        VALUES (:id, :s, :t, :sc, :rz, :ref, :g_at, :e_at, :reads)
    """
        ),
        {
            "id": grant_id,
            "s": staff_id,
            "t": tenant_id,
            "sc": scope,
            "rz": reason,
            "ref": reference,
            "g_at": ahora,
            "e_at": caduca,
            "reads": reads,
        },
    )

    await registrar_accion(
        db,
        staff_id=staff_id,
        staff_role="staff_soporte",
        action="grant_created",
        endpoint="POST /admin/v1/access-grants",
        tenant_id=tenant_id,
        grant_id=grant_id,
        scope=scope,
        reason=reason,
    )
    await db.commit()
    return grant_id


def _token_portal(
    user_id: str = "usr_test",
    org: str = "org_acme",
    rol: str = "admin",
    exp_delta: int = 1800,
    iss: str = "kc-portal",
    aud: str = "kc-portal-api",
    typ: str = "user",
) -> str:
    priv, _ = _claves()
    ahora = int(time.time())
    return jwt.encode(
        {
            "sub": user_id,
            "org": org,
            "rol": rol,
            "typ": typ,
            "iss": iss,
            "aud": aud,
            "jti": uuid.uuid4().hex,
            "iat": ahora,
            "exp": ahora + exp_delta,
        },
        priv,
        algorithm="RS256",
    )


# ========================================================= 3. Aislamiento por Tenant
async def test_aislamiento_estricto_por_tenant(
    cliente: Any, db: Any, staff_factory: Any
) -> None:
    """Un usuario del tenant A nunca puede ver concesiones del tenant B."""
    st = await staff_factory("staff_soporte")

    # Insertar una concesión para org_acme y otra para org_globex
    await _crear_concesion_y_accion(
        db,
        st["id"],
        "org_acme",
        reason="Revision justificada de incidencias SUP-01",
        reference="KC-01",
    )
    await _crear_concesion_y_accion(
        db,
        st["id"],
        "org_globex",
        reason="Revision justificada de incidencias SUP-02",
        reference="KC-02",
    )

    token_a = _token_portal(user_id="usr_a", org="org_acme", rol="admin")
    resp_a = await cliente.get(
        "/api/v1/audit/staff-accesses",
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert resp_a.status_code == 200, resp_a.text
    datos_a = resp_a.json()
    assert datos_a["total"] >= 1
    # Todas las filas pertenecen a org_acme
    for item in datos_a["items"]:
        assert "SUP-01" in item["motivo"]
        assert "SUP-02" not in item["motivo"]

    token_b = _token_portal(user_id="usr_b", org="org_globex", rol="owner")
    resp_b = await cliente.get(
        "/api/v1/audit/staff-accesses",
        headers={"Authorization": f"Bearer {token_b}"},
    )
    assert resp_b.status_code == 200, resp_b.text
    datos_b = resp_b.json()
    assert datos_b["total"] >= 1
    for item in datos_b["items"]:
        assert "SUP-02" in item["motivo"]
        assert "SUP-01" not in item["motivo"]


# ========================================================= 4. Respuesta Vacía 200
async def test_tenant_sin_accesos_devuelve_200_con_items_vacio(cliente: Any) -> None:
    """Una organización sin accesos recibe 200 con items: [] y total: 0, jamás 404."""
    tenant_vacio = f"org_vacia_{uuid.uuid4().hex[:6]}"
    token = _token_portal(user_id="usr_vacio", org=tenant_vacio, rol="owner")

    r = await cliente.get(
        "/api/v1/audit/staff-accesses",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200
    cuerpo = r.json()
    assert cuerpo["items"] == []
    assert cuerpo["total"] == 0
    assert cuerpo["page"] == 1
    assert cuerpo["page_size"] == 25


# ========================================================= 5. Privacidad Estricta
async def test_privacidad_estricta_del_personal_sin_fugas(
    cliente: Any, db: Any, staff_factory: Any
) -> None:
    """La respuesta jamás expone staff_id, staff_email ni prefijo st_."""
    st = await staff_factory("staff_soporte")
    tenant = "org_acme"

    # Asignar un nombre conocido al empleado en base
    await db.execute(
        text("UPDATE admin.staff SET full_name = 'Lucía Prieto' WHERE id = :s"),
        {"s": st["id"]},
    )
    await db.commit()

    await _crear_concesion_y_accion(
        db,
        st["id"],
        tenant,
        reason="Atención urgente de soporte ticket KC-9900",
        reference="KC-9900",
    )

    token = _token_portal(user_id="usr_priv", org=tenant, rol="admin")
    r = await cliente.get(
        "/api/v1/audit/staff-accesses",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200
    texto_respuesta = r.text
    cuerpo = r.json()

    # Prohibición absoluta de fugas
    assert st["id"] not in texto_respuesta
    assert st["email"] not in texto_respuesta
    assert "st_" not in texto_respuesta
    assert "@kallicode.com" not in texto_respuesta

    item = next(it for it in cuerpo["items"] if "KC-9900" in it["motivo"])
    assert item["actor"] == {
        "nombre": "L. Prieto",
        "rol": "staff_soporte",
    }
    assert item["alcance"] == "datos_negocio"
    assert "KC-9900" in item["motivo"]
    assert item["verificado"] is True
    assert item["accesos"] == 2


# ========================================================= 6. Validaciones de Negocio
async def test_validaciones_de_parametros_fechas_y_paginacion(cliente: Any) -> None:
    """Valida rango de 365 días, cronología invertida y límites de página."""
    token = _token_portal(user_id="usr_val", org="org_acme", rol="admin")
    cabecera = {"Authorization": f"Bearer {token}"}

    # 1. Rango invertido (desde posterior a hasta)
    r1 = await cliente.get(
        "/api/v1/audit/staff-accesses?desde=2026-10-25&hasta=2026-10-10",
        headers=cabecera,
    )
    assert r1.status_code == 422
    assert r1.json()["error"]["codigo"] == "VALIDACION_ENTRADA"

    # 2. Rango mayor a 365 días
    r2 = await cliente.get(
        "/api/v1/audit/staff-accesses?desde=2024-01-01&hasta=2026-01-01",
        headers=cabecera,
    )
    assert r2.status_code == 422
    assert r2.json()["error"]["codigo"] == "VALIDACION_ENTRADA"

    # 3. page < 1
    r3 = await cliente.get("/api/v1/audit/staff-accesses?page=0", headers=cabecera)
    assert r3.status_code == 422
    assert r3.json()["error"]["codigo"] == "VALIDACION_ENTRADA"

    # 4. page_size > 100
    r4 = await cliente.get("/api/v1/audit/staff-accesses?page_size=101", headers=cabecera)
    assert r4.status_code == 422
    assert r4.json()["error"]["codigo"] == "VALIDACION_ENTRADA"


async def test_filtro_por_ticket_id(cliente: Any, db: Any, staff_factory: Any) -> None:
    """El parámetro ticket_id filtra concesiones asociadas al caso."""
    st1 = await staff_factory("staff_soporte")
    st2 = await staff_factory("staff_admin")
    tenant = "org_globex"

    await _crear_concesion_y_accion(
        db,
        st1["id"],
        tenant,
        reason="Revision de incidencia KC-4001 urgente",
        reference="KC-4001",
    )
    await _crear_concesion_y_accion(
        db,
        st2["id"],
        tenant,
        reason="Revision de incidencia KC-4002 rutinaria",
        reference="KC-4002",
    )

    token = _token_portal(user_id="usr_tkt", org=tenant, rol="owner")
    r = await cliente.get(
        "/api/v1/audit/staff-accesses?ticket_id=KC-4001",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200
    cuerpo = r.json()
    assert cuerpo["total"] == 1
    assert "KC-4001" in cuerpo["items"][0]["motivo"]


# ========================================================= 7. Autenticación y RBAC
@pytest.mark.parametrize("rol", ROLES_PERMITIDOS)
async def test_roles_autorizados_portal_acceden_con_200(cliente: Any, rol: str) -> None:
    """Roles owner, admin, architect y approver están autorizados."""
    token = _token_portal(user_id=f"usr_{rol}", org="org_acme", rol=rol)
    r = await cliente.get(
        "/api/v1/audit/staff-accesses",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200


@pytest.mark.parametrize("rol", ROLES_DENEGADOS)
async def test_roles_no_autorizados_portal_reciben_403(cliente: Any, rol: str) -> None:
    """Roles restringidos del portal (developer, viewer, etc.) reciben 403."""
    token = _token_portal(user_id=f"usr_{rol}", org="org_acme", rol=rol)
    r = await cliente.get(
        "/api/v1/audit/staff-accesses",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 403
    assert r.json()["error"]["codigo"] in ("PERMISO_DENEGADO", "ROL_INSUFICIENTE")


async def test_peticion_sin_token_es_401(cliente: Any) -> None:
    """Peticiones anónimas devuelven 401."""
    r = await cliente.get("/api/v1/audit/staff-accesses")
    assert r.status_code == 401


async def test_token_expirado_portal_es_401(cliente: Any) -> None:
    """Tokens expirados devuelven 401."""
    token_exp = _token_portal(exp_delta=-60)
    r = await cliente.get(
        "/api/v1/audit/staff-accesses",
        headers={"Authorization": f"Bearer {token_exp}"},
    )
    assert r.status_code == 401


async def test_token_realm_staff_no_sirve_en_portal(cliente: Any, staff_factory: Any) -> None:
    """Un token con typ=staff no es admitido en la API de portal."""
    from admin_api.security import emitir_tokens_staff

    st = await staff_factory("staff_admin")
    token_staff = emitir_tokens_staff(st["id"], "staff_admin", datetime.now(UTC))

    r = await cliente.get(
        "/api/v1/audit/staff-accesses",
        headers={"Authorization": f"Bearer {token_staff}"},
    )
    assert r.status_code == 401


# ========================================================= 8. Verificación Criptográfica
async def test_verificacion_criptografica_refleja_integridad(
    cliente: Any, db: Any, staff_factory: Any
) -> None:
    """El campo 'verificado' es true cuando la cadena está íntegra."""
    st = await staff_factory("staff_soporte")
    tenant = "org_acme"

    await _crear_concesion_y_accion(
        db,
        st["id"],
        tenant,
        reason="Verificacion de sellos de auditoria caso SUP-123",
        reference="KC-123",
    )

    token = _token_portal(user_id="usr_forense", org=tenant, rol="admin")
    r = await cliente.get(
        "/api/v1/audit/staff-accesses",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200
    cuerpo = r.json()
    assert len(cuerpo["items"]) >= 1
    assert cuerpo["items"][0]["verificado"] is True


async def test_cadena_corrompida_hace_verificado_false(
    cliente: Any, db: Any, staff_factory: Any
) -> None:
    """Si la cadena de sellos reporta rupturas, verificado debe ser False."""
    st = await staff_factory("staff_soporte")
    tenant = "org_acme"

    gid = await _crear_concesion_y_accion(
        db, st["id"], tenant, reason="Acceso legitimo caso SUP-999", reference="KC-999"
    )

    with patch(
        "admin_api.audit.verificar_cadena",
        return_value=[
            {"broken_at": datetime.now(UTC), "broken_id": 1, "motivo": "sello no reproducible"}
        ],
    ):
        token = _token_portal(user_id="usr_tamper", org=tenant, rol="admin")
        r = await cliente.get(
            "/api/v1/audit/staff-accesses",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 200
        cuerpo = r.json()
        item = next(it for it in cuerpo["items"] if it["id"] == gid)
        assert item["verificado"] is False


async def test_alias_de_ruta_audit_staff_accesses_funciona(cliente: Any) -> None:
    """El alias /audit/staff-accesses responde idéntico a /api/v1/audit/staff-accesses."""
    token = _token_portal(org="org_acme", rol="admin")
    r = await cliente.get(
        "/audit/staff-accesses",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200
    assert "items" in r.json()
    assert "total" in r.json()


# ========================================================= 9. Recálculo Determinista
async def test_recalculo_determinista_sha256_coincide_con_base_de_datos(
    db: Any, staff_factory: Any
) -> None:
    """Verifica que el hash recalculado en Python coincide 100% con el seal de BD."""
    st = await staff_factory("staff_admin")
    sid = st["id"]

    for i in range(5):
        await registrar_accion_staff(
            db,
            staff_id=sid,
            staff_role="staff_admin",
            accion="admin_query",
            endpoint=f"/admin/v1/test-recalc-{i}",
            motivo=f"Motivo determinista de auditoria {i}",
            alcance="sistema",
            recurso="configuracion",
            datos={"indice": i, "modo": "determinista"},
        )
    await db.commit()

    res = await db.execute(
        text(
            """
        SELECT id, occurred_at::text AS ts, staff_id, action,
               tenant_id, scope, reason, resource, endpoint,
               payload::text AS pl, prev_seal, seal
        FROM admin.staff_actions
        ORDER BY occurred_at, id
    """
        )
    )
    filas = res.fetchall()
    assert len(filas) >= 5

    for f in filas:
        sello_py = calcular_sello_staff_action(
            prev_seal=f.prev_seal or "",
            occurred_at=f.ts,
            staff_id=f.staff_id,
            action=f.action,
            endpoint=f.endpoint,
            tenant_id=f.tenant_id,
            scope=f.scope,
            reason=f.reason,
            resource=f.resource,
            payload=f.pl or "",
        )
        assert f.seal == sello_py, f"Fallo en recálculo ID {f.id}: DB {f.seal} != PY {sello_py}"
        assert len(f.seal) == 64
        assert re.match(r"^[0-9a-f]{64}$", f.seal)


async def test_integridad_y_continuidad_criptografica_de_la_cadena(
    db: Any, staff_factory: Any
) -> None:
    """Verifica que cada evento referencie exactamente el sello del evento anterior."""
    st = await staff_factory("staff_soporte")
    sid = st["id"]

    for i in range(4):
        await registrar_accion_staff(
            db,
            staff_id=sid,
            staff_role="staff_soporte",
            accion="read",
            endpoint=f"/admin/v1/business/customers/{i}",
            tenant_id="org_acme",
            motivo=f"Consulta de cliente caso {i}",
            alcance="datos_negocio",
        )
    await db.commit()

    res = await db.execute(
        text("SELECT id, prev_seal, seal FROM admin.staff_actions ORDER BY occurred_at, id")
    )
    filas = res.fetchall()
    assert len(filas) >= 4

    for i in range(1, len(filas)):
        evento_anterior = filas[i - 1]
        evento_actual = filas[i]
        assert evento_actual.prev_seal == evento_anterior.seal, (
            f"Discontinuidad en evento ID {evento_actual.id}: "
            f"esperaba {evento_anterior.seal[:12]} pero obtuvo {evento_actual.prev_seal[:12]}"
        )


async def test_verificado_true_solo_cuando_cadena_completa_es_integra(db: Any) -> None:
    """Verifica que verificado: true e integra: true solo se devuelven si no hay roturas."""
    res_sql = await verificar_cadena_staff_actions(db)
    assert res_sql.integra is True
    assert res_sql.verificado is True
    assert res_sql.total_roturas == 0
    assert res_sql.primer_evento_roto is None
    assert res_sql["verificado"] is True
    assert res_sql["integra"] is True

    res_py = await recalcular_y_verificar_cadena(db)
    assert res_py.integra is True
    assert res_py.verificado is True
    assert res_py.total_roturas == 0
    assert res_py.primer_evento_roto is None


# ========================================================= 10. Pruebas Adversarias (Tamper)
async def test_tamper_alteracion_payload_detecta_ruptura_y_primer_evento_roto(
    dsn: str, db: Any, staff_factory: Any
) -> None:
    """Simula alteración maliciosa en payload y comprueba detección y primer_evento_roto."""
    st = await staff_factory("staff_admin")
    await registrar_accion_staff(
        db,
        staff_id=st["id"],
        staff_role="staff_admin",
        accion="admin_query",
        endpoint="/admin/v1/tamper-payload",
        motivo="Accion previa al ataque de payload",
        datos={"inmutable": True},
    )
    await db.commit()

    engine_su = create_async_engine(
        dsn.replace("postgresql://", "postgresql+asyncpg://"),
        poolclass=NullPool,
    )
    async with engine_su.begin() as conn:
        res = await conn.execute(
            text(
                """
            SELECT id, payload::text AS pl FROM admin.staff_actions
            WHERE endpoint = '/admin/v1/tamper-payload'
            ORDER BY id DESC LIMIT 1
        """
            )
        )
        row = res.fetchone()
        assert row is not None
        target_id = row.id
        orig_pl = row.pl

        try:
            # 1. Deshabilitar trigger de inmutabilidad y alterar payload
            await conn.execute(
                text(
                    "ALTER TABLE admin.staff_actions "
                    "DISABLE TRIGGER trg_staff_actions_immutable"
                )
            )
            await conn.execute(
                text(
                    """
                UPDATE admin.staff_actions
                SET payload = '{"inmutable": false, "inyeccion": "maliciosa"}'::jsonb
                WHERE id = :id
            """
                ),
                {"id": target_id},
            )
            await conn.execute(
                text(
                    "ALTER TABLE admin.staff_actions ENABLE TRIGGER trg_staff_actions_immutable"
                )
            )

            # 2. Ejecutar verificación SQL y Python
            res_sql = await verificar_cadena_staff_actions(conn)
            assert res_sql.integra is False
            assert res_sql.verificado is False
            assert res_sql.total_roturas >= 1
            assert res_sql.primer_evento_roto is not None
            assert res_sql.primer_evento_roto["broken_id"] == target_id
            assert "sello no reproducible" in res_sql.primer_evento_roto["motivo"]

            res_py = await recalcular_y_verificar_cadena(conn)
            assert res_py.integra is False
            assert res_py.verificado is False
            assert res_py.primer_evento_roto is not None
            assert res_py.primer_evento_roto["broken_id"] == target_id

        finally:
            # 3. Restaurar estado original
            await conn.execute(
                text(
                    "ALTER TABLE admin.staff_actions "
                    "DISABLE TRIGGER trg_staff_actions_immutable"
                )
            )
            await conn.execute(
                text(
                    """
                UPDATE admin.staff_actions
                SET payload = CAST(:pl AS jsonb)
                WHERE id = :id
            """
                ),
                {"pl": orig_pl, "id": target_id},
            )
            await conn.execute(
                text(
                    "ALTER TABLE admin.staff_actions ENABLE TRIGGER trg_staff_actions_immutable"
                )
            )

    await engine_su.dispose()

    # Confirmar restitución de integridad
    limpio = await verificar_cadena_staff_actions(db)
    assert limpio.integra is True
    assert limpio.verificado is True


async def test_tamper_alteracion_motivo_detecta_ruptura_inmediata(
    dsn: str, db: Any, staff_factory: Any
) -> None:
    """Simula alteración de motivo (reason) y comprueba reporte de primer_evento_roto."""
    st = await staff_factory("staff_admin")
    await registrar_accion_staff(
        db,
        staff_id=st["id"],
        staff_role="staff_admin",
        accion="admin_query",
        endpoint="/admin/v1/tamper-reason",
        motivo="Motivo legitimo auditado",
    )
    await db.commit()

    engine_su = create_async_engine(
        dsn.replace("postgresql://", "postgresql+asyncpg://"),
        poolclass=NullPool,
    )
    async with engine_su.begin() as conn:
        res = await conn.execute(
            text(
                """
            SELECT id, reason FROM admin.staff_actions
            WHERE endpoint = '/admin/v1/tamper-reason'
            ORDER BY id DESC LIMIT 1
        """
            )
        )
        row = res.fetchone()
        assert row is not None
        target_id = row.id
        orig_reason = row.reason

        try:
            await conn.execute(
                text(
                    "ALTER TABLE admin.staff_actions "
                    "DISABLE TRIGGER trg_staff_actions_immutable"
                )
            )
            await conn.execute(
                text(
                    "UPDATE admin.staff_actions "
                    "SET reason = 'motivo falsificado' WHERE id = :id"
                ),
                {"id": target_id},
            )
            await conn.execute(
                text(
                    "ALTER TABLE admin.staff_actions ENABLE TRIGGER trg_staff_actions_immutable"
                )
            )

            res_sql = await verificar_cadena_staff_actions(conn)
            assert res_sql.integra is False
            assert res_sql.verificado is False
            assert res_sql.primer_evento_roto is not None
            assert res_sql.primer_evento_roto["broken_id"] == target_id
            assert "sello no reproducible" in res_sql.primer_evento_roto["motivo"]

            res_py = await recalcular_y_verificar_cadena(conn)
            assert res_py.integra is False
            assert res_py.primer_evento_roto is not None
            assert res_py.primer_evento_roto["broken_id"] == target_id

        finally:
            await conn.execute(
                text(
                    "ALTER TABLE admin.staff_actions "
                    "DISABLE TRIGGER trg_staff_actions_immutable"
                )
            )
            await conn.execute(
                text("UPDATE admin.staff_actions SET reason = :r WHERE id = :id"),
                {"r": orig_reason, "id": target_id},
            )
            await conn.execute(
                text(
                    "ALTER TABLE admin.staff_actions ENABLE TRIGGER trg_staff_actions_immutable"
                )
            )

    await engine_su.dispose()

    limpio = await verificar_cadena_staff_actions(db)
    assert limpio.integra is True


async def test_tamper_alteracion_timestamp_detecta_ruptura_inmediata(
    dsn: str, db: Any, staff_factory: Any
) -> None:
    """Simula alteración de occurred_at y comprueba detección de ruptura inmediata."""
    st = await staff_factory("staff_admin")
    await registrar_accion_staff(
        db,
        staff_id=st["id"],
        staff_role="staff_admin",
        accion="admin_query",
        endpoint="/admin/v1/tamper-timestamp",
        motivo="Accion previa a alteracion temporal",
    )
    await db.commit()

    engine_su = create_async_engine(
        dsn.replace("postgresql://", "postgresql+asyncpg://"),
        poolclass=NullPool,
    )
    async with engine_su.begin() as conn:
        res = await conn.execute(
            text(
                """
            SELECT id, occurred_at FROM admin.staff_actions
            WHERE endpoint = '/admin/v1/tamper-timestamp'
            ORDER BY id DESC LIMIT 1
        """
            )
        )
        row = res.fetchone()
        assert row is not None
        target_id = row.id
        orig_ts = row.occurred_at

        try:
            await conn.execute(
                text(
                    "ALTER TABLE admin.staff_actions "
                    "DISABLE TRIGGER trg_staff_actions_immutable"
                )
            )
            await conn.execute(
                text(
                    "UPDATE admin.staff_actions "
                    "SET occurred_at = occurred_at - interval '2 hours' "
                    "WHERE id = :id"
                ),
                {"id": target_id},
            )
            await conn.execute(
                text(
                    "ALTER TABLE admin.staff_actions ENABLE TRIGGER trg_staff_actions_immutable"
                )
            )

            res_sql = await verificar_cadena_staff_actions(conn)
            assert res_sql.integra is False
            assert res_sql.verificado is False
            assert res_sql.primer_evento_roto is not None
            assert res_sql.primer_evento_roto["broken_id"] == target_id

            res_py = await recalcular_y_verificar_cadena(conn)
            assert res_py.integra is False
            assert res_py.primer_evento_roto is not None
            assert res_py.primer_evento_roto["broken_id"] == target_id

        finally:
            await conn.execute(
                text(
                    "ALTER TABLE admin.staff_actions "
                    "DISABLE TRIGGER trg_staff_actions_immutable"
                )
            )
            await conn.execute(
                text("UPDATE admin.staff_actions SET occurred_at = :ts WHERE id = :id"),
                {"ts": orig_ts, "id": target_id},
            )
            await conn.execute(
                text(
                    "ALTER TABLE admin.staff_actions ENABLE TRIGGER trg_staff_actions_immutable"
                )
            )

    await engine_su.dispose()

    limpio = await verificar_cadena_staff_actions(db)
    assert limpio.integra is True


async def test_tamper_supresion_registro_intermedio_detecta_discontinuidad(
    dsn: str, db: Any, staff_factory: Any
) -> None:
    """Simula eliminación de registro intermedio y verifica detección de encadenamiento roto."""
    st = await staff_factory("staff_admin")
    sid = st["id"]

    # Insertar 3 registros continuos
    await registrar_accion_staff(
        db,
        staff_id=sid,
        staff_role="staff_admin",
        accion="admin_query",
        endpoint="/admin/v1/del-step-1",
        motivo="Paso 1 de secuencia",
    )
    await registrar_accion_staff(
        db,
        staff_id=sid,
        staff_role="staff_admin",
        accion="admin_query",
        endpoint="/admin/v1/del-step-2",
        motivo="Paso 2 a eliminar",
    )
    await registrar_accion_staff(
        db,
        staff_id=sid,
        staff_role="staff_admin",
        accion="admin_query",
        endpoint="/admin/v1/del-step-3",
        motivo="Paso 3 posterior",
    )
    await db.commit()

    engine_su = create_async_engine(
        dsn.replace("postgresql://", "postgresql+asyncpg://"),
        poolclass=NullPool,
    )
    async with engine_su.begin() as conn:
        res = await conn.execute(
            text(
                """
            SELECT id, occurred_at, staff_id, staff_email, staff_role, action,
                   tenant_id, grant_id, scope, reason, resource, endpoint,
                   ip, user_agent, request_id, payload, prev_seal, seal
            FROM admin.staff_actions
            WHERE endpoint = '/admin/v1/del-step-2'
            ORDER BY id DESC LIMIT 1
        """
            )
        )
        row_del = res.fetchone()
        assert row_del is not None

        res_post = await conn.execute(
            text(
                """
            SELECT id FROM admin.staff_actions
            WHERE endpoint = '/admin/v1/del-step-3'
            ORDER BY id DESC LIMIT 1
        """
            )
        )
        row_post = res_post.fetchone()
        assert row_post is not None
        post_id = row_post.id

        try:
            # Eliminar paso 2 con trigger deshabilitado
            await conn.execute(
                text(
                    "ALTER TABLE admin.staff_actions "
                    "DISABLE TRIGGER trg_staff_actions_immutable"
                )
            )
            await conn.execute(
                text("DELETE FROM admin.staff_actions WHERE id = :id"),
                {"id": row_del.id},
            )
            await conn.execute(
                text(
                    "ALTER TABLE admin.staff_actions ENABLE TRIGGER trg_staff_actions_immutable"
                )
            )

            # Verificar que el registro posterior (paso 3) reporta encadenamiento roto
            res_sql = await verificar_cadena_staff_actions(conn)
            assert res_sql.integra is False
            assert res_sql.primer_evento_roto is not None
            assert res_sql.primer_evento_roto["broken_id"] == post_id
            assert "encadenamiento roto" in res_sql.primer_evento_roto["motivo"]

            res_py = await recalcular_y_verificar_cadena(conn)
            assert res_py.integra is False
            assert res_py.primer_evento_roto is not None
            assert res_py.primer_evento_roto["broken_id"] == post_id

        finally:
            # Restaurar fila eliminada exactamente con su ID y sellos originales
            await conn.execute(
                text(
                    "ALTER TABLE admin.staff_actions "
                    "DISABLE TRIGGER trg_staff_actions_immutable"
                )
            )
            await conn.execute(
                text("ALTER TABLE admin.staff_actions DISABLE TRIGGER trg_staff_actions_seal")
            )
            await conn.execute(
                text(
                    """
                INSERT INTO admin.staff_actions (
                    id, occurred_at, staff_id, staff_email, staff_role, action,
                    tenant_id, grant_id, scope, reason, resource, endpoint,
                    ip, user_agent, request_id, payload, prev_seal, seal
                ) OVERRIDING SYSTEM VALUE VALUES (
                    :id, :o_at, :s_id, :s_em, :s_ro, :act,
                    :tid, :gid, :sc, :rz, :res, :ep,
                    :ip, :ua, :rq, :pl, :prev, :seal
                )
            """
                ),
                {
                    "id": row_del.id,
                    "o_at": row_del.occurred_at,
                    "s_id": row_del.staff_id,
                    "s_em": row_del.staff_email,
                    "s_ro": row_del.staff_role,
                    "act": row_del.action,
                    "tid": row_del.tenant_id,
                    "gid": row_del.grant_id,
                    "sc": row_del.scope,
                    "rz": row_del.reason,
                    "res": row_del.resource,
                    "ep": row_del.endpoint,
                    "ip": row_del.ip,
                    "ua": row_del.user_agent,
                    "rq": row_del.request_id,
                    "pl": row_del.payload,
                    "prev": row_del.prev_seal,
                    "seal": row_del.seal,
                },
            )
            await conn.execute(
                text("ALTER TABLE admin.staff_actions ENABLE TRIGGER trg_staff_actions_seal")
            )
            await conn.execute(
                text(
                    "ALTER TABLE admin.staff_actions ENABLE TRIGGER trg_staff_actions_immutable"
                )
            )

    await engine_su.dispose()

    limpio = await verificar_cadena_staff_actions(db)
    assert limpio.integra is True


# ========================================================= 11. Inmutabilidad Append-Only
async def test_trigger_inmutabilidad_bloquea_update_para_superusuario_y_app(
    dsn: str, db: Any, staff_factory: Any
) -> None:
    """Valida que el trigger trg_staff_actions_immutable impida cualquier UPDATE."""
    st = await staff_factory("staff_admin")
    await registrar_accion_staff(
        db,
        staff_id=st["id"],
        staff_role="staff_admin",
        accion="admin_query",
        endpoint="/admin/v1/trigger-update",
        motivo="Comprobacion de trigger UPDATE",
    )
    await db.commit()

    engine_su = create_async_engine(
        dsn.replace("postgresql://", "postgresql+asyncpg://"),
        poolclass=NullPool,
    )
    async with engine_su.connect() as conn:
        with pytest.raises((InternalError, DBAPIError)) as excinfo:
            await conn.execute(
                text(
                    """
                UPDATE admin.staff_actions
                SET reason = 'mutacion no autorizada'
                WHERE endpoint = '/admin/v1/trigger-update'
            """
                )
            )
        assert "append-only" in str(excinfo.value)
        assert "UPDATE no está permitido" in str(excinfo.value)

    await engine_su.dispose()


async def test_trigger_inmutabilidad_bloquea_delete_para_superusuario_y_app(
    dsn: str, db: Any, staff_factory: Any
) -> None:
    """Valida que el trigger trg_staff_actions_immutable impida cualquier DELETE."""
    st = await staff_factory("staff_admin")
    await registrar_accion_staff(
        db,
        staff_id=st["id"],
        staff_role="staff_admin",
        accion="admin_query",
        endpoint="/admin/v1/trigger-delete",
        motivo="Comprobacion de trigger DELETE",
    )
    await db.commit()

    engine_su = create_async_engine(
        dsn.replace("postgresql://", "postgresql+asyncpg://"),
        poolclass=NullPool,
    )
    async with engine_su.connect() as conn:
        with pytest.raises((InternalError, DBAPIError)) as excinfo:
            await conn.execute(
                text(
                    """
                DELETE FROM admin.staff_actions
                WHERE endpoint = '/admin/v1/trigger-delete'
            """
                )
            )
        assert "append-only" in str(excinfo.value)
        assert "DELETE no está permitido" in str(excinfo.value)

    await engine_su.dispose()


async def test_roles_app_y_ro_tienen_privilegios_dml_revocados(
    dsn: str, db: Any, staff_factory: Any
) -> None:
    """Verifica que kallicode_admin_app y kallicode_admin_ro tengan denegado UPDATE/DELETE."""
    st = await staff_factory("staff_admin")
    await registrar_accion_staff(
        db,
        staff_id=st["id"],
        staff_role="staff_admin",
        accion="admin_query",
        endpoint="/admin/v1/perms-dml",
        motivo="Comprobacion de privilegios DML revocados",
    )
    await db.commit()

    # 1. Rol kallicode_admin_app
    dsn_app = dsn.replace("postgres:postgres@", "kallicode_admin_app:test@").replace(
        "postgresql://", "postgresql+asyncpg://"
    )
    engine_app = create_async_engine(dsn_app, poolclass=NullPool)
    async with engine_app.connect() as conn_app:
        with pytest.raises(ProgrammingError) as exc_upd:
            await conn_app.execute(
                text(
                    "UPDATE admin.staff_actions "
                    "SET reason = 'hack' WHERE endpoint = '/admin/v1/perms-dml'"
                )
            )
        assert "permission denied for table staff_actions" in str(exc_upd.value).lower()

    async with engine_app.connect() as conn_app:
        with pytest.raises(ProgrammingError) as exc_del:
            await conn_app.execute(
                text("DELETE FROM admin.staff_actions WHERE endpoint = '/admin/v1/perms-dml'")
            )
        assert "permission denied for table staff_actions" in str(exc_del.value).lower()

    await engine_app.dispose()

    # 2. Rol kallicode_admin_ro
    dsn_ro = dsn.replace("postgres:postgres@", "kallicode_admin_ro:test@").replace(
        "postgresql://", "postgresql+asyncpg://"
    )
    engine_ro = create_async_engine(dsn_ro, poolclass=NullPool)
    async with engine_ro.connect() as conn_ro:
        with pytest.raises(ProgrammingError) as exc_ro_upd:
            await conn_ro.execute(
                text(
                    "UPDATE admin.staff_actions "
                    "SET reason = 'hack' WHERE endpoint = '/admin/v1/perms-dml'"
                )
            )
        assert "permission denied for table staff_actions" in str(exc_ro_upd.value).lower()

    async with engine_ro.connect() as conn_ro:
        with pytest.raises(ProgrammingError) as exc_ro_del:
            await conn_ro.execute(
                text("DELETE FROM admin.staff_actions WHERE endpoint = '/admin/v1/perms-dml'")
            )
        assert "permission denied for table staff_actions" in str(exc_ro_del.value).lower()

    await engine_ro.dispose()


# ========================================================= 12. Rango Temporal y Tenant
async def test_verificacion_por_rango_temporal(db: Any, staff_factory: Any) -> None:
    """Verifica la comprobación acotada por rango temporal (desde, hasta)."""
    st = await staff_factory("staff_admin")
    ahora = datetime.now(UTC)
    desde = (ahora - timedelta(days=1)).isoformat()
    hasta = (ahora + timedelta(days=1)).isoformat()

    await registrar_accion_staff(
        db,
        staff_id=st["id"],
        staff_role="staff_admin",
        accion="admin_query",
        endpoint="/admin/v1/rango-temp",
        motivo="Comprobacion en ventana temporal",
    )
    await db.commit()

    res = await recalcular_y_verificar_cadena(db, desde=desde, hasta=hasta)
    assert res.integra is True
    assert res.verificado is True
    assert res.total_roturas == 0

    pasado_desde = (ahora - timedelta(days=30)).isoformat()
    pasado_hasta = (ahora - timedelta(days=29)).isoformat()
    res_vacio = await recalcular_y_verificar_cadena(db, desde=pasado_desde, hasta=pasado_hasta)
    assert res_vacio.integra is True
    assert res_vacio.verificado is True
    assert res_vacio.total_roturas == 0


async def test_verificacion_por_tenant_id(db: Any, staff_factory: Any) -> None:
    """Verifica el filtrado y comprobación criptográfica acotada por tenant_id."""
    st = await staff_factory("staff_soporte")
    sid = st["id"]

    await registrar_accion_staff(
        db,
        staff_id=sid,
        staff_role="staff_soporte",
        accion="read",
        endpoint="/admin/v1/business/customers/org_acme",
        tenant_id="org_acme",
        motivo="Lectura cliente Acme",
        alcance="datos_negocio",
    )
    await registrar_accion_staff(
        db,
        staff_id=sid,
        staff_role="staff_soporte",
        accion="read",
        endpoint="/admin/v1/business/customers/org_globex",
        tenant_id="org_globex",
        motivo="Lectura cliente Globex",
        alcance="datos_negocio",
    )
    await db.commit()

    res_acme = await recalcular_y_verificar_cadena(db, tenant_id="org_acme")
    assert res_acme.integra is True
    assert res_acme.verificado is True
    assert res_acme.total_roturas == 0

    res_globex = await recalcular_y_verificar_cadena(db, tenant_id="org_globex")
    assert res_globex.integra is True
    assert res_globex.verificado is True
    assert res_globex.total_roturas == 0
