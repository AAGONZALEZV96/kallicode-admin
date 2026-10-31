"""Pruebas E2E automatizadas de exposición mínima de datos y no-fuga por rol (KC-ADM-B3-07).

Épica EAD3: Auditoría y Gobierno del Acceso del Personal (ADM-G09 / §18.18).

Garantiza de forma inmutable y determinista que:
1. Inspección recursiva de payloads JSON (200, 201, 403, 404, 422, 503):
   - Cero secretos internos: hashes Argon2id/bcrypt/PBKDF2, tokens JWT indebidos,
     cadenas de conexión DSN (PostgreSQL/Redis), claves privadas y campos prohibidos.
   - Cero trazas de depuración, nombres de excepciones Python ni tablas internas.
2. Enmascaramiento obligatorio por defecto sin concesión activa:
   - Toda información PII (razón social, dominio, email) se ofusca con viñetas ('•').
   - El payload declara explícitamente el enmascaramiento ('enmascarado': true o lista).
3. Revelación granular y selectiva fila por fila ante concesiones activas:
   - Solo la organización con concesión temporal vigente se expone en claro.
   - Organizaciones sin concesión permanecen estrictamente ofuscadas en la respuesta.
4. Cumplimiento estricto de mínimo privilegio por rol:
   - staff_operaciones: 403 determinista en negocio/clientes/staff; 200 en operaciones
     sin PII ni indicadores comerciales agregados (MRR).
   - staff_soporte: 403 en negocio global y operaciones infra; 200 en clientes con PII.
   - staff_negocio: 403 en colas/agentes y administración de personal; 200 en negocio.
   - staff_admin: acceso autorizado amplio pero con enmascaramiento por defecto.
5. Sanitización de manejadores de error:
   - Sobre canónico estandarizado con 'codigo', 'code', 'mensaje' y 'trace_id'.
   - Cabecera 'X-Trace-Id' presente y consistente.
   - Ausencia total de sentencias SQL, esquemas de base de datos o rutas de sistema.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any

import pytest
import pytest_asyncio
import respx
from admin_api.settings import get_admin_settings
from admin_workers.main import refrescar_agregados
from httpx import Response
from sqlalchemy import text

pytestmark = [pytest.mark.integracion, pytest.mark.asyncio]

# ==============================================================================
# Reglas y Patrones de Seguridad para Detección de Fugas
# ==============================================================================

CLAVES_SECRETAS_PROHIBIDAS: set[str] = {
    "password",
    "password_hash",
    "contrasena",
    "totp_secret",
    "secret_key",
    "api_key",
    "dsn",
    "database_url",
    "private_key",
    "jwt_secret",
    "auth_token",
}

# Tokens JWT completos (header.payload.signature)
PATRON_JWT = re.compile(r"^eyJ[a-zA-Z0-9_-]{10,}\.eyJ[a-zA-Z0-9_-]{10,}\.[a-zA-Z0-9_-]{10,}$")

# Hashes criptográficos (Argon2id, bcrypt, PBKDF2)
PATRON_HASH = re.compile(r"\$(?:argon2id|argon2i|2b|2a|pbkdf2)\$")

# Cadenas DSN de conexión a bases de datos o brokers
PATRON_DSN = re.compile(
    r"(?:postgres(?:ql)?(?:\+[a-z0-9_-]+)?|redis(?:s)?)://[a-zA-Z0-9_:@./-]+"
)

# Bloques de certificados o claves privadas
PATRON_PRIVATE_KEY = re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")

# Tablas o esquemas internos cuya existencia o contenido nunca debe filtrarse
PATRON_TABLAS_PROHIBIDAS = re.compile(
    r"\b(?:core\.users|core\.password_reset_tokens|core\.refresh_tokens|admin\.staff_secrets)\b",
    re.IGNORECASE,
)

# Nombres de excepciones Python o trazas de depuración
PATRON_EXCEPCIONES = re.compile(
    r"(?:Traceback \(most recent call last\)|SQLAlchemyError|OperationalError|"
    r"ProgrammingError|IntegrityError|AttributeError|KeyError)"
)

# Fragmentos de consultas SQL
PATRON_SQL_SNIPPET = re.compile(
    r"\b(?:SELECT\s+.+\s+FROM|INSERT\s+INTO|UPDATE\s+\w+\s+SET|DELETE\s+FROM)\b",
    re.IGNORECASE,
)

# Rutas internas de archivos de código en servidor
PATRON_RUTA_INTERNA = re.compile(r"/(?:home|usr|app|src)/[a-zA-Z0-9_/.-]+\.py")


def inspeccionar_payload_recursivo(
    data: Any, path: str = "$", permitir_jwt: bool = False
) -> None:
    """Inspecciona recursivamente estructuras JSON verificando ausencia de secretos."""
    if isinstance(data, dict):
        for k, v in data.items():
            curr_path = f"{path}.{k}"
            clave_lower = str(k).lower()

            # Comprobar claves prohibidas
            for prohibida in CLAVES_SECRETAS_PROHIBIDAS:
                if clave_lower == prohibida or clave_lower.endswith(f"_{prohibida}"):
                    if clave_lower not in ("mfa_inscrito",):
                        raise AssertionError(
                            f"Clave secreta prohibida detectada en '{curr_path}': '{k}'"
                        )

            inspeccionar_payload_recursivo(v, curr_path, permitir_jwt=permitir_jwt)

    elif isinstance(data, list):
        for idx, item in enumerate(data):
            inspeccionar_payload_recursivo(item, f"{path}[{idx}]", permitir_jwt=permitir_jwt)

    elif isinstance(data, str):
        val = data.strip()
        if not permitir_jwt and PATRON_JWT.match(val):
            raise AssertionError(
                f"Token JWT no autorizado detectado en '{path}': '{val[:20]}...'"
            )
        if PATRON_HASH.search(val):
            raise AssertionError(f"Hash criptográfico detectado en '{path}': '{val[:25]}...'")
        if PATRON_DSN.search(val):
            raise AssertionError(f"Cadena de conexión DSN detectada en '{path}': '{val}'")
        if PATRON_PRIVATE_KEY.search(val):
            raise AssertionError(f"Clave privada detectada en '{path}'")
        if PATRON_TABLAS_PROHIBIDAS.search(val):
            raise AssertionError(f"Tabla interna no autorizada en '{path}': '{val}'")
        if PATRON_EXCEPCIONES.search(val):
            raise AssertionError(f"Excepción o traza de error detectada en '{path}': '{val}'")


def verificar_enmascaramiento_cliente(
    cliente_data: dict[str, Any], esperado_enmascarado: bool
) -> None:
    """Valida el cumplimiento estricto de la política de ofuscación de PII."""
    rs = cliente_data.get("razon_social")
    dom = cliente_data.get("dominio")
    enm = cliente_data.get("enmascarado")

    if esperado_enmascarado:
        if rs is not None:
            assert "•" in rs, f"razon_social no está ofuscada con viñetas: '{rs}'"
        if dom is not None:
            assert "•" in dom, f"dominio no está ofuscado con viñetas: '{dom}'"

        if isinstance(enm, bool):
            assert enm is True, f"Se esperaba enmascarado=True pero fue {enm}"
        elif isinstance(enm, list):
            assert "razon_social" in enm or "dominio" in enm, (
                f"Lista 'enmascarado' debe indicar los campos protegidos: {enm}"
            )
        else:
            raise AssertionError(f"Tipo inesperado en campo 'enmascarado': {type(enm)} ({enm})")
    else:
        if rs is not None:
            assert "•" not in rs, (
                f"razon_social sigue ofuscada a pesar de concesión activa: '{rs}'"
            )
        if dom is not None:
            assert "•" not in dom, f"dominio sigue ofuscado a pesar de concesión: '{dom}'"

        if isinstance(enm, bool):
            assert enm is False, f"Se esperaba enmascarado=False pero fue {enm}"
        elif isinstance(enm, list):
            assert "razon_social" not in enm and "dominio" not in enm, (
                f"razon_social o dominio siguen enmascarados con concesión: {enm}"
            )


# ==============================================================================
# Fixtures de Soporte
# ==============================================================================


@pytest_asyncio.fixture
async def agregados_frescos(db: Any, dos_clientes: list[str]) -> None:
    """Refresca todos los agregados de negocio para evitar HTTP 503 por frescura."""
    await refrescar_agregados(db)


@pytest_asyncio.fixture
async def concesion_acme(db: Any) -> None:
    """Registra una concesión activa en admin.access_grants para org_acme."""
    await db.execute(
        text("""
        INSERT INTO admin.access_grants (
            id, staff_id, tenant_id, scope, reason, expires_at
        )
        VALUES (
            'gr_org_acme', 'st_prueba', 'org_acme', 'expediente',
            'Incidencia de soporte SUP-1234 justificada',
            now() + interval '1 hour'
        )
        ON CONFLICT (id) DO NOTHING;
        """)
    )
    await db.commit()


@pytest.fixture
def telemetria() -> Any:
    """Doble del contrato interno de telemetría con marcas de tiempo frescas."""
    s = get_admin_settings()
    ahora = datetime.now(UTC).isoformat()
    with respx.mock(base_url=s.telemetry_base_url, assert_all_called=False) as mock:
        mock.get("/telemetry/agents").mock(
            return_value=Response(
                200,
                json={
                    "telemetria_desde": ahora,
                    "etapas": [
                        {
                            "etapa": "gate1",
                            "activos": 3,
                            "en_cola": 7,
                            "latencia_p95_ms": 4200,
                            "errores": 0,
                        }
                    ],
                    "lineas_activas": 12,
                },
            )
        )
        mock.get("/telemetry/queues").mock(
            return_value=Response(
                200,
                json={
                    "telemetria_desde": ahora,
                    "colas": [
                        {
                            "nombre": "fabrica.gate1",
                            "profundidad": 7,
                            "antiguedad_max_s": 45,
                            "dlq": 0,
                        }
                    ],
                },
            )
        )
        mock.get("/telemetry/providers").mock(
            return_value=Response(
                200,
                json={
                    "telemetria_desde": ahora,
                    "proveedores": [
                        {
                            "proveedor": "anthropic",
                            "modelo": "flash",
                            "disponibilidad_pct": 99.8,
                            "latencia_p95_ms": 1800,
                            "error_pct": 0.2,
                            "tokens": 1_240_000,
                        }
                    ],
                },
            )
        )
        yield mock


# ==============================================================================
# 1. Pruebas Unitarias del Motor de Inspección Recursiva
# ==============================================================================


async def test_inspeccionar_payload_recursivo_detecta_anomalias() -> None:
    """Verifica que el inspector recursivo detecte de forma infalible cualquier anomalía."""
    # Estructura limpia -> pasa sin error
    payload_limpio = {
        "status": "ok",
        "items": [
            {"id": "org_1", "nombre": "A•••• S.L.", "mfa_inscrito": True, "activo": True},
            {"id": "org_2", "nombre": "G•••• S.A.", "mfa_inscrito": False, "activo": False},
        ],
        "total": 2,
    }
    inspeccionar_payload_recursivo(payload_limpio)

    # 1. Clave sensible prohibida
    with pytest.raises(AssertionError, match="Clave secreta prohibida"):
        inspeccionar_payload_recursivo({"usuario": {"password_hash": "abc"}})

    with pytest.raises(AssertionError, match="Clave secreta prohibida"):
        inspeccionar_payload_recursivo({"items": [{"totp_secret": "JBSWY3DPEHPK3PXP"}]})

    # 2. Hash Argon2id
    with pytest.raises(AssertionError, match="Hash criptográfico detectado"):
        inspeccionar_payload_recursivo(
            {"datos": "$argon2id$v=19$m=65536,t=3,p=4$somehashvaluehere$signature"}
        )

    # 3. DSN PostgreSQL
    with pytest.raises(AssertionError, match="Cadena de conexión DSN"):
        inspeccionar_payload_recursivo(
            {"database": "postgresql://postgres:dev@localhost:5432/kallicode"}
        )

    # 4. Tabla interna prohibida
    with pytest.raises(AssertionError, match="Tabla interna no autorizada"):
        inspeccionar_payload_recursivo({"mensaje": "Error al leer de core.users"})

    # 5. Traza de excepción
    with pytest.raises(AssertionError, match="Excepción o traza de error"):
        inspeccionar_payload_recursivo({"error": "Traceback (most recent call last):"})


# ==============================================================================
# 2. Enmascaramiento por Defecto sin Concesión en Roles Autorizados
# ==============================================================================


@pytest.mark.parametrize("rol", ["staff_soporte", "staff_negocio", "staff_admin"])
async def test_enmascaramiento_por_defecto_sin_concesion(
    cliente: Any,
    como: Any,
    sin_limite: None,
    agregados_frescos: None,
    rol: str,
) -> None:
    """Sin concesión activa, roles autorizados reciben PII enmascarada y cero secretos."""
    como(rol)

    # A. Listado paginado de clientes
    r_listado = await cliente.get("/admin/v1/business/customers")
    assert r_listado.status_code == 200, r_listado.text
    body_listado = r_listado.json()

    inspeccionar_payload_recursivo(body_listado)
    assert body_listado["total"] >= 2
    for cliente_item in body_listado["items"]:
        verificar_enmascaramiento_cliente(cliente_item, esperado_enmascarado=True)

    # B. Ficha detallada 360° de cliente individual
    r_ficha = await cliente.get("/admin/v1/business/customers/org_acme")
    assert r_ficha.status_code == 200, r_ficha.text
    body_ficha = r_ficha.json()

    inspeccionar_payload_recursivo(body_ficha)
    assert body_ficha["tenant_id"] == "org_acme"
    verificar_enmascaramiento_cliente(body_ficha, esperado_enmascarado=True)


# ==============================================================================
# 3. Revelación Selectiva por Organización con Concesión Activa
# ==============================================================================


async def test_revelacion_selectiva_por_organizacion_con_concesion(
    cliente: Any,
    como: Any,
    sin_limite: None,
    agregados_frescos: None,
    concesion_acme: None,
) -> None:
    """Una concesión activa sobre org_acme revela esa fila; org_globex sigue ofuscada."""
    # Concesión puntual para org_acme únicamente (datos_negocio y expediente)
    como("staff_soporte", grants={"org_acme": ["datos_negocio", "expediente"]})

    # A. En el listado global de clientes
    r_listado = await cliente.get("/admin/v1/business/customers")
    assert r_listado.status_code == 200, r_listado.text
    body_listado = r_listado.json()
    inspeccionar_payload_recursivo(body_listado)

    mapa_clientes = {c["tenant_id"]: c for c in body_listado["items"]}
    assert "org_acme" in mapa_clientes, "org_acme debe figurar en el listado"
    assert "org_globex" in mapa_clientes, "org_globex debe figurar en el listado"

    # org_acme debe figurar revelada
    acme_item = mapa_clientes["org_acme"]
    verificar_enmascaramiento_cliente(acme_item, esperado_enmascarado=False)
    assert acme_item["razon_social"] == "Acme Logística S.L."
    assert acme_item["dominio"] == "acme.com"

    # org_globex debe permanecer ofuscada (no-fuga cross-tenant)
    globex_item = mapa_clientes["org_globex"]
    verificar_enmascaramiento_cliente(globex_item, esperado_enmascarado=True)
    assert "•" in globex_item["razon_social"]
    assert "•" in globex_item["dominio"]

    # B. Ficha individual de org_acme (revelada)
    r_acme = await cliente.get("/admin/v1/business/customers/org_acme")
    assert r_acme.status_code == 200, r_acme.text
    body_acme = r_acme.json()
    inspeccionar_payload_recursivo(body_acme)
    verificar_enmascaramiento_cliente(body_acme, esperado_enmascarado=False)
    assert body_acme["razon_social"] == "Acme Logística S.L."
    assert body_acme["enmascarado"] == []

    # C. Ficha individual de org_globex (ofuscada)
    r_globex = await cliente.get("/admin/v1/business/customers/org_globex")
    assert r_globex.status_code == 200, r_globex.text
    body_globex = r_globex.json()
    inspeccionar_payload_recursivo(body_globex)
    verificar_enmascaramiento_cliente(body_globex, esperado_enmascarado=True)
    assert "•" in body_globex["razon_social"]
    assert "razon_social" in body_globex["enmascarado"]


# ==============================================================================
# 4. Mínimo Privilegio: staff_operaciones
# ==============================================================================


async def test_minimo_privilegio_staff_operaciones(
    cliente: Any,
    como: Any,
    sin_limite: None,
    agregados_frescos: None,
    telemetria: Any,
) -> None:
    """staff_operaciones: 403 en negocio/clientes; 200 en operaciones sin PII ni KPIs."""
    como("staff_operaciones")

    # Endpoints de negocio y clientes vedados para operaciones
    rutas_negocio_prohibidas = [
        ("GET", "/admin/v1/business/overview"),
        ("GET", "/admin/v1/business/customers"),
        ("GET", "/admin/v1/business/customers/org_acme"),
        ("GET", "/admin/v1/business/subscriptions"),
        ("GET", "/admin/v1/business/usage/tokens"),
        ("GET", "/admin/v1/staff"),
    ]

    for metodo, ruta in rutas_negocio_prohibidas:
        r = await cliente.request(metodo, ruta)
        assert r.status_code == 403, (
            f"staff_operaciones debió recibir 403 en {metodo} {ruta}, obtuvo {r.status_code}"
        )
        body = r.json()
        assert body["error"]["codigo"] == "ROL_STAFF_INSUFICIENTE"
        inspeccionar_payload_recursivo(body)

    # Endpoints de operaciones permitidos para su rol
    rutas_ops_autorizadas = [
        "/admin/v1/ops/agents",
        "/admin/v1/ops/queues",
        "/admin/v1/ops/models",
        "/admin/v1/ops/sla",
    ]

    for ruta in rutas_ops_autorizadas:
        r = await cliente.get(ruta)
        assert r.status_code == 200, f"staff_operaciones debió acceder a {ruta}: {r.text}"
        body = r.json()
        inspeccionar_payload_recursivo(body)

        # Garantizar ausencia de PII de clientes y agregados comerciales (MRR)
        texto_serializado = str(body).lower()
        assert "acme" not in texto_serializado, f"Fuga de PII en {ruta}"
        assert "globex" not in texto_serializado, f"Fuga de PII en {ruta}"
        assert "mrr_eur" not in body, f"Métrica comercial prohibida en {ruta}"
        assert "facturacion" not in body, f"Métrica comercial prohibida en {ruta}"


# ==============================================================================
# 5. Mínimo Privilegio: staff_soporte
# ==============================================================================


async def test_minimo_privilegio_staff_soporte(
    cliente: Any,
    como: Any,
    sin_limite: None,
    agregados_frescos: None,
) -> None:
    """staff_soporte: 403 en negocio global y operaciones; 200 en clientes y concesiones."""
    como("staff_soporte")

    # Endpoints fuera del alcance de soporte
    rutas_bloqueadas = [
        ("GET", "/admin/v1/business/overview"),
        ("GET", "/admin/v1/business/subscriptions"),
        ("GET", "/admin/v1/business/usage/tokens"),
        ("GET", "/admin/v1/ops/agents"),
        ("GET", "/admin/v1/ops/queues"),
        ("GET", "/admin/v1/staff"),
    ]

    for metodo, ruta in rutas_bloqueadas:
        r = await cliente.request(metodo, ruta)
        assert r.status_code == 403, (
            f"staff_soporte debió recibir 403 en {metodo} {ruta}, obtuvo {r.status_code}"
        )
        body = r.json()
        assert body["error"]["codigo"] == "ROL_STAFF_INSUFICIENTE"
        inspeccionar_payload_recursivo(body)

    # Endpoints autorizados para soporte
    r_clientes = await cliente.get("/admin/v1/business/customers")
    assert r_clientes.status_code == 200
    inspeccionar_payload_recursivo(r_clientes.json())

    r_grants = await cliente.get("/admin/v1/access-grants?ambito=propias")
    assert r_grants.status_code == 200
    inspeccionar_payload_recursivo(r_grants.json())

    r_audit = await cliente.get("/admin/v1/audit/staff-actions?ambito=propias")
    assert r_audit.status_code == 200
    inspeccionar_payload_recursivo(r_audit.json())


# ==============================================================================
# 6. Mínimo Privilegio: staff_negocio
# ==============================================================================


async def test_minimo_privilegio_staff_negocio(
    cliente: Any,
    como: Any,
    sin_limite: None,
    agregados_frescos: None,
    telemetria: Any,
) -> None:
    """staff_negocio: 403 en ops infra, personal y auditoría; 200 en negocio."""
    como("staff_negocio")

    # Rutas prohibidas para negocio
    rutas_prohibidas = [
        ("GET", "/admin/v1/ops/agents"),
        ("GET", "/admin/v1/ops/queues"),
        ("GET", "/admin/v1/staff"),
        ("GET", "/admin/v1/audit/staff-actions?ambito=todas"),
    ]

    for metodo, ruta in rutas_prohibidas:
        r = await cliente.request(metodo, ruta)
        assert r.status_code == 403, (
            f"staff_negocio debió recibir 403 en {metodo} {ruta}, obtuvo {r.status_code}"
        )
        body = r.json()
        assert body["error"]["codigo"] == "ROL_STAFF_INSUFICIENTE"
        inspeccionar_payload_recursivo(body)

    # Rutas autorizadas para negocio
    rutas_autorizadas = [
        "/admin/v1/business/overview",
        "/admin/v1/business/customers",
        "/admin/v1/business/subscriptions",
        "/admin/v1/business/usage/tokens",
        "/admin/v1/ops/models",
        "/admin/v1/ops/sla",
    ]

    for ruta in rutas_autorizadas:
        r = await cliente.get(ruta)
        assert r.status_code == 200, f"staff_negocio debió acceder a {ruta}: {r.text}"
        body = r.json()
        inspeccionar_payload_recursivo(body)


# ==============================================================================
# 7. Super-rol: staff_admin y Enmascaramiento por Defecto
# ==============================================================================


async def test_staff_admin_super_rol_y_enmascaramiento_por_defecto(
    cliente: Any,
    como: Any,
    sin_limite: None,
    agregados_frescos: None,
    telemetria: Any,
) -> None:
    """staff_admin tiene acceso global, pero clientes se entregan ofuscados sin concesión."""
    como("staff_admin")

    rutas_admin = [
        "/admin/v1/staff",
        "/admin/v1/ops/agents",
        "/admin/v1/business/overview",
        "/admin/v1/audit/staff-actions?ambito=todas",
    ]

    for ruta in rutas_admin:
        r = await cliente.get(ruta)
        assert r.status_code == 200, f"staff_admin debió acceder a {ruta}: {r.text}"
        body = r.json()
        inspeccionar_payload_recursivo(body)

    # En /admin/v1/staff: validar que NO se expongan hashes ni secretos
    r_staff = await cliente.get("/admin/v1/staff")
    assert r_staff.status_code == 200
    body_staff = r_staff.json()
    inspeccionar_payload_recursivo(body_staff)
    for empleado in body_staff["items"]:
        assert "password_hash" not in empleado
        assert "totp_secret" not in empleado
        assert "mfa_inscrito" in empleado
        assert isinstance(empleado["mfa_inscrito"], bool)

    # En /admin/v1/business/customers: INCLUSO staff_admin recibe datos enmascarados
    r_cli = await cliente.get("/admin/v1/business/customers")
    assert r_cli.status_code == 200
    body_cli = r_cli.json()
    inspeccionar_payload_recursivo(body_cli)
    for item in body_cli["items"]:
        verificar_enmascaramiento_cliente(item, esperado_enmascarado=True)


# ==============================================================================
# 8. Sanitización Estricta de Respuestas de Error (403, 404, 422)
# ==============================================================================


async def test_sanitizacion_estricta_respuestas_error(
    cliente: Any,
    como: Any,
    sin_limite: None,
) -> None:
    """Las respuestas de error siguen el sobre canónico y no filtran trazas, SQL ni esquemas."""
    casos_error: list[tuple[str, str, str, dict[str, Any] | None, int, str]] = [
        # 1. 403 ROL_STAFF_INSUFICIENTE
        (
            "staff_operaciones",
            "GET",
            "/admin/v1/business/overview",
            None,
            403,
            "ROL_STAFF_INSUFICIENTE",
        ),
        # 2. 404 RECURSO_NO_ENCONTRADO
        (
            "staff_soporte",
            "GET",
            "/admin/v1/business/customers/org_inexistente_9999",
            None,
            404,
            "RECURSO_NO_ENCONTRADO",
        ),
        # 3. 422 VALIDACION_ENTRADA
        (
            "staff_admin",
            "POST",
            "/admin/v1/staff/invitations",
            {"email": "correo-invalido-sin-arroba", "rol": "staff_soporte"},
            422,
            "VALIDACION_ENTRADA",
        ),
    ]

    for rol, metodo, ruta, cuerpo, status_esperado, codigo_esperado in casos_error:
        como(rol)
        if cuerpo is None:
            r = await cliente.request(metodo, ruta)
        else:
            r = await cliente.request(metodo, ruta, json=cuerpo)

        assert r.status_code == status_esperado, (
            f"Esperado {status_esperado} en {metodo} {ruta}, obtenido {r.status_code}: {r.text}"
        )

        # Validación del sobre estándar de error
        body = r.json()
        assert "error" in body, f"Respuesta de error sin sobre estándar en {ruta}"
        err = body["error"]
        assert err["codigo"] == codigo_esperado
        assert err["code"] == codigo_esperado.lower()
        assert "mensaje" in err
        assert "trace_id" in err

        # Cabecera X-Trace-Id
        assert "X-Trace-Id" in r.headers
        assert r.headers["X-Trace-Id"] == err["trace_id"]

        # Inspección recursiva completa
        inspeccionar_payload_recursivo(body)

        # Comprobación de no-fuga en el texto del error
        texto_error = str(body)
        assert not PATRON_SQL_SNIPPET.search(texto_error), (
            f"Fuga de sentencia SQL detectada en error: {texto_error}"
        )
        assert not PATRON_EXCEPCIONES.search(texto_error), (
            f"Fuga de nombre de excepción o traza detectada en error: {texto_error}"
        )
        assert not PATRON_TABLAS_PROHIBIDAS.search(texto_error), (
            f"Fuga de tabla interna detectada en error: {texto_error}"
        )
        assert not PATRON_RUTA_INTERNA.search(texto_error), (
            f"Fuga de ruta del servidor detectada en error: {texto_error}"
        )


# ==============================================================================
# 9. Concesiones y Auditoría: Gestión Segura sin Fuga de Secretos
# ==============================================================================


async def test_gestion_concesiones_y_auditoria_sin_fugas(
    cliente: Any,
    como: Any,
    sin_limite: None,
    dos_clientes: list[str],
) -> None:
    """Creación de concesión y consulta de trazas de auditoría sin filtración de secretos."""
    como("staff_soporte")

    # A. Crear concesión justificada
    payload_concesion = {
        "tenant_id": "org_acme",
        "alcance": "datos_negocio",
        "motivo": "Revisión técnica de incidencia crítica en facturación caso SUP-9988",
        "duracion_min": 30,
        "referencia": "SUP-9988",
    }
    r_crear = await cliente.post("/admin/v1/access-grants", json=payload_concesion)
    assert r_crear.status_code == 201, r_crear.text
    body_crear = r_crear.json()
    inspeccionar_payload_recursivo(body_crear)
    assert body_crear["tenant_id"] == "org_acme"
    assert body_crear["alcance"] == "datos_negocio"

    # B. Listar concesiones propias
    r_grants = await cliente.get("/admin/v1/access-grants?ambito=propias")
    assert r_grants.status_code == 200, r_grants.text
    body_grants = r_grants.json()
    inspeccionar_payload_recursivo(body_grants)

    # C. Listar acciones auditadas
    r_audit = await cliente.get("/admin/v1/audit/staff-actions?ambito=propias")
    assert r_audit.status_code == 200, r_audit.text
    body_audit = r_audit.json()
    inspeccionar_payload_recursivo(body_audit)
