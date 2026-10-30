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

import time
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import patch

import jwt
import pytest
from admin_api.audit import formatear_nombre_publico
from admin_api.security import _claves
from sqlalchemy import text

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
        text("""
        INSERT INTO admin.access_grants
            (id, staff_id, tenant_id, scope, reason, reference, granted_at, expires_at, reads)
        VALUES (:id, :s, :t, :sc, :rz, :ref, :g_at, :e_at, :reads)
    """),
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
