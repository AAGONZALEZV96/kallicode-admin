"""Matriz de autorización completa: 31 endpoints × 4 roles.

Esta es la prueba más importante de la consola y la razón es de diseño, no de
cobertura. La consola es la única parte de KalliCode que puede leer datos de todos
los clientes; un endpoint que se publique sin la dependencia de rol correcta
convierte un panel de negocio en una fuga de datos de todos los inquilinos a la
vez. Un fallo aquí no es un error de permisos: es un incidente.

Tres propiedades se comprueban:

  1. **Negativa exhaustiva** — para cada endpoint y cada rol NO autorizado, la
     respuesta es 403. No 200 con lista vacía, no 404, no 500.
  2. **Positiva mínima** — para cada rol autorizado, la respuesta NO es 401 ni 403.
     Puede ser 503 (agregado no disponible) o 422 (falta un parámetro): lo que se
     comprueba es que la puerta de autorización no cierra.
  3. **Cierre de la matriz** — si alguien añade un endpoint y no lo declara en
     `MATRIZ`, la prueba `test_matriz_cubre_todos_los_endpoints` falla. Esto es lo
     que impide que la cobertura se degrade en silencio con el tiempo, que es
     exactamente lo que pasó en el backend: 22 de los 37 defectos son endpoints
     añadidos después de la suite original.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

ROLES = ("staff_soporte", "staff_operaciones", "staff_negocio", "staff_admin")
TODOS = ROLES
NEGOCIO = ("staff_negocio", "staff_admin")
OPS = ("staff_operaciones", "staff_admin")
OPS_NEGOCIO = ("staff_operaciones", "staff_negocio", "staff_admin")
ADMIN = ("staff_admin",)

# Endpoints que no exigen sesión: se prueban en test_auth_flow, no aquí.
PUBLICOS = {
    ("GET", "/admin/v1/health"),
    ("POST", "/admin/v1/auth/login"),
    ("POST", "/admin/v1/auth/mfa/verify"),
    ("POST", "/admin/v1/auth/mfa/enroll"),
    ("POST", "/admin/v1/auth/refresh"),
    ("POST", "/admin/v1/auth/forgot-password"),
    ("POST", "/admin/v1/auth/reset-password"),
    ("POST", "/admin/v1/auth/invitations/accept"),
}

# (método, ruta, roles autorizados, cuerpo mínimo válido en forma)
#
# El cuerpo solo tiene que ser suficiente para pasar la validación de esquema; si
# la petición muere después por falta de datos en base, da igual: la puerta que se
# está probando es la de rol, y esa se evalúa antes del cuerpo del endpoint.
MATRIZ: list[tuple[str, str, tuple[str, ...], dict[str, Any] | None]] = [
    # ---------------------------------------------------------- §18.5 sesión
    ("POST", "/admin/v1/auth/logout", TODOS, {}),

    # ------------------------------------------------ §18.9 – §18.12 personal
    ("GET", "/admin/v1/staff/me", TODOS, None),
    ("GET", "/admin/v1/staff", ADMIN, None),
    ("POST", "/admin/v1/staff/invitations", ADMIN,
     {"email": "nuevo@kallicode.com", "rol": "staff_soporte",
      "nota": "Refuerzo del turno de tarde"}),
    ("PATCH", "/admin/v1/staff/st_otro", ADMIN,
     {"estado": "suspended", "motivo": "Baja temporal solicitada por su mando"}),

    # --------------------------------------------- §18.13 – §18.15 concesiones
    ("POST", "/admin/v1/access-grants", TODOS,
     {"tenant_id": "org_acme", "alcance": "expediente",
      "motivo": "El cliente reporta que el gate 2 no avanza en el caso SUP-4471",
      "referencia": "SUP-4471", "duracion_min": 30}),
    ("GET", "/admin/v1/access-grants", TODOS, None),
    ("DELETE", "/admin/v1/access-grants/gr_x", TODOS, None),

    # ------------------------------------------------ §18.16 – §18.23 negocio
    ("GET", "/admin/v1/business/overview", NEGOCIO, None),
    ("GET", "/admin/v1/business/customers", TODOS, None),
    ("GET", "/admin/v1/business/customers/org_acme", TODOS, None),
    ("GET", "/admin/v1/business/subscriptions", NEGOCIO, None),
    ("GET", "/admin/v1/business/upgrade-requests", NEGOCIO, None),
    ("GET", "/admin/v1/business/usage/tokens", NEGOCIO, None),
    ("POST", "/admin/v1/business/reports", NEGOCIO,
     {"tipo": "consumo", "desde": "2026-01-01", "hasta": "2026-01-31",
      "formato": "csv"}),
    ("GET", "/admin/v1/business/reports/rp_x", TODOS, None),

    # --------------------------------------------- §18.24 – §18.28 operaciones
    ("GET", "/admin/v1/ops/agents", OPS, None),
    ("GET", "/admin/v1/ops/queues", OPS, None),
    ("GET", "/admin/v1/ops/models", OPS_NEGOCIO, None),
    ("GET", "/admin/v1/ops/sla", OPS_NEGOCIO, None),
    ("GET", "/admin/v1/ops/sla/cases/job_x", OPS_NEGOCIO, None),

    # ------------------------------------------- §18.29 – §18.30 auditoría
    ("GET", "/admin/v1/audit/staff-actions", TODOS, None),
    ("POST", "/admin/v1/audit/staff-actions/exports", ADMIN,
     {"desde": "2026-01-01", "hasta": "2026-01-31", "formato": "csv"}),
    # Nota: los cuerpos de esta tabla solo tienen que ser válidos en forma. La
    # puerta de rol se evalúa en las dependencias, antes de validar el cuerpo, así
    # que un 422 posterior no enmascara un 403 que debiera haberse producido.
]


async def _pedir(cliente: Any, metodo: str, ruta: str,
                 cuerpo: dict[str, Any] | None) -> Any:
    if cuerpo is None:
        return await cliente.request(metodo, ruta)
    return await cliente.request(metodo, ruta, json=cuerpo)


# ==================================================================== negativa
@pytest.mark.parametrize(("metodo", "ruta", "permitidos", "cuerpo"), MATRIZ,
                         ids=[f"{m}:{r}" for m, r, _, _ in MATRIZ])
async def test_rol_no_autorizado_recibe_403(
        cliente: Any, como: Any, sin_limite: None,
        metodo: str, ruta: str, permitidos: tuple[str, ...],
        cuerpo: dict[str, Any] | None) -> None:
    """Ningún rol fuera de la lista puede llegar al cuerpo del endpoint."""
    for rol in ROLES:
        if rol in permitidos:
            continue
        como(rol)
        r = await _pedir(cliente, metodo, ruta, cuerpo)
        assert r.status_code == 403, (
            f"{metodo} {ruta} devolvió {r.status_code} al rol {rol}, "
            f"que no está autorizado: {r.text[:300]}")
        cuerpo_err = r.json()
        assert cuerpo_err["error"]["code"] == "rol_staff_insuficiente", cuerpo_err
        # El mensaje no debe enumerar los roles que sí pueden: eso es un mapa de
        # la organización que el empleado no necesita.
        assert "staff_admin" not in r.text, (
            "el error revela qué roles tienen acceso")


@pytest.mark.parametrize(("metodo", "ruta", "permitidos", "cuerpo"), MATRIZ,
                         ids=[f"{m}:{r}" for m, r, _, _ in MATRIZ])
async def test_rol_autorizado_pasa_la_puerta(
        cliente: Any, como: Any, sin_limite: None,
        metodo: str, ruta: str, permitidos: tuple[str, ...],
        cuerpo: dict[str, Any] | None) -> None:
    """El rol autorizado no recibe 401 ni 403.

    Puede recibir 404, 422 o 503 según el estado de la base y de los agregados;
    lo que se afirma aquí es que la autorización no es la que rechaza.
    """
    for rol in permitidos:
        como(rol)
        r = await _pedir(cliente, metodo, ruta, cuerpo)
        assert r.status_code not in (401, 403), (
            f"{metodo} {ruta} rechazó a {rol}, que sí está autorizado: "
            f"{r.status_code} {r.text[:300]}")


# ============================================================ cierre de matriz
def test_matriz_cubre_todos_los_endpoints(app: Any) -> None:
    """Todo endpoint publicado está en `MATRIZ` o declarado público.

    Añadir un endpoint sin declararlo aquí rompe la suite a propósito. Es la única
    barrera estructural contra el patrón que produjo la mayoría de los defectos
    del backend: endpoints nuevos sobre una suite que ya no los alcanza.
    """
    publicados: set[tuple[str, str]] = set()
    for ruta in app.routes:
        camino = getattr(ruta, "path", "")
        if (
            not camino.startswith("/admin/v1")
            or camino in ("/admin/v1/docs", "/admin/v1/openapi.json")
        ):
            continue
        for metodo in getattr(ruta, "methods", set()) - {"HEAD", "OPTIONS"}:
            publicados.add((metodo, camino))

    # Las rutas de la matriz llevan valores concretos donde el endpoint declara
    # parámetros; se normalizan al patrón para poder comparar.
    def patron(metodo: str, ruta: str) -> tuple[str, str]:
        for m, camino in publicados:
            if m != metodo:
                continue
            partes_c = camino.strip("/").split("/")
            partes_r = ruta.strip("/").split("/")
            if len(partes_c) != len(partes_r):
                continue
            if all(c.startswith("{") or c == r
                   for c, r in zip(partes_c, partes_r, strict=True)):
                return (m, camino)
        return (metodo, ruta)

    cubiertos = {patron(m, r) for m, r, _, _ in MATRIZ}
    cubiertos |= {patron(m, r) for m, r in PUBLICOS}

    sin_cubrir = publicados - cubiertos
    assert not sin_cubrir, (
        "endpoints publicados sin fila en MATRIZ ni en PUBLICOS: "
        f"{sorted(sin_cubrir)}")

    assert len(publicados) == 31, (
        f"la consola declara 31 endpoints en §18; se publican {len(publicados)}: "
        f"{sorted(publicados)}")


def test_matriz_no_declara_endpoints_inexistentes(app: Any) -> None:
    """Una fila de la matriz que ya no corresponde a ningún endpoint es ruido."""
    caminos = {getattr(r, "path", "") for r in app.routes}
    for _, ruta, _, _ in MATRIZ:
        partes_r = ruta.strip("/").split("/")
        existe = any(
            len(c.strip("/").split("/")) == len(partes_r)
            and all(p.startswith("{") or p == q
                    for p, q in zip(c.strip("/").split("/"), partes_r,
                                    strict=True))
            for c in caminos)
        assert existe, f"MATRIZ declara {ruta}, que no está publicado"


# ================================================== sesión, segundo factor, estado
async def test_sin_credencial_es_401_no_403(cliente: Any) -> None:
    """Sin cabecera de autorización la respuesta es 401, y sin pistas de rol."""
    r = await cliente.get("/admin/v1/staff/me")
    assert r.status_code == 401
    assert r.json()["error"]["code"] in ("no_autenticado", "token_invalido")


async def test_token_de_la_api_de_cliente_no_sirve_en_la_consola(
        cliente: Any) -> None:
    """Un token del portal no abre la consola: distinto emisor y audiencia.

    La consola emite con `iss`/`aud` propios y `typ=staff`. Aceptar un token de
    cliente sería el peor de los errores posibles: un usuario del portal
    consultando datos de todos los inquilinos.
    """
    from admin_api.security import verificar_token_staff
    from kallicode_core.seguridad import emitir_access_token

    acceso = emitir_access_token("usr_cliente", "org_acme", "owner")
    with pytest.raises(Exception):  # noqa: B017 — cualquier rechazo es válido
        verificar_token_staff(acceso)

    r = await cliente.get("/admin/v1/staff/me",
                          headers={"authorization": f"Bearer {acceso}"})
    assert r.status_code == 401


async def test_segundo_factor_caducado_bloquea_datos_de_cliente(
        app: Any, cliente: Any, sin_limite: None) -> None:
    """Con el segundo factor vencido no se accede a datos de cliente.

    La consola no solo exige TOTP al entrar: exige que la verificación esté
    vigente. Una sesión de ocho horas con un segundo factor de la mañana es una
    sesión sin segundo factor por la tarde.
    """
    from admin_api.deps import Staff, staff_actual

    viejo = Staff(
        id="st_viejo", role="staff_admin", full_name="Con MFA vencido",
        email="viejo@kallicode.com",
        mfa_at=datetime.now(UTC) - timedelta(hours=12),
        jti="jti_viejo", ip="10.0.0.7", user_agent="pytest",
        request_id="tr_x", grants={}, grant_detalle={})

    async def _override() -> Staff:
        return viejo

    app.dependency_overrides[staff_actual] = _override
    try:
        r = await cliente.get("/admin/v1/business/customers")
        assert r.status_code == 403
        assert r.json()["error"]["code"] == "mfa_requerido"
    finally:
        app.dependency_overrides.clear()


@pytest.mark.integracion
@pytest.mark.parametrize("estado", ["suspended", "disabled"])
async def test_empleado_desactivado_no_pasa_aunque_el_token_siga_vivo(
        cliente: Any, db: Any, staff_factory: Any, estado: str) -> None:
    """El rol y el estado se resuelven en base, no se leen del token.

    Es el defecto BE-F11 del backend: el rol venía del token, así que degradar a
    alguien no tenía efecto hasta que su token caducaba. Aquí se comprueba lo
    contrario: se emite un token con el empleado activo, se desactiva, y el token
    deja de servir de inmediato.
    """
    from admin_api.security import emitir_tokens_staff
    from sqlalchemy import text

    empleado = await staff_factory("staff_admin")
    acceso = emitir_tokens_staff(empleado["id"], "staff_admin",
                                 datetime.now(UTC))
    cabeceras = {"authorization": f"Bearer {acceso}"}

    r = await cliente.get("/admin/v1/staff/me", headers=cabeceras)
    assert r.status_code == 200, r.text

    await db.execute(text("UPDATE admin.staff SET status = :e WHERE id = :i"),
                     {"e": estado, "i": empleado["id"]})
    await db.commit()

    r = await cliente.get("/admin/v1/staff/me", headers=cabeceras)
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "staff_desactivado"


@pytest.mark.integracion
async def test_degradar_el_rol_tiene_efecto_inmediato(
        cliente: Any, db: Any, staff_factory: Any) -> None:
    """Bajar de administrador a soporte cierra los endpoints de administración."""
    from admin_api.security import emitir_tokens_staff
    from sqlalchemy import text

    empleado = await staff_factory("staff_admin")
    acceso = emitir_tokens_staff(empleado["id"], "staff_admin",
                                 datetime.now(UTC))
    cabeceras = {"authorization": f"Bearer {acceso}"}

    assert (await cliente.get("/admin/v1/staff",
                              headers=cabeceras)).status_code == 200

    await db.execute(
        text("UPDATE admin.staff SET role = 'staff_soporte' WHERE id = :i"),
        {"i": empleado["id"]})
    await db.commit()

    r = await cliente.get("/admin/v1/staff", headers=cabeceras)
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "rol_staff_insuficiente"


@pytest.mark.integracion
async def test_jti_revocado_no_vuelve_a_servir(
        cliente: Any, staff_factory: Any) -> None:
    """Cerrar sesión invalida el token de acceso, no solo el de refresco."""
    from admin_api.deps import revocar_jti
    from admin_api.security import emitir_tokens_staff, verificar_token_staff

    empleado = await staff_factory("staff_negocio")
    acceso = emitir_tokens_staff(empleado["id"], "staff_negocio",
                                 datetime.now(UTC))
    cabeceras = {"authorization": f"Bearer {acceso}"}
    assert (await cliente.get("/admin/v1/staff/me",
                              headers=cabeceras)).status_code == 200

    datos = verificar_token_staff(acceso)
    restante = int(str(datos["exp"])) - int(datetime.now(UTC).timestamp())
    await revocar_jti(str(datos["jti"]), max(restante, 1))

    r = await cliente.get("/admin/v1/staff/me", headers=cabeceras)
    assert r.status_code == 401


# ================================================================ ámbito propio
async def test_ambito_todas_solo_para_administracion(
        cliente: Any, como: Any, sin_limite: None) -> None:
    """`ambito=todas` en concesiones y auditoría es privilegio de administración.

    Cualquier empleado ve su propio rastro —debe poder auditarse—, pero ver el de
    los demás es supervisión, y la supervisión tiene un rol.
    """
    for ruta in ("/admin/v1/access-grants", "/admin/v1/audit/staff-actions"):
        for rol in ("staff_soporte", "staff_operaciones", "staff_negocio"):
            como(rol)
            r = await cliente.get(ruta, params={"ambito": "todas"})
            assert r.status_code == 403, (
                f"{rol} pudo pedir ambito=todas en {ruta}: {r.status_code}")
            assert r.json()["error"]["code"] == "rol_staff_insuficiente"

        como("staff_admin")
        r = await cliente.get(ruta, params={"ambito": "todas"})
        assert r.status_code not in (401, 403), r.text


async def test_filtrar_por_otro_empleado_exige_ambito_todas(
        cliente: Any, como: Any, sin_limite: None) -> None:
    """No se puede rodear el ámbito propio filtrando por el id de otro."""
    como("staff_soporte")
    r = await cliente.get("/admin/v1/audit/staff-actions",
                          params={"staff_id": "st_otro"})
    assert r.status_code in (400, 403), r.text
