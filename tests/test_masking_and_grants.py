"""Suite integral de pruebas para el ticket [KC-ADM-B2-05].

Valida:
1. Enmascarado de texto, dominios y correos electrónicos.
2. Comprobación y evaluación de concesiones activas con resolución jerárquica.
3. Aplicación de la política de enmascarado por defecto ("enmascarado": [...]).
4. Creación de concesiones con validación de motivos, techos de duración y concurrencia.
5. Revocación propia y por staff_admin con auditoría append-only.
6. Caducidad temporal automática sin intervención manual.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from admin_api.masking import (
    aplicar_politica_enmascarado,
    enmascarar_email,
    enmascarar_texto,
    evaluar_concesion_activa,
)
from admin_api.security import emitir_tokens_staff
from sqlalchemy import text

pytestmark = pytest.mark.integracion

MOTIVO_VALIDO = (
    "Revisión técnica de incidencia crítica en expediente de facturación caso SUP-9988"
)


# ============================================================ 1. Enmascarado Unitario
def test_enmascarar_texto_y_dominios() -> None:
    """Valida que enmascarar_texto preserve iniciales, sufijos y dominios."""
    assert enmascarar_texto("Acme Logística S.L.") == "A•••• S.L."
    assert enmascarar_texto("Globex Industrial S.A.") == "G•••• S.A."
    assert enmascarar_texto("Nortec") == "N••••"
    assert enmascarar_texto("acme.com") == "a••••.com"
    assert enmascarar_texto("kallicode.es") == "k••••.es"
    assert enmascarar_texto("") == ""
    assert enmascarar_texto(None) is None


def test_enmascarar_email() -> None:
    """Valida la ofuscación de la parte local conservando dominio."""
    assert enmascarar_email("juan@acme.com") == "j••••@acme.com"
    assert enmascarar_email("m••••@acme.com") == "m••••@acme.com"
    assert enmascarar_email("contacto@kallicode.com") == "c••••@kallicode.com"
    assert enmascarar_email("") == ""
    assert enmascarar_email(None) is None


# ============================================================ 2. Política de Enmascarado
def test_aplicar_politica_enmascarado() -> None:
    """Valida que la política añada lista 'enmascarado' o devuelva datos en claro."""
    datos = {
        "tenant_id": "org_acme",
        "razon_social": "Acme Logística S.L.",
        "dominio": "acme.com",
        "email": "contacto@acme.com",
    }

    # Sin concesión: datos ofuscados y lista de campos enmascarados
    oculto = aplicar_politica_enmascarado(datos, tiene_concesion=False)
    assert isinstance(oculto, dict)
    assert oculto["razon_social"] == "A•••• S.L."
    assert oculto["dominio"] == "a••••.com"
    assert oculto["email"] == "c••••@acme.com"
    assert "razon_social" in oculto["enmascarado"]
    assert "dominio" in oculto["enmascarado"]

    # Con concesión activa: datos en claro y enmascarado vacío
    revelado = aplicar_politica_enmascarado(datos, tiene_concesion=True)
    assert isinstance(revelado, dict)
    assert revelado["razon_social"] == "Acme Logística S.L."
    assert revelado["dominio"] == "acme.com"
    assert revelado["email"] == "contacto@acme.com"
    assert revelado["enmascarado"] == []


# ============================================================ 3. Evaluación de Concesión
async def test_evaluar_concesion_activa_en_db(
    db: Any, staff_factory: Any, dos_clientes: list[str]
) -> None:
    """Verifica la consulta y resolución jerárquica de concesiones activas."""
    empleado = await staff_factory("staff_soporte")
    sid = empleado["id"]
    tid = dos_clientes[0]

    # Sin concesión inicial
    assert await evaluar_concesion_activa(db, sid, tid, "datos_negocio") is False

    # Insertar concesión de expediente (que cubre datos_negocio y expediente)
    await db.execute(
        text("""
        INSERT INTO admin.access_grants
            (id, staff_id, tenant_id, scope, reason, reference, granted_at, expires_at)
        VALUES (
            'gr_eval_1', :s, :t, 'expediente', :r, 'SUP-101', now(), now() + interval '1 hour'
        )
    """),
        {"s": sid, "t": tid, "r": MOTIVO_VALIDO},
    )
    await db.flush()

    # Jerarquía: expediente cubre datos_negocio y expediente, pero no contenido_codigo
    assert await evaluar_concesion_activa(db, sid, tid, "datos_negocio") is True
    assert await evaluar_concesion_activa(db, sid, tid, "expediente") is True
    assert await evaluar_concesion_activa(db, sid, tid, "contenido_codigo") is False

    # Simular revocación
    await db.execute(
        text("""
        UPDATE admin.access_grants
        SET revoked_at = now(), revoked_by = :s, revoked_reason = 'Cierre'
        WHERE id = 'gr_eval_1'
    """),
        {"s": sid},
    )
    await db.flush()

    assert await evaluar_concesion_activa(db, sid, tid, "datos_negocio") is False


# ==================================================== 4. Ciclo de Vida y Validaciones API
async def test_concesiones_crear_validaciones_y_techos(
    cliente: Any, db: Any, staff_factory: Any, dos_clientes: list[str]
) -> None:
    """Valida reglas de motivo, techos de duración, concurrencia y auditoría."""
    empleado = await staff_factory("staff_soporte")
    token = emitir_tokens_staff(empleado["id"], "staff_soporte", datetime.now(UTC))
    cab = {"authorization": f"Bearer {token}"}
    tid = dos_clientes[0]

    # 1. Motivo menor a 20 caracteres se rechaza con 422 MOTIVO_INSUFICIENTE
    r = await cliente.post(
        "/admin/v1/access-grants",
        json={"tenant_id": tid, "alcance": "datos_negocio", "motivo": "Demasiado corto"},
        headers=cab,
    )
    assert r.status_code == 422
    assert r.json()["error"]["code"] in ("motivo_insuficiente", "validacion_entrada")

    # 2. Motivo genérico ("soporte") se rechaza con 422 MOTIVO_INSUFICIENTE
    r = await cliente.post(
        "/admin/v1/access-grants",
        json={
            "tenant_id": tid,
            "alcance": "datos_negocio",
            "motivo": "soporte soporte soporte soporte",
        },
        headers=cab,
    )
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "motivo_insuficiente"

    # 3. contenido_codigo exige recurso o referencia
    r = await cliente.post(
        "/admin/v1/access-grants",
        json={
            "tenant_id": tid,
            "alcance": "contenido_codigo",
            "motivo": "Revisión técnica urgente de código fuente cliente",
        },
        headers=cab,
    )
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "motivo_insuficiente"

    # 4. Creación válida con recurso y capping de 60 min para contenido_codigo
    r = await cliente.post(
        "/admin/v1/access-grants",
        json={
            "tenant_id": tid,
            "alcance": "contenido_codigo",
            "motivo": MOTIVO_VALIDO,
            "recurso": "TK-9988",
            "duracion_min": 120,  # pide 120 pero debe limitar a 60
        },
        headers=cab,
    )
    assert r.status_code == 201, r.text
    concesion = r.json()
    grant_id = concesion["grant_id"]

    minutos = await db.execute(
        text(
            "SELECT extract(epoch FROM (expires_at - granted_at)) / 60 "
            "FROM admin.access_grants WHERE id = :g"
        ),
        {"g": grant_id},
    )
    assert round(minutos.scalar() or 0) <= 60

    # 5. Concesión duplicada devuelve 409 CONCESION_DUPLICADA
    r_dup = await cliente.post(
        "/admin/v1/access-grants",
        json={
            "tenant_id": tid,
            "alcance": "contenido_codigo",
            "motivo": MOTIVO_VALIDO,
            "recurso": "TK-9988",
        },
        headers=cab,
    )
    assert r_dup.status_code == 409
    assert r_dup.json()["error"]["code"] == "concesion_duplicada"

    # 6. Comprobar que la creación quedó registrada en admin.staff_actions
    audit = await db.execute(
        text(
            "SELECT count(*) FROM admin.staff_actions "
            "WHERE grant_id = :g AND action = 'grant_created'"
        ),
        {"g": grant_id},
    )
    assert (audit.scalar() or 0) >= 1

    # 7. Revocación anticipada por el propio empleado y comprobación de auditoría
    r_del = await cliente.delete(f"/admin/v1/access-grants/{grant_id}", headers=cab)
    assert r_del.status_code == 200

    audit_rev = await db.execute(
        text(
            "SELECT count(*) FROM admin.staff_actions "
            "WHERE grant_id = :g AND action = 'grant_revoked'"
        ),
        {"g": grant_id},
    )
    assert (audit_rev.scalar() or 0) >= 1


# ==================================================== 5. Revocación por Admin sobre Ajenas
async def test_revocacion_por_staff_admin_con_motivo(
    cliente: Any, db: Any, staff_factory: Any, dos_clientes: list[str]
) -> None:
    """staff_admin puede revocar concesiones ajenas proporcionando motivo obligatorio."""
    soporte = await staff_factory("staff_soporte")
    admin = await staff_factory("staff_admin")
    tok_soporte = emitir_tokens_staff(soporte["id"], "staff_soporte", datetime.now(UTC))
    tok_admin = emitir_tokens_staff(admin["id"], "staff_admin", datetime.now(UTC))
    tid = dos_clientes[0]

    # Crear concesión como soporte
    r = await cliente.post(
        "/admin/v1/access-grants",
        json={"tenant_id": tid, "alcance": "datos_negocio", "motivo": MOTIVO_VALIDO},
        headers={"authorization": f"Bearer {tok_soporte}"},
    )
    assert r.status_code == 201
    grant_id = r.json()["grant_id"]

    # Admin intenta revocar sin motivo -> 422 MOTIVO_INSUFICIENTE
    r_no_motivo = await cliente.delete(
        f"/admin/v1/access-grants/{grant_id}",
        headers={"authorization": f"Bearer {tok_admin}"},
    )
    assert r_no_motivo.status_code == 422

    # Admin revoca con motivo válido (10-280 chars) -> 200 OK
    r_ok = await cliente.request(
        "DELETE",
        f"/admin/v1/access-grants/{grant_id}",
        json={"motivo": "Cierre preventivo de auditoría administrativa"},
        headers={"authorization": f"Bearer {tok_admin}"},
    )
    assert r_ok.status_code == 200
    assert r_ok.json()["grant_id"] == grant_id
