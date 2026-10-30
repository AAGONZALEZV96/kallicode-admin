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
CLIENTES = ("staff_soporte", "staff_negocio", "staff_admin")
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
    (
        "POST",
        "/admin/v1/staff/invitations",
        ADMIN,
        {
            "email": "nuevo@kallicode.com",
            "rol": "staff_soporte",
            "nota": "Refuerzo del turno de tarde",
        },
    ),
    (
        "PATCH",
        "/admin/v1/staff/st_otro",
        ADMIN,
        {"estado": "suspended", "motivo": "Baja temporal solicitada por su mando"},
    ),
    # --------------------------------------------- §18.13 – §18.15 concesiones
    (
        "POST",
        "/admin/v1/access-grants",
        TODOS,
        {
            "tenant_id": "org_acme",
            "alcance": "expediente",
            "motivo": "El cliente reporta que el gate 2 no avanza en el caso SUP-4471",
            "referencia": "SUP-4471",
            "duracion_min": 30,
        },
    ),
    ("GET", "/admin/v1/access-grants", TODOS, None),
    ("DELETE", "/admin/v1/access-grants/gr_x", TODOS, None),
    # ------------------------------------------------ §18.16 – §18.23 negocio
    ("GET", "/admin/v1/business/overview", NEGOCIO, None),
    ("GET", "/admin/v1/business/customers", CLIENTES, None),
    ("GET", "/admin/v1/business/customers/org_acme", CLIENTES, None),
    ("GET", "/admin/v1/business/subscriptions", NEGOCIO, None),
    ("GET", "/admin/v1/business/upgrade-requests", NEGOCIO, None),
    ("GET", "/admin/v1/business/usage/tokens", NEGOCIO, None),
    (
        "POST",
        "/admin/v1/business/reports",
        NEGOCIO,
        {"tipo": "consumo", "desde": "2026-01-01", "hasta": "2026-01-31", "formato": "csv"},
    ),
    ("GET", "/admin/v1/business/reports/rp_x", TODOS, None),
    # --------------------------------------------- §18.24 – §18.28 operaciones
    ("GET", "/admin/v1/ops/agents", OPS, None),
    ("GET", "/admin/v1/ops/queues", OPS, None),
    ("GET", "/admin/v1/ops/models", OPS_NEGOCIO, None),
    ("GET", "/admin/v1/ops/sla", OPS_NEGOCIO, None),
    ("GET", "/admin/v1/ops/sla/cases/job_x", OPS_NEGOCIO, None),
    # ------------------------------------------- §18.29 – §18.30 auditoría
    ("GET", "/admin/v1/audit/staff-actions", TODOS, None),
    (
        "POST",
        "/admin/v1/audit/staff-actions/exports",
        ADMIN,
        {"desde": "2026-01-01", "hasta": "2026-01-31", "formato": "csv"},
    ),
    # Nota: los cuerpos de esta tabla solo tienen que ser válidos en forma. La
    # puerta de rol se evalúa en las dependencias, antes de validar el cuerpo, así
    # que un 422 posterior no enmascara un 403 que debiera haberse producido.
]


async def _pedir(cliente: Any, metodo: str, ruta: str, cuerpo: dict[str, Any] | None) -> Any:
    if cuerpo is None:
        return await cliente.request(metodo, ruta)
    return await cliente.request(metodo, ruta, json=cuerpo)


# ==================================================================== negativa
COMBINACIONES_NEGATIVAS: list[tuple[str, str, str, dict[str, Any] | None]] = [
    (metodo, ruta, rol, cuerpo)
    for metodo, ruta, permitidos, cuerpo in MATRIZ
    for rol in ROLES
    if rol not in permitidos
]


@pytest.mark.parametrize(
    ("metodo", "ruta", "rol", "cuerpo"),
    COMBINACIONES_NEGATIVAS,
    ids=[f"{m} {r} - {rol}" for m, r, rol, _ in COMBINACIONES_NEGATIVAS],
)
async def test_matriz_autorizacion_negativa_por_rol(
    cliente: Any,
    como: Any,
    sin_limite: None,
    metodo: str,
    ruta: str,
    rol: str,
    cuerpo: dict[str, Any] | None,
) -> None:
    """Ninguna combinación de rol no autorizado puede acceder a endpoints protegidos."""
    como(rol)
    r = await _pedir(cliente, metodo, ruta, cuerpo)
    assert r.status_code == 403, (
        f"{metodo} {ruta} devolvió {r.status_code} al rol {rol}, "
        f"que no está autorizado: {r.text[:300]}"
    )
    cuerpo_err = r.json()
    assert cuerpo_err["error"]["codigo"] == "ROL_STAFF_INSUFICIENTE", cuerpo_err
    assert cuerpo_err["error"]["code"] == "rol_staff_insuficiente", cuerpo_err
    # El mensaje no debe enumerar los roles que sí pueden: eso es un mapa de
    # la organización que el empleado no necesita.
    assert "staff_admin" not in r.text, "el error revela qué roles tienen acceso"


@pytest.mark.parametrize(
    ("metodo", "ruta", "permitidos", "cuerpo"),
    MATRIZ,
    ids=[f"{m}:{r}" for m, r, _, _ in MATRIZ],
)
async def test_rol_no_autorizado_recibe_403(
    cliente: Any,
    como: Any,
    sin_limite: None,
    metodo: str,
    ruta: str,
    permitidos: tuple[str, ...],
    cuerpo: dict[str, Any] | None,
) -> None:
    """Ningún rol fuera de la lista puede llegar al cuerpo del endpoint."""
    for rol in ROLES:
        if rol in permitidos:
            continue
        como(rol)
        r = await _pedir(cliente, metodo, ruta, cuerpo)
        assert r.status_code == 403, (
            f"{metodo} {ruta} devolvió {r.status_code} al rol {rol}, "
            f"que no está autorizado: {r.text[:300]}"
        )
        cuerpo_err = r.json()
        assert cuerpo_err["error"]["codigo"] == "ROL_STAFF_INSUFICIENTE", cuerpo_err
        assert cuerpo_err["error"]["code"] == "rol_staff_insuficiente", cuerpo_err
        # El mensaje no debe enumerar los roles que sí pueden: eso es un mapa de
        # la organización que el empleado no necesita.
        assert "staff_admin" not in r.text, "el error revela qué roles tienen acceso"


@pytest.mark.parametrize(
    ("metodo", "ruta", "permitidos", "cuerpo"),
    MATRIZ,
    ids=[f"{m}:{r}" for m, r, _, _ in MATRIZ],
)
async def test_rol_autorizado_pasa_la_puerta(
    cliente: Any,
    como: Any,
    sin_limite: None,
    metodo: str,
    ruta: str,
    permitidos: tuple[str, ...],
    cuerpo: dict[str, Any] | None,
) -> None:
    """El rol autorizado no recibe 401 ni 403.

    Puede recibir 404, 422 o 503 según el estado de la base y de los agregados;
    lo que se afirma aquí es que la autorización no es la que rechaza.
    """
    for rol in permitidos:
        como(rol)
        r = await _pedir(cliente, metodo, ruta, cuerpo)
        assert r.status_code not in (401, 403), (
            f"{metodo} {ruta} rechazó a {rol}, que sí está autorizado: "
            f"{r.status_code} {r.text[:300]}"
        )


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
        if not camino.startswith("/admin/v1") or camino in (
            "/admin/v1/docs",
            "/admin/v1/openapi.json",
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
            if all(
                c.startswith("{") or c == r for c, r in zip(partes_c, partes_r, strict=True)
            ):
                return (m, camino)
        return (metodo, ruta)

    cubiertos = {patron(m, r) for m, r, _, _ in MATRIZ}
    cubiertos |= {patron(m, r) for m, r in PUBLICOS}

    sin_cubrir = publicados - cubiertos
    assert not sin_cubrir, (
        f"endpoints publicados sin fila en MATRIZ ni en PUBLICOS: {sorted(sin_cubrir)}"
    )

    assert len(publicados) == 31, (
        f"la consola declara 31 endpoints en §18; se publican {len(publicados)}: "
        f"{sorted(publicados)}"
    )


def test_matriz_no_declara_endpoints_inexistentes(app: Any) -> None:
    """Una fila de la matriz que ya no corresponde a ningún endpoint es ruido."""
    caminos = {getattr(r, "path", "") for r in app.routes}
    for _, ruta, _, _ in MATRIZ:
        partes_r = ruta.strip("/").split("/")
        existe = any(
            len(c.strip("/").split("/")) == len(partes_r)
            and all(
                p.startswith("{") or p == q
                for p, q in zip(c.strip("/").split("/"), partes_r, strict=True)
            )
            for c in caminos
        )
        assert existe, f"MATRIZ declara {ruta}, que no está publicado"


def _dependencias_recursivas(dependant: Any) -> set[Any]:
    """Obtiene el conjunto recursivo de funciones dependientes de una ruta."""
    funcs: set[Any] = set()
    if getattr(dependant, "call", None):
        funcs.add(dependant.call)
    for sub in getattr(dependant, "dependencies", []):
        funcs |= _dependencias_recursivas(sub)
    return funcs


def test_todos_los_endpoints_protegidos_tienen_guardas_rbac(app: Any) -> None:
    """Verifica que ningún endpoint protegido se publique sin pasar por staff_actual / RBAC.

    Si alguien añade un endpoint a FastAPI olvidando asignarle una dependencia
    de staff_actual o exigir_rol, este test falla de inmediato.
    """
    from admin_api.deps import staff_actual

    vulnerables: list[str] = []
    for ruta in app.routes:
        camino = getattr(ruta, "path", "")
        if not camino.startswith("/admin/v1") or camino in (
            "/admin/v1/docs",
            "/admin/v1/openapi.json",
        ):
            continue
        metodos = getattr(ruta, "methods", set()) - {"HEAD", "OPTIONS"}
        for m in metodos:
            # Endpoints declarados públicos
            es_publico = any(
                m == pm
                and (
                    camino == pr
                    or (
                        len(camino.strip("/").split("/")) == len(pr.strip("/").split("/"))
                        and all(
                            c.startswith("{") or c == p
                            for c, p in zip(
                                camino.strip("/").split("/"),
                                pr.strip("/").split("/"),
                                strict=True,
                            )
                        )
                    )
                )
                for pm, pr in PUBLICOS
            )
            if es_publico:
                continue

            dependant = getattr(ruta, "dependant", None)
            if dependant is None or staff_actual not in _dependencias_recursivas(dependant):
                vulnerables.append(f"{m} {camino}")

    assert not vulnerables, (
        f"Se encontraron endpoints sin guarda de staff_actual / RBAC: {vulnerables}"
    )


def test_validador_de_guardas_falla_si_se_agrega_endpoint_desprotegido() -> None:
    """Comprueba que si se montara un endpoint sin guarda RBAC, la validación falla."""
    from admin_api.deps import staff_actual
    from fastapi import FastAPI

    app_falsa = FastAPI()

    @app_falsa.get("/admin/v1/test-inseguro")
    async def ruta_insegura() -> dict[str, bool]:
        return {"ok": True}

    ruta_obj = next(
        r for r in app_falsa.routes if getattr(r, "path", "") == "/admin/v1/test-inseguro"
    )
    dependant = getattr(ruta_obj, "dependant", None)
    assert dependant is not None
    assert staff_actual not in _dependencias_recursivas(dependant)


# ================================================== sesión, segundo factor, estado
@pytest.mark.parametrize(
    "ruta_protegida",
    [
        "/admin/v1/staff/me",
        "/admin/v1/staff",
        "/admin/v1/business/overview",
        "/admin/v1/business/customers",
        "/admin/v1/ops/agents",
        "/admin/v1/access-grants",
    ],
)
async def test_sin_credencial_es_401_no_403(cliente: Any, ruta_protegida: str) -> None:
    """Sin cabecera de autorización la respuesta es 401, y sin pistas de rol."""
    r = await cliente.get(ruta_protegida)
    assert r.status_code == 401
    cuerpo = r.json()
    assert cuerpo["error"]["codigo"] in ("TOKEN_INVALIDO", "NO_AUTENTICADO")
    assert cuerpo["error"]["code"] in ("no_autenticado", "token_invalido")


async def test_token_expirado_es_401(cliente: Any) -> None:
    """Un token con exp en el pasado es rechazado con 401."""
    import jwt
    from admin_api.security import _claves
    from admin_api.settings import get_admin_settings

    s = get_admin_settings()
    priv, _ = _claves()
    pasado = datetime.now(UTC) - timedelta(hours=2)
    token_expirado = jwt.encode(
        {
            "sub": "st_testexp",
            "rol": "staff_admin",
            "typ": "staff",
            "mfa": int(pasado.timestamp()),
            "iss": s.jwt_issuer,
            "aud": s.jwt_audience,
            "jti": "jti_expirado",
            "iat": int(pasado.timestamp()),
            "exp": int((pasado + timedelta(minutes=5)).timestamp()),
        },
        priv,
        algorithm="RS256",
    )
    r = await cliente.get(
        "/admin/v1/staff/me", headers={"authorization": f"Bearer {token_expirado}"}
    )
    assert r.status_code == 401
    cuerpo = r.json()
    assert cuerpo["error"]["codigo"] in ("TOKEN_INVALIDO", "NO_AUTENTICADO")


async def test_token_firma_alterada_es_401(cliente: Any, staff_factory: Any) -> None:
    """Un token con la firma alterada es rechazado con 401."""
    from admin_api.security import emitir_tokens_staff

    empleado = await staff_factory("staff_soporte")
    token = emitir_tokens_staff(empleado["id"], "staff_soporte", datetime.now(UTC))
    token_alterado = token[:-8] + "ABCDEFGH"
    r = await cliente.get(
        "/admin/v1/staff/me", headers={"authorization": f"Bearer {token_alterado}"}
    )
    assert r.status_code == 401
    cuerpo = r.json()
    assert cuerpo["error"]["codigo"] in ("TOKEN_INVALIDO", "NO_AUTENTICADO")


async def test_token_firmado_con_otra_clave_es_401(cliente: Any) -> None:
    """Un token firmado con un par de claves no reconocido es rechazado con 401."""
    import jwt
    from admin_api.settings import get_admin_settings
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    s = get_admin_settings()
    clave_ajena = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem_ajena = clave_ajena.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("utf-8")

    ahora = datetime.now(UTC)
    token_ajeno = jwt.encode(
        {
            "sub": "st_hacker",
            "rol": "staff_admin",
            "typ": "staff",
            "mfa": int(ahora.timestamp()),
            "iss": s.jwt_issuer,
            "aud": s.jwt_audience,
            "jti": "jti_hacker",
            "iat": int(ahora.timestamp()),
            "exp": int((ahora + timedelta(minutes=15)).timestamp()),
        },
        pem_ajena,
        algorithm="RS256",
    )
    r = await cliente.get(
        "/admin/v1/staff/me", headers={"authorization": f"Bearer {token_ajeno}"}
    )
    assert r.status_code == 401
    cuerpo = r.json()
    assert cuerpo["error"]["codigo"] in ("TOKEN_INVALIDO", "NO_AUTENTICADO")


@pytest.mark.parametrize(
    "token_basura",
    [
        "esto-no-es-un-jwt",
        "abc.def.ghi",
        "eyJh.eyJ.sig",
    ],
)
async def test_token_malformado_es_401(cliente: Any, token_basura: str) -> None:
    """Cabeceras con tokens malformados retornan 401."""
    r = await cliente.get(
        "/admin/v1/staff/me", headers={"authorization": f"Bearer {token_basura}"}
    )
    assert r.status_code == 401
    cuerpo = r.json()
    assert cuerpo["error"]["codigo"] in ("TOKEN_INVALIDO", "NO_AUTENTICADO")


async def test_token_sin_claim_mfa_es_401(cliente: Any) -> None:
    """Un token sin el claim obligatorio 'mfa' es rechazado con 401."""
    import jwt
    from admin_api.security import _claves
    from admin_api.settings import get_admin_settings

    s = get_admin_settings()
    priv, _ = _claves()
    ahora = datetime.now(UTC)
    token_sin_mfa = jwt.encode(
        {
            "sub": "st_sinmfa",
            "rol": "staff_admin",
            "typ": "staff",
            # 'mfa' omitido
            "iss": s.jwt_issuer,
            "aud": s.jwt_audience,
            "jti": "jti_sin_mfa",
            "iat": int(ahora.timestamp()),
            "exp": int((ahora + timedelta(minutes=15)).timestamp()),
        },
        priv,
        algorithm="RS256",
    )
    r = await cliente.get(
        "/admin/v1/staff/me", headers={"authorization": f"Bearer {token_sin_mfa}"}
    )
    assert r.status_code == 401
    cuerpo = r.json()
    assert cuerpo["error"]["codigo"] in ("TOKEN_INVALIDO", "NO_AUTENTICADO")


async def test_token_con_claim_mfa_invalido_es_401(cliente: Any) -> None:
    """Un token con el claim 'mfa' no numérico es rechazado con 401."""
    import jwt
    from admin_api.security import _claves
    from admin_api.settings import get_admin_settings

    s = get_admin_settings()
    priv, _ = _claves()
    ahora = datetime.now(UTC)
    token_mfa_malo = jwt.encode(
        {
            "sub": "st_mfamalo",
            "rol": "staff_admin",
            "typ": "staff",
            "mfa": "marca_invalida",
            "iss": s.jwt_issuer,
            "aud": s.jwt_audience,
            "jti": "jti_mfa_malo",
            "iat": int(ahora.timestamp()),
            "exp": int((ahora + timedelta(minutes=15)).timestamp()),
        },
        priv,
        algorithm="RS256",
    )
    r = await cliente.get(
        "/admin/v1/staff/me", headers={"authorization": f"Bearer {token_mfa_malo}"}
    )
    assert r.status_code == 401
    cuerpo = r.json()
    assert cuerpo["error"]["codigo"] in ("TOKEN_INVALIDO", "NO_AUTENTICADO")


@pytest.mark.integracion
async def test_token_revocado_global_staff_es_401(cliente: Any, staff_factory: Any) -> None:
    """Revocar globalmente la sesión por admin:staff:{sub}:revoked_at invalida tokens."""
    from admin_api.deps import redis
    from admin_api.security import emitir_tokens_staff

    empleado = await staff_factory("staff_operaciones")
    token = emitir_tokens_staff(empleado["id"], "staff_operaciones", datetime.now(UTC))
    cabeceras = {"authorization": f"Bearer {token}"}

    assert (await cliente.get("/admin/v1/staff/me", headers=cabeceras)).status_code == 200

    # Se simula el corte global en Redis
    corte = int(datetime.now(UTC).timestamp()) + 10
    await redis().set(f"admin:staff:{empleado['id']}:revoked_at", corte, ex=60)

    r = await cliente.get("/admin/v1/staff/me", headers=cabeceras)
    assert r.status_code == 401
    cuerpo = r.json()
    assert cuerpo["error"]["codigo"] in ("TOKEN_INVALIDO", "NO_AUTENTICADO")


async def test_login_credenciales_invalidas_es_401(cliente: Any, sin_limite: None) -> None:
    """Login con contraseña incorrecta devuelve 401 y CREDENCIALES_INVALIDAS."""
    import uuid

    from admin_api.deps import redis

    email = f"err_{uuid.uuid4().hex[:8]}@kallicode.com"
    r = await cliente.post(
        "/admin/v1/auth/login",
        json={"email": email, "password": "Password-Incorrecto-99"},
    )
    assert r.status_code == 401
    cuerpo = r.json()
    assert cuerpo["error"]["codigo"] == "CREDENCIALES_INVALIDAS"
    assert cuerpo["error"]["code"] == "credenciales_invalidas"

    # Limpiar cualquier clave residual de login
    await redis().delete(f"admin:login:{email}:127.0.0.1", f"admin:login:{email}:sin-ip")


async def test_mfa_verify_con_codigo_invalido_es_401(cliente: Any, sin_limite: None) -> None:
    """Verificación de segundo factor con token/código incorrecto devuelve 401."""
    r = await cliente.post(
        "/admin/v1/auth/mfa/verify",
        json={"mfa_token": "mfa_token_invalido_123", "codigo": "000000"},
    )
    assert r.status_code == 401
    cuerpo = r.json()
    assert cuerpo["error"]["codigo"] in ("MFA_INVALIDO", "TOKEN_INVALIDO", "NO_AUTENTICADO")


async def test_token_de_la_api_de_cliente_no_sirve_en_la_consola(cliente: Any) -> None:
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

    r = await cliente.get("/admin/v1/staff/me", headers={"authorization": f"Bearer {acceso}"})
    assert r.status_code == 401


async def test_segundo_factor_caducado_bloquea_datos_de_cliente(
    app: Any, cliente: Any, sin_limite: None
) -> None:
    """Con el segundo factor vencido no se accede a datos de cliente.

    La consola no solo exige TOTP al entrar: exige que la verificación esté
    vigente. Una sesión de ocho horas con un segundo factor de la mañana es una
    sesión sin segundo factor por la tarde.
    """
    from admin_api.deps import Staff, staff_actual

    viejo = Staff(
        id="st_viejo",
        role="staff_admin",
        full_name="Con MFA vencido",
        email="viejo@kallicode.com",
        mfa_at=datetime.now(UTC) - timedelta(hours=12),
        jti="jti_viejo",
        ip="10.0.0.7",
        user_agent="pytest",
        request_id="tr_x",
        grants={},
        grant_detalle={},
    )

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
    cliente: Any, db: Any, staff_factory: Any, estado: str
) -> None:
    """El rol y el estado se resuelven en base, no se leen del token.

    Es el defecto BE-F11 del backend: el rol venía del token, así que degradar a
    alguien no tenía efecto hasta que su token caducaba. Aquí se comprueba lo
    contrario: se emite un token con el empleado activo, se desactiva, y el token
    deja de servir de inmediato.
    """
    from admin_api.security import emitir_tokens_staff
    from sqlalchemy import text

    empleado = await staff_factory("staff_admin")
    acceso = emitir_tokens_staff(empleado["id"], "staff_admin", datetime.now(UTC))
    cabeceras = {"authorization": f"Bearer {acceso}"}

    r = await cliente.get("/admin/v1/staff/me", headers=cabeceras)
    assert r.status_code == 200, r.text

    await db.execute(
        text("UPDATE admin.staff SET status = :e WHERE id = :i"),
        {"e": estado, "i": empleado["id"]},
    )
    await db.commit()

    r = await cliente.get("/admin/v1/staff/me", headers=cabeceras)
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "staff_desactivado"


@pytest.mark.integracion
async def test_degradar_el_rol_tiene_efecto_inmediato(
    cliente: Any, db: Any, staff_factory: Any
) -> None:
    """Bajar de administrador a soporte cierra los endpoints de administración."""
    from admin_api.security import emitir_tokens_staff
    from sqlalchemy import text

    empleado = await staff_factory("staff_admin")
    acceso = emitir_tokens_staff(empleado["id"], "staff_admin", datetime.now(UTC))
    cabeceras = {"authorization": f"Bearer {acceso}"}

    assert (await cliente.get("/admin/v1/staff", headers=cabeceras)).status_code == 200

    await db.execute(
        text("UPDATE admin.staff SET role = 'staff_soporte' WHERE id = :i"),
        {"i": empleado["id"]},
    )
    await db.commit()

    r = await cliente.get("/admin/v1/staff", headers=cabeceras)
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "rol_staff_insuficiente"


@pytest.mark.integracion
async def test_jti_revocado_no_vuelve_a_servir(cliente: Any, staff_factory: Any) -> None:
    """Cerrar sesión invalida el token de acceso, no solo el de refresco."""
    from admin_api.deps import revocar_jti
    from admin_api.security import emitir_tokens_staff, verificar_token_staff

    empleado = await staff_factory("staff_negocio")
    acceso = emitir_tokens_staff(empleado["id"], "staff_negocio", datetime.now(UTC))
    cabeceras = {"authorization": f"Bearer {acceso}"}
    assert (await cliente.get("/admin/v1/staff/me", headers=cabeceras)).status_code == 200

    datos = verificar_token_staff(acceso)
    restante = int(str(datos["exp"])) - int(datetime.now(UTC).timestamp())
    await revocar_jti(str(datos["jti"]), max(restante, 1))

    r = await cliente.get("/admin/v1/staff/me", headers=cabeceras)
    assert r.status_code == 401


# ================================================================ ámbito propio
async def test_ambito_todas_solo_para_administracion(
    cliente: Any, como: Any, sin_limite: None
) -> None:
    """`ambito=todas` en concesiones y auditoría es privilegio de administración.

    Cualquier empleado ve su propio rastro —debe poder auditarse—, pero ver el de
    los demás es supervisión, y la supervisión tiene un rol.
    """
    for ruta in ("/admin/v1/access-grants", "/admin/v1/audit/staff-actions"):
        for rol in ("staff_soporte", "staff_operaciones", "staff_negocio"):
            como(rol)
            r = await cliente.get(ruta, params={"ambito": "todas"})
            assert r.status_code == 403, (
                f"{rol} pudo pedir ambito=todas en {ruta}: {r.status_code}"
            )
            assert r.json()["error"]["code"] == "rol_staff_insuficiente"

        como("staff_admin")
        r = await cliente.get(ruta, params={"ambito": "todas"})
        assert r.status_code not in (401, 403), r.text


async def test_filtrar_por_otro_empleado_exige_ambito_todas(
    cliente: Any, como: Any, sin_limite: None
) -> None:
    """No se puede rodear el ámbito propio filtrando por el id de otro."""
    como("staff_soporte")
    r = await cliente.get("/admin/v1/audit/staff-actions", params={"staff_id": "st_otro"})
    assert r.status_code in (400, 403), r.text


@pytest.mark.integracion
async def test_no_admin_no_puede_revocar_concesion_ajena(
    cliente: Any, db: Any, staff_factory: Any
) -> None:
    """Un empleado no-admin no puede revocar la concesión de otro empleado."""
    from admin_api.security import emitir_tokens_staff
    from kallicode_core.ids import nuevo
    from sqlalchemy import text

    admin_emp = await staff_factory("staff_admin")
    soporte_emp = await staff_factory("staff_soporte")

    gid = nuevo("gr")
    await db.execute(
        text("""
            INSERT INTO admin.access_grants (id, staff_id, tenant_id, scope, reason, expires_at)
            VALUES (:id, :sid, 'org_acme', 'expediente',
                    'Motivo justificado para revision del caso SUP-12345',
                    now() + interval '1 hour')
        """),
        {"id": gid, "sid": admin_emp["id"]},
    )
    await db.commit()

    token_soporte = emitir_tokens_staff(soporte_emp["id"], "staff_soporte", datetime.now(UTC))
    cabeceras = {"authorization": f"Bearer {token_soporte}"}

    # Soporte intenta revocar concesión de admin: denegado por anti-enumeración (404)
    r = await cliente.delete(f"/admin/v1/access-grants/{gid}", headers=cabeceras)
    assert r.status_code == 404, r.text
