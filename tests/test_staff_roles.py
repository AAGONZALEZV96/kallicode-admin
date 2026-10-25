"""Pruebas del Catálogo de Roles de Staff y Matriz de Permisos (Ticket KC-ADM-B1-09).

Verifica:
  1. Catálogo formal de los 4 roles canónicos:
     - staff_soporte
     - staff_operaciones
     - staff_negocio
     - staff_admin
  2. Catálogo canónico de permisos y su resolución en GET /admin/v1/staff/me.
  3. Comportamiento estricto de HTTP 403 Forbidden y sobre ROL_STAFF_INSUFICIENTE
     ante accesos fuera de rol.
  4. Funcionamiento unitario de las dependencias exigir_rol y exigir_permiso en deps.py.
  5. Separación de responsabilidades: soporte no accede a métricas de negocio ni ops;
     ops no accede a datos comerciales ni clientes; negocio no accede a telemetría de
     infraestructura; admin es el único autorizado para gobernar personal y exportar auditoría.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from admin_api.deps import Staff, exigir_permiso, exigir_rol
from admin_api.security import PERMISOS_ROL, STAFF_ROLES
from kallicode_core.errors import AppError


# ==================================================================== 1. Catálogo
def test_catalogo_cuatro_roles_definidos() -> None:
    """STAFF_ROLES debe contener exactamente los cuatro roles canónicos de KalliCode."""
    esperados = {"staff_soporte", "staff_operaciones", "staff_negocio", "staff_admin"}
    assert set(STAFF_ROLES) == esperados
    assert len(STAFF_ROLES) == 4


def test_catalogo_permisos_canonicos_completitud() -> None:
    """PERMISOS_ROL debe contener los permisos clave del catálogo para cada rol."""
    # Permisos clave exigidos en la especificación
    permisos_clave = {
        "negocio.overview.leer",
        "negocio.clientes.leer",
        "ops.telemetria.leer",
        "personal.gestionar",
        "auditoria.total.leer",
    }

    todos_los_permisos: set[str] = set()
    for rol in STAFF_ROLES:
        assert rol in PERMISOS_ROL, f"El rol {rol} no tiene permisos definidos"
        perms = PERMISOS_ROL[rol]
        assert isinstance(perms, tuple)
        assert len(perms) > 0
        todos_los_permisos.update(perms)

    for p in permisos_clave:
        assert p in todos_los_permisos, f"El permiso canónico {p} falta en el catálogo"

    # Soporte nunca debe tener negocio.overview, ops.telemetria ni personal
    soporte_perms = set(PERMISOS_ROL["staff_soporte"])
    assert "negocio.overview.leer" not in soporte_perms
    assert "ops.telemetria.leer" not in soporte_perms
    assert "personal.gestionar" not in soporte_perms
    assert "negocio.clientes.leer" in soporte_perms
    assert "expediente.leer" in soporte_perms

    # Operaciones no debe tener negocio.overview, clientes ni personal
    ops_perms = set(PERMISOS_ROL["staff_operaciones"])
    assert "negocio.overview.leer" not in ops_perms
    assert "negocio.clientes.leer" not in ops_perms
    assert "personal.gestionar" not in ops_perms
    assert "ops.telemetria.leer" in ops_perms
    assert "ops.sla.leer" in ops_perms

    # Negocio no debe tener ops.telemetria.leer ni personal.gestionar
    negocio_perms = set(PERMISOS_ROL["staff_negocio"])
    assert "ops.telemetria.leer" not in negocio_perms
    assert "ops.colas.leer" not in negocio_perms
    assert "personal.gestionar" not in negocio_perms
    assert "negocio.overview.leer" in negocio_perms
    assert "negocio.clientes.leer" in negocio_perms

    # Admin debe tener el superconjunto incluyendo gestión de personal y auditoría total
    admin_perms = set(PERMISOS_ROL["staff_admin"])
    assert "personal.gestionar" in admin_perms
    assert "personal.leer" in admin_perms
    assert "auditoria.total.leer" in admin_perms
    assert "auditoria.exportar" in admin_perms
    assert "concesiones.todas" in admin_perms
    assert "concesiones.revocar_ajenas" in admin_perms


# ============================================================= 2. GET /staff/me
@pytest.mark.parametrize("rol", STAFF_ROLES)
async def test_staff_me_devuelve_permisos_segun_rol(
    cliente: Any, como: Any, sin_limite: None, rol: str
) -> None:
    """GET /admin/v1/staff/me debe devolver la lista exacta y ordenada de permisos del rol."""
    como(rol)
    r = await cliente.get("/admin/v1/staff/me")
    assert r.status_code == 200, f"Error en /staff/me para rol {rol}: {r.text}"
    cuerpo = r.json()

    assert cuerpo["rol"] == rol
    assert cuerpo["email"] == f"{rol}@kallicode.com"
    assert "permisos" in cuerpo

    esperados = sorted(PERMISOS_ROL[rol])
    assert cuerpo["permisos"] == esperados


# =================================================== 3. Rechazo 403 estricto
@pytest.mark.parametrize(
    ("rol", "metodo", "ruta", "cuerpo"),
    [
        # Soporte intenta ver agregados de negocio -> 403
        ("staff_soporte", "GET", "/admin/v1/business/overview", None),
        # Soporte intenta gestionar personal -> 403
        ("staff_soporte", "GET", "/admin/v1/staff", None),
        # Soporte intenta ver agentes de operaciones -> 403
        ("staff_soporte", "GET", "/admin/v1/ops/agents", None),
        # Soporte intenta exportar auditoría -> 403
        (
            "staff_soporte",
            "POST",
            "/admin/v1/audit/staff-actions/exports",
            {"desde": "2026-01-01", "hasta": "2026-01-31", "formato": "csv"},
        ),
        # Operaciones intenta ver agregados comerciales -> 403
        ("staff_operaciones", "GET", "/admin/v1/business/overview", None),
        # Operaciones intenta ver suscripciones de clientes -> 403
        ("staff_operaciones", "GET", "/admin/v1/business/subscriptions", None),
        # Operaciones intenta ver consumo de tokens de negocio -> 403
        ("staff_operaciones", "GET", "/admin/v1/business/usage/tokens", None),
        # Operaciones intenta gestionar personal -> 403
        ("staff_operaciones", "GET", "/admin/v1/staff", None),
        # Negocio intenta ver agentes de infraestructura -> 403
        ("staff_negocio", "GET", "/admin/v1/ops/agents", None),
        # Negocio intenta inspeccionar colas -> 403
        ("staff_negocio", "GET", "/admin/v1/ops/queues", None),
        # Negocio intenta gestionar personal -> 403
        ("staff_negocio", "GET", "/admin/v1/staff", None),
    ],
)
async def test_endpoint_fuera_de_rol_responde_403_con_sobre_estandarizado(
    cliente: Any,
    como: Any,
    sin_limite: None,
    rol: str,
    metodo: str,
    ruta: str,
    cuerpo: dict[str, Any] | None,
) -> None:
    """Cualquier acceso fuera de rol responde HTTP 403 con sobre ROL_STAFF_INSUFICIENTE."""
    como(rol)
    if cuerpo is not None:
        r = await cliente.request(metodo, ruta, json=cuerpo)
    else:
        r = await cliente.request(metodo, ruta)

    assert r.status_code == 403, (
        f"Se esperaba 403 para {rol} en {metodo} {ruta}, se obtuvo {r.status_code}: {r.text}"
    )

    resp = r.json()
    assert "error" in resp, f"Falta el sobre de error: {resp}"
    err = resp["error"]
    assert err["codigo"] == "ROL_STAFF_INSUFICIENTE"
    assert err["code"] == "rol_staff_insuficiente"
    assert err["mensaje"] == "Tu rol no permite esta operación."
    assert "trace_id" in err


# ================================================== 4. Unitarias de dependencias
async def test_dependencia_exigir_rol_unitaria() -> None:
    """exigir_rol permite roles autorizados y rechaza con ROL_STAFF_INSUFICIENTE."""
    guard = exigir_rol("staff_admin", "staff_negocio")

    staff_valido = Staff(
        id="st_01",
        role="staff_negocio",
        full_name="Staff Negocio",
        email="negocio@kallicode.com",
        mfa_at=datetime.now(UTC),
        jti="jti_01",
        ip="127.0.0.1",
        user_agent="pytest",
        request_id="tr_01",
    )

    # Debe pasar sin excepción
    res = await guard(staff_valido)
    assert res.id == "st_01"

    staff_invalido = Staff(
        id="st_02",
        role="staff_soporte",
        full_name="Staff Soporte",
        email="soporte@kallicode.com",
        mfa_at=datetime.now(UTC),
        jti="jti_02",
        ip="127.0.0.1",
        user_agent="pytest",
        request_id="tr_02",
    )

    with pytest.raises(AppError) as exc_info:
        await guard(staff_invalido)

    err = exc_info.value
    assert err.codigo == "ROL_STAFF_INSUFICIENTE"
    assert err.http == 403
    assert err.mensaje == "Tu rol no permite esta operación."


async def test_dependencia_exigir_permiso_unitaria() -> None:
    """exigir_permiso debe verificar los permisos canónicos derivados del rol del empleado."""
    guard = exigir_permiso("personal.gestionar")

    staff_admin = Staff(
        id="st_adm",
        role="staff_admin",
        full_name="Staff Admin",
        email="admin@kallicode.com",
        mfa_at=datetime.now(UTC),
        jti="jti_adm",
        ip="127.0.0.1",
        user_agent="pytest",
        request_id="tr_adm",
    )

    # staff_admin posee 'personal.gestionar' -> éxito
    res = await guard(staff_admin)
    assert res.id == "st_adm"

    staff_soporte = Staff(
        id="st_sop",
        role="staff_soporte",
        full_name="Staff Soporte",
        email="soporte@kallicode.com",
        mfa_at=datetime.now(UTC),
        jti="jti_sop",
        ip="127.0.0.1",
        user_agent="pytest",
        request_id="tr_sop",
    )

    # staff_soporte NO posee 'personal.gestionar' -> 403
    with pytest.raises(AppError) as exc_info:
        await guard(staff_soporte)

    err = exc_info.value
    assert err.codigo == "ROL_STAFF_INSUFICIENTE"
    assert err.http == 403
    assert err.mensaje == "Tu rol no permite esta operación."


# ========================================= 5. Autorización específica por rol
async def test_soporte_y_negocio_acceden_a_clientes_y_operaciones_bloqueado_en_suscripciones(
    cliente: Any, como: Any, sin_limite: None
) -> None:
    """Soporte y negocio consultan clientes; operaciones está bloqueado en suscripciones."""
    for rol in ("staff_soporte", "staff_negocio", "staff_admin"):
        como(rol)
        r = await cliente.get("/admin/v1/business/customers")
        # No debe ser 403 de autorización
        assert r.status_code != 403, f"{rol} fue rechazado indebidamente en customers: {r.text}"

    # Operaciones no está autorizado para ver suscripciones comerciales
    como("staff_operaciones")
    r_ops = await cliente.get("/admin/v1/business/subscriptions")
    assert r_ops.status_code == 403
    assert r_ops.json()["error"]["codigo"] == "ROL_STAFF_INSUFICIENTE"


async def test_admin_super_rol_accede_a_todas_las_superficies(
    cliente: Any, como: Any, sin_limite: None
) -> None:
    """staff_admin puede atravesar las puertas de negocio, ops, personal y auditoría."""
    como("staff_admin")

    rutas = [
        ("GET", "/admin/v1/business/overview"),
        ("GET", "/admin/v1/business/customers"),
        ("GET", "/admin/v1/ops/agents"),
        ("GET", "/admin/v1/ops/queues"),
        ("GET", "/admin/v1/ops/models"),
        ("GET", "/admin/v1/staff"),
        ("GET", "/admin/v1/audit/staff-actions"),
    ]

    for metodo, ruta in rutas:
        r = await cliente.request(metodo, ruta)
        assert r.status_code != 403, (
            f"staff_admin fue rechazado indebidamente con 403 en {metodo} {ruta}: {r.text}"
        )
