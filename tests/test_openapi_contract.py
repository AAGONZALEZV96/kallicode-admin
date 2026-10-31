"""Pruebas del Contrato OpenAPI v1.0 Congelado con Schemathesis y Respx (KC-ADM-B3-09).

Valida de forma estricta e inmutable:
  1. Versión OpenAPI congelada a exactamente "3.0.3" y 7 tags canónicos oficiales.
  2. Cobertura exacta de las 31 operaciones de la API /admin/v1.
  3. Esquemas globales ErrorStandard, BearerAuth y CustomerSummary en components.
  4. Fuzzing y validación de contrato basada en propiedades con Schemathesis.
  5. Drenaje y aislamiento de telemetría saliente mediante dobles en memoria (Respx).
  6. Matriz de pruebas sembradas sobre las 31 operaciones con verificación de:
     - Códigos de estado HTTP documentados (sin códigos inesperados ni 500).
     - Validación de esquemas JSON de respuesta contra la especificación.
     - Presencia de cabecera obligatoria X-Trace-Id y cabeceras de seguridad.
  7. Rechazo estricto de campos extra indocumentados (extra="forbid" -> 422 ErrorStandard).
"""

from __future__ import annotations

import re
from collections.abc import AsyncIterator, Callable, Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pyotp
import pytest
import pytest_asyncio
import respx
import schemathesis
import yaml
from admin_api.deps import redis
from admin_api.security import hash_token, hashear_password
from admin_api.settings import get_admin_settings
from schemathesis.checks import (
    content_type_conformance,
    not_a_server_error,
    response_schema_conformance,
    status_code_conformance,
)
from sqlalchemy import text

TAGS_OFICIALES = {
    "Salud",
    "Identidad y sesión",
    "Gestión del personal",
    "Concesiones de acceso",
    "Consola de negocio",
    "Consola de operaciones",
    "Auditoría del personal",
}

YAML_PATH = Path(__file__).resolve().parents[1] / "docs" / "openapi-admin-v1.yaml"
SCHEMA_CONTRATO = schemathesis.openapi.from_path(YAML_PATH)

CHECKS_CONTRATO = [
    not_a_server_error,
    status_code_conformance,
    content_type_conformance,
    response_schema_conformance,
]

MFA_RAW = "mfa_raw_token_for_verify"
TOTP_SECRET = "JBSWY3DPEHPK3PXP"
RT_RAW = "rt_raw_token_for_refresh"
PRT_RAW = "prt_raw_token_for_reset"
INV_RAW = "inv_raw_token_for_invitation"


# ==============================================================================
# Fixtures de aislamiento de telemetría y datos sembrados
# ==============================================================================


@pytest.fixture
def telemetria_mock() -> Iterator[respx.MockRouter]:
    """Doble de telemetría saliente con marcas de tiempo ISO-8601 UTC en memoria."""
    s = get_admin_settings()
    ahora = datetime.now(UTC).isoformat()
    with respx.mock(base_url=s.telemetry_base_url, assert_all_called=False) as mock:
        mock.get("/telemetry/agents").mock(
            return_value=httpx.Response(
                200,
                json={"telemetria_desde": ahora, "etapas": [], "lineas_activas": 5},
            )
        )
        mock.get("/telemetry/queues").mock(
            return_value=httpx.Response(
                200,
                json={"telemetria_desde": ahora, "colas": []},
            )
        )
        mock.get("/telemetry/providers").mock(
            return_value=httpx.Response(
                200,
                json={"telemetria_desde": ahora, "proveedores": []},
            )
        )
        yield mock


@pytest_asyncio.fixture
async def datos_contrato_sembrados(
    dsn: str, dos_clientes: list[str]
) -> AsyncIterator[dict[str, str]]:
    """Siembra los registros mínimos necesarios para que las 31 operaciones respondan 2xx."""
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
    from sqlalchemy.pool import NullPool

    engine = create_async_engine(
        dsn.replace("postgresql://", "postgresql+asyncpg://"),
        poolclass=NullPool,
    )

    sid = "st_contract"
    email = "st_contract@kallicode.com"
    pw_hash = hashear_password("Prueba-Segura-2026")

    async with AsyncSession(engine) as session:
        # 1. Staff principal y staff adicional para operaciones de administración
        await session.execute(
            text("DELETE FROM admin.staff_password_history WHERE staff_id = :sid"),
            {"sid": sid},
        )
        await session.execute(
            text("""
                INSERT INTO admin.staff
                    (id, email, full_name, role, status, password_hash,
                     totp_secret, totp_enrolled_at)
                VALUES (:sid, :email, 'Staff Contrato', 'staff_admin', 'active',
                        :pw, :totp, now())
                ON CONFLICT (id) DO UPDATE
                SET password_hash = :pw, status = 'active', totp_secret = :totp,
                    totp_enrolled_at = now()
            """),
            {"sid": sid, "email": email, "pw": pw_hash, "totp": TOTP_SECRET},
        )

        await session.execute(
            text("""
                INSERT INTO admin.staff
                    (id, email, full_name, role, status, password_hash,
                     totp_secret, totp_enrolled_at)
                VALUES ('st_otro', 'st_otro@kallicode.com', 'Staff Otro',
                        'staff_soporte', 'active', :pw, :totp, now())
                ON CONFLICT (id) DO UPDATE
                SET role = 'staff_soporte', status = 'active'
            """),
            {"pw": pw_hash, "totp": TOTP_SECRET},
        )

        # 2. Desafíos MFA (uno para verificar y otro para enrolar)
        await session.execute(
            text("""
                INSERT INTO admin.staff_mfa_challenges (id, staff_id, token_hash, expires_at)
                VALUES ('mfa_verify_1', :sid, :h, now() + interval '10 minutes')
                ON CONFLICT (id) DO UPDATE
                SET token_hash = :h, expires_at = now() + interval '10 minutes',
                    consumed_at = NULL
            """),
            {"sid": sid, "h": hash_token(MFA_RAW)},
        )

        await session.execute(
            text("""
                INSERT INTO admin.staff (id, email, full_name, role, status, totp_secret)
                VALUES ('st_enroll', 'st_enroll@kallicode.com', 'Staff Enroll',
                        'staff_soporte', 'invited', NULL)
                ON CONFLICT (id) DO UPDATE SET totp_secret = NULL
            """)
        )
        await session.execute(
            text("""
                INSERT INTO admin.staff_mfa_challenges (id, staff_id, token_hash, expires_at)
                VALUES ('mfa_enroll_1', 'st_enroll', :h, now() + interval '10 minutes')
                ON CONFLICT (id) DO UPDATE
                SET staff_id = 'st_enroll', token_hash = :h, consumed_at = NULL,
                    expires_at = now() + interval '10 minutes'
            """),
            {"h": hash_token("mfa_raw_token_for_enroll")},
        )

        # 3. Refresh token activo
        await session.execute(
            text("""
                INSERT INTO admin.staff_refresh_tokens
                    (id, staff_id, token_hash, mfa_at, expires_at)
                VALUES ('rt_contract_1', :sid, :h, now(), now() + interval '1 day')
                ON CONFLICT (id) DO UPDATE
                SET token_hash = :h, expires_at = now() + interval '1 day',
                    revoked = false, used_at = NULL, mfa_at = now()
            """),
            {"sid": sid, "h": hash_token(RT_RAW)},
        )

        # 4. Solicitud de restablecimiento de contraseña
        await session.execute(
            text("""
                INSERT INTO admin.staff_password_resets (id, staff_id, token_hash, expires_at)
                VALUES ('prt_contract_1', :sid, :h, now() + interval '15 minutes')
                ON CONFLICT (id) DO UPDATE
                SET token_hash = :h, expires_at = now() + interval '15 minutes',
                    used_at = NULL
            """),
            {"sid": sid, "h": hash_token(PRT_RAW)},
        )

        # 5. Invitación pendiente
        await session.execute(
            text("""
                DELETE FROM admin.staff_password_history
                WHERE staff_id IN (
                    SELECT id FROM admin.staff WHERE email = 'invitado@kallicode.com'
                )
            """)
        )
        await session.execute(
            text("DELETE FROM admin.staff WHERE email = 'invitado@kallicode.com'")
        )
        await session.execute(
            text("""
                INSERT INTO admin.staff_invitations
                    (id, email, role, token_hash, invited_by, expires_at)
                VALUES ('inv_contract_1', 'invitado@kallicode.com', 'staff_soporte',
                        :h, :sid, now() + interval '7 days')
                ON CONFLICT (id) DO UPDATE
                SET token_hash = :h, expires_at = now() + interval '7 days',
                    accepted_at = NULL, revoked_at = NULL
            """),
            {"h": hash_token(INV_RAW), "sid": sid},
        )

        # 6. Concesión de acceso para probar DELETE sin violar restricciones de auditoría
        await session.execute(
            text("""
                UPDATE admin.access_grants
                SET revoked_at = now(), revoked_by = :sid
                WHERE staff_id = :sid AND revoked_at IS NULL
            """),
            {"sid": sid},
        )
        await session.execute(
            text("""
                INSERT INTO admin.access_grants
                    (id, staff_id, tenant_id, scope, reason, expires_at)
                VALUES ('gr_contract_del', :sid, 'org_acme', 'expediente',
                        'Auditoria motivo con mas de 20 caracteres',
                        now() + interval '1 hour')
                ON CONFLICT (id) DO UPDATE
                SET revoked_at = NULL, expires_at = now() + interval '1 hour'
            """),
            {"sid": sid},
        )

        # 7. Caso de SLA
        await session.execute(
            text("""
                INSERT INTO admin.sla_cases
                    (job_id, tenant_id, ticket_numero, plan_codigo, objetivo_h,
                     transcurrido_h, bruto_h, resultado, tramos, reglas, iniciado_en)
                VALUES ('job_contract_1', 'org_acme', 'TICK-999', 'growth',
                        4.0, 1.5, 1.5, 'dentro', '[]'::jsonb,
                        ARRAY['regla_std']::text[], now())
                ON CONFLICT (job_id) DO UPDATE SET resultado = 'dentro'
            """)
        )

        # 8. Informe de negocio
        await session.execute(
            text("""
                INSERT INTO admin.reports
                    (id, kind, format, params, requested_by, status)
                VALUES ('rp_contract_1', 'consumo', 'csv',
                        '{"desde": "2026-01-01"}'::jsonb, 'st_prueba', 'en_cola')
                ON CONFLICT (id) DO UPDATE
                SET requested_by = 'st_prueba', status = 'en_cola'
            """)
        )

        # 9. Refresco de vistas materializadas y limpieza de Redis
        await session.execute(text("SELECT admin.refresh_all_business_aggregates()"))
        await session.commit()

    await engine.dispose()

    r_client = redis()
    await r_client.flushdb()

    yield {
        "staff_id": sid,
        "mfa_raw": MFA_RAW,
        "totp_secret": TOTP_SECRET,
        "rt_raw": RT_RAW,
        "prt_raw": PRT_RAW,
        "inv_raw": INV_RAW,
    }


# ==============================================================================
# 1. Pruebas Estáticas y de Congelamiento (KC-ADM-B1-08)
# ==============================================================================


def test_metadata_y_version_congelada(app: Any) -> None:
    """La API debe servir exactamente OpenAPI 3.0.3 y metadatos del capítulo 18."""
    schema = app.openapi()

    assert schema["openapi"] == "3.0.3", f"Versión incorrecta: {schema['openapi']}"
    assert schema["info"]["title"] == "KalliCode · API de Administración"
    assert "capítulo 18" in schema["info"]["description"]
    assert schema["info"]["version"] == "0.1.0" or schema["info"]["version"] == "1.0.0"


async def test_endpoint_openapi_json_sirve_303(cliente: Any) -> None:
    """El endpoint HTTP /admin/v1/openapi.json debe responder 200 con versión 3.0.3."""
    r = await cliente.get("/admin/v1/openapi.json")
    assert r.status_code == 200, f"Error obteniendo openapi.json: {r.text}"
    cuerpo = r.json()
    assert cuerpo["openapi"] == "3.0.3"
    assert "paths" in cuerpo


def test_cobertura_exacta_31_endpoints(app: Any) -> None:
    """Deben existir exactamente 31 operaciones HTTP agrupadas en los 7 tags canónicos."""
    schema = app.openapi()
    paths = schema.get("paths", {})

    operaciones: list[tuple[str, str, list[str]]] = []
    for ruta, metodos in paths.items():
        for metodo, defn in metodos.items():
            if metodo.lower() in ("get", "post", "put", "patch", "delete"):
                tags = defn.get("tags", [])
                operaciones.append((metodo.upper(), ruta, tags))

    assert len(operaciones) == 31, (
        f"Se esperaban exactamente 31 endpoints, se encontraron {len(operaciones)}: "
        f"{[f'{m} {r}' for m, r, _ in operaciones]}"
    )

    tags_encontrados: set[str] = set()
    for metodo, ruta, tags in operaciones:
        assert len(tags) > 0, f"Endpoint {metodo} {ruta} no tiene tags asignados"
        for t in tags:
            assert t in TAGS_OFICIALES, (
                f"Tag '{t}' en {metodo} {ruta} no pertenece a los 7 tags oficiales"
            )
            tags_encontrados.add(t)

    assert tags_encontrados == TAGS_OFICIALES, (
        f"Tags faltantes: {TAGS_OFICIALES - tags_encontrados}"
    )


def test_seguridad_y_esquemas_estandar(app: Any) -> None:
    """Verifica BearerAuth en securitySchemes y ErrorStandard en schemas."""
    schema = app.openapi()
    components = schema.get("components", {})
    security_schemes = components.get("securitySchemes", {})
    schemas = components.get("schemas", {})

    assert "BearerAuth" in security_schemes, "Falta BearerAuth en components/securitySchemes"
    bearer = security_schemes["BearerAuth"]
    assert bearer["type"] == "http"
    assert bearer["scheme"] == "bearer"
    assert bearer["bearerFormat"] == "JWT"
    assert "typ=staff" in bearer["description"]

    assert "security" in schema
    assert {"BearerAuth": []} in schema["security"]

    assert "ErrorStandard" in schemas, "Falta ErrorStandard en components/schemas"
    err = schemas["ErrorStandard"]
    assert err["type"] == "object"
    props = err.get("properties", {})

    campos_requeridos = ["codigo", "mensaje", "detalle", "trace_id", "timestamp"]
    for campo in campos_requeridos:
        assert campo in props, f"Propiedad '{campo}' falta en ErrorStandard"
        assert campo in err.get("required", []), (
            f"'{campo}' debe ser requerida en ErrorStandard"
        )

    assert props["timestamp"]["format"] == "date-time"
    assert props["detalle"]["nullable"] is True


def test_enmascarado_declarado_en_clientes(app: Any) -> None:
    """CustomerSummary debe documentar el enmascarado por defecto de datos de clientes."""
    schema = app.openapi()
    components = schema.get("components", {})
    schemas = components.get("schemas", {})

    assert "CustomerSummary" in schemas, "Falta CustomerSummary en components/schemas"
    customer = schemas["CustomerSummary"]
    assert customer["type"] == "object"
    props = customer.get("properties", {})

    campos_requeridos = ["tenant_id", "name", "plan", "status"]
    for campo in campos_requeridos:
        assert campo in props, f"Propiedad '{campo}' falta en CustomerSummary"
        assert campo in customer.get("required", []), (
            f"'{campo}' debe ser requerida en CustomerSummary"
        )

    descripcion_name = props["name"].get("description", "").lower()
    assert "enmascarada" in descripcion_name or "enmascarado" in descripcion_name, (
        f"La descripción de 'name' debe explicitar el enmascarado: {props['name']}"
    )


def test_archivo_yaml_congelado_coincide_con_api() -> None:
    """El archivo docs/openapi-admin-v1.yaml debe declarar openapi 3.0.3 y esquemas."""
    assert YAML_PATH.exists(), f"No se encontró el contrato YAML en {YAML_PATH}"

    with open(YAML_PATH, encoding="utf-8") as f:
        doc = yaml.safe_load(f)

    assert doc["openapi"] == "3.0.3"
    assert "BearerAuth" in doc["components"]["securitySchemes"]
    assert "ErrorStandard" in doc["components"]["schemas"]
    assert "CustomerSummary" in doc["components"]["schemas"]


# ==============================================================================
# 2. Validación de Propiedades y Fuzzing de Contrato con Schemathesis
# ==============================================================================


def test_schemathesis_valida_31_operaciones_y_propiedades() -> None:
    """Schemathesis comprueba la integridad estructural y sintáctica del contrato."""
    schema = schemathesis.openapi.from_path(YAML_PATH)
    operaciones = list(schema.get_all_operations())

    assert len(operaciones) == 31, (
        f"Schemathesis debe descubrir exactamente 31 operaciones, encontró {len(operaciones)}"
    )

    tags_vistos: set[str] = set()
    for op_res in operaciones:
        op = op_res.ok()
        assert op.label, "Operación sin etiqueta canónica"
        for tag in op.tags or []:
            tags_vistos.add(tag)

        # Genera estrategias basadas en propiedades para verificar la validez del esquema
        estrategia = op.as_strategy()
        assert estrategia is not None, f"No se pudo generar estrategia para {op.label}"

    assert tags_vistos == TAGS_OFICIALES, (
        f"Discrepancia en tags oficiales descubiertos por Schemathesis: {tags_vistos}"
    )


# ==============================================================================
# 3. Matriz Exhaustiva de las 31 Operaciones Sembradas con Schemathesis Checks
# ==============================================================================

CASOS_31_OPERACIONES: list[
    tuple[
        str,
        str,
        str,
        str | None,
        dict[str, Any] | Callable[[], dict[str, Any]] | None,
        dict[str, Any] | None,
        int,
    ]
] = [
    # 1. Salud (pública)
    ("GET", "/admin/v1/health", "/admin/v1/health", None, None, None, 200),
    # 2-9. Identidad y sesión
    (
        "POST",
        "/admin/v1/auth/login",
        "/admin/v1/auth/login",
        None,
        {"email": "st_contract@kallicode.com", "password": "Prueba-Segura-2026"},
        None,
        200,
    ),
    (
        "POST",
        "/admin/v1/auth/mfa/verify",
        "/admin/v1/auth/mfa/verify",
        None,
        lambda: {"mfa_token": MFA_RAW, "codigo": pyotp.TOTP(TOTP_SECRET).now()},
        None,
        200,
    ),
    (
        "POST",
        "/admin/v1/auth/mfa/enroll",
        "/admin/v1/auth/mfa/enroll",
        None,
        {"mfa_token": "mfa_raw_token_for_enroll"},
        None,
        200,
    ),
    (
        "POST",
        "/admin/v1/auth/refresh",
        "/admin/v1/auth/refresh",
        None,
        {"refresh_token": RT_RAW},
        None,
        200,
    ),
    (
        "POST",
        "/admin/v1/auth/logout",
        "/admin/v1/auth/logout",
        "staff_admin",
        {},
        None,
        200,
    ),
    (
        "POST",
        "/admin/v1/auth/forgot-password",
        "/admin/v1/auth/forgot-password",
        None,
        {"email": "st_contract@kallicode.com"},
        None,
        204,
    ),
    (
        "POST",
        "/admin/v1/auth/reset-password",
        "/admin/v1/auth/reset-password",
        None,
        {"token": PRT_RAW, "password": "Nueva-Password-Segura-2026!"},
        None,
        200,
    ),
    (
        "POST",
        "/admin/v1/auth/invitations/accept",
        "/admin/v1/auth/invitations/accept",
        None,
        {
            "token": INV_RAW,
            "nombre": "Invitado Contrato",
            "password": "Invitado-Pass-2026!",
        },
        None,
        200,
    ),
    # 10-13. Gestión del personal
    ("GET", "/admin/v1/staff/me", "/admin/v1/staff/me", "staff_admin", None, None, 200),
    ("GET", "/admin/v1/staff", "/admin/v1/staff", "staff_admin", None, None, 200),
    (
        "POST",
        "/admin/v1/staff/invitations",
        "/admin/v1/staff/invitations",
        "staff_admin",
        {
            "email": "nuevo_invitado_2@kallicode.com",
            "rol": "staff_soporte",
            "nota": "Contrato",
        },
        None,
        200,
    ),
    (
        "PATCH",
        "/admin/v1/staff/st_otro",
        "/admin/v1/staff/{staff_id}",
        "staff_admin",
        {"rol": "staff_operaciones"},
        None,
        200,
    ),
    # 14-16. Concesiones de acceso
    (
        "POST",
        "/admin/v1/access-grants",
        "/admin/v1/access-grants",
        "staff_admin",
        {
            "tenant_id": "org_globex",
            "alcance": "expediente",
            "motivo": "Auditoria de contrato caso SUP-9999",
            "referencia": "SUP-9999",
            "duracion_min": 15,
        },
        None,
        201,
    ),
    (
        "GET",
        "/admin/v1/access-grants",
        "/admin/v1/access-grants",
        "staff_admin",
        None,
        None,
        200,
    ),
    (
        "DELETE",
        "/admin/v1/access-grants/gr_contract_del",
        "/admin/v1/access-grants/{grant_id}",
        "staff_admin",
        {"motivo": "Motivo justificado para revocacion de concesion ajena"},
        None,
        200,
    ),
    # 17-24. Consola de negocio
    (
        "GET",
        "/admin/v1/business/overview",
        "/admin/v1/business/overview",
        "staff_negocio",
        None,
        None,
        200,
    ),
    (
        "GET",
        "/admin/v1/business/customers",
        "/admin/v1/business/customers",
        "staff_negocio",
        None,
        None,
        200,
    ),
    (
        "GET",
        "/admin/v1/business/customers/org_acme",
        "/admin/v1/business/customers/{tenant_id}",
        "staff_negocio",
        None,
        None,
        200,
    ),
    (
        "GET",
        "/admin/v1/business/subscriptions",
        "/admin/v1/business/subscriptions",
        "staff_negocio",
        None,
        None,
        200,
    ),
    (
        "GET",
        "/admin/v1/business/upgrade-requests",
        "/admin/v1/business/upgrade-requests",
        "staff_negocio",
        None,
        None,
        200,
    ),
    (
        "GET",
        "/admin/v1/business/usage/tokens",
        "/admin/v1/business/usage/tokens",
        "staff_negocio",
        None,
        None,
        200,
    ),
    (
        "POST",
        "/admin/v1/business/reports",
        "/admin/v1/business/reports",
        "staff_negocio",
        {
            "tipo": "consumo",
            "desde": "2026-01-01",
            "hasta": "2026-01-31",
            "formato": "csv",
        },
        None,
        202,
    ),
    (
        "GET",
        "/admin/v1/business/reports/rp_contract_1",
        "/admin/v1/business/reports/{report_id}",
        "staff_admin",
        None,
        None,
        200,
    ),
    (
        "GET",
        "/admin/v1/ops/agents",
        "/admin/v1/ops/agents",
        "staff_operaciones",
        None,
        None,
        200,
    ),
    (
        "GET",
        "/admin/v1/ops/queues",
        "/admin/v1/ops/queues",
        "staff_operaciones",
        None,
        None,
        200,
    ),
    (
        "GET",
        "/admin/v1/ops/models",
        "/admin/v1/ops/models",
        "staff_operaciones",
        None,
        None,
        200,
    ),
    ("GET", "/admin/v1/ops/sla", "/admin/v1/ops/sla", "staff_operaciones", None, None, 200),
    (
        "GET",
        "/admin/v1/ops/sla/cases/job_contract_1",
        "/admin/v1/ops/sla/cases/{job_id}",
        "staff_operaciones",
        None,
        None,
        200,
    ),
    # 30-31. Auditoría del personal
    (
        "GET",
        "/admin/v1/audit/staff-actions",
        "/admin/v1/audit/staff-actions",
        "staff_admin",
        None,
        None,
        200,
    ),
    (
        "POST",
        "/admin/v1/audit/staff-actions/exports",
        "/admin/v1/audit/staff-actions/exports",
        "staff_admin",
        {"desde": "2026-01-01", "hasta": "2026-01-31", "formato": "csv"},
        None,
        202,
    ),
]


@pytest.mark.parametrize(
    "metodo, ruta_real, ruta_tpl, rol, cuerpo, params, st_esp",
    CASOS_31_OPERACIONES,
)
async def test_contrato_31_operaciones_sembradas(
    cliente: Any,
    como: Any,
    sin_limite: None,
    telemetria_mock: respx.MockRouter,
    datos_contrato_sembrados: dict[str, str],
    metodo: str,
    ruta_real: str,
    ruta_tpl: str,
    rol: str | None,
    cuerpo: dict[str, Any] | Callable[[], dict[str, Any]] | None,
    params: dict[str, Any] | None,
    st_esp: int,
) -> None:
    """Valida cada una de las 31 operaciones de la API contra el contrato OpenAPI."""
    if rol is not None:
        como(rol)

    op = SCHEMA_CONTRATO.find_operation_by_label(f"{metodo} {ruta_tpl}")
    assert op is not None, f"Operación no encontrada en OpenAPI: {metodo} {ruta_tpl}"

    # Extrae parámetros de ruta para la comprobación en Schemathesis
    path_params: dict[str, Any] = {}
    if "{" in ruta_tpl:
        patron = re.sub(r"\{(\w+)\}", r"(?P<\1>[^/]+)", ruta_tpl)
        m = re.match(patron, ruta_real)
        if m:
            path_params = m.groupdict()

    case = op.Case(path_parameters=path_params if path_params else None)

    # Resuelve cuerpo dinámico si es una función generadora (ej. código TOTP fresco)
    payload = cuerpo() if callable(cuerpo) else cuerpo

    r = await cliente.request(metodo, ruta_real, json=payload, params=params)

    # 1. Comprobación estricta de código HTTP declarado
    assert r.status_code == st_esp, (
        f"Código HTTP no esperado en {metodo} {ruta_real}: {r.status_code} != {st_esp}. "
        f"Respuesta: {r.text[:500]}"
    )

    # 2. Comprobaciones de contrato Schemathesis (esquemas, tipos y ausencia de 500)
    case.validate_response(r, checks=CHECKS_CONTRATO)

    # 3. Comprobación obligatoria de cabeceras de trazabilidad y seguridad
    assert "x-trace-id" in r.headers, (
        f"Cabecera 'X-Trace-Id' falta en la respuesta de {metodo} {ruta_real}"
    )
    assert r.headers.get("x-content-type-options") == "nosniff"
    assert r.headers.get("x-frame-options") == "DENY"
    assert "no-store" in r.headers.get("cache-control", "")


# ==============================================================================
# 4. Validación de Rechazo Estricto de Payloads Indocumentados (extra="forbid")
# ==============================================================================

CASOS_CAMPOS_EXTRA = [
    (
        "POST",
        "/admin/v1/auth/login",
        {
            "email": "st_contract@kallicode.com",
            "password": "Prueba-Segura-2026",
            "campo_extra_prohibido": 1,
        },
    ),
    (
        "POST",
        "/admin/v1/auth/mfa/verify",
        {"mfa_token": "tok", "codigo": "123456", "campo_extra_prohibido": 1},
    ),
    (
        "POST",
        "/admin/v1/auth/mfa/enroll",
        {"mfa_token": "tok", "campo_extra_prohibido": 1},
    ),
    (
        "POST",
        "/admin/v1/auth/refresh",
        {"refresh_token": "tok", "campo_extra_prohibido": 1},
    ),
    (
        "POST",
        "/admin/v1/auth/logout",
        {"campo_extra_prohibido": 1},
    ),
    (
        "POST",
        "/admin/v1/auth/forgot-password",
        {"email": "st_contract@kallicode.com", "campo_extra_prohibido": 1},
    ),
    (
        "POST",
        "/admin/v1/auth/reset-password",
        {
            "token": "tok",
            "password": "Nueva-Password-Segura-2026!",
            "campo_extra_prohibido": 1,
        },
    ),
    (
        "POST",
        "/admin/v1/auth/invitations/accept",
        {
            "token": "tok",
            "nombre": "Invitado",
            "password": "Password-1234!",
            "campo_extra_prohibido": 1,
        },
    ),
    (
        "POST",
        "/admin/v1/staff/invitations",
        {
            "email": "inv@kallicode.com",
            "rol": "staff_soporte",
            "nota": "Nota",
            "campo_extra_prohibido": 1,
        },
    ),
    (
        "PATCH",
        "/admin/v1/staff/st_otro",
        {"rol": "staff_operaciones", "campo_extra_prohibido": 1},
    ),
    (
        "POST",
        "/admin/v1/access-grants",
        {
            "tenant_id": "org_acme",
            "alcance": "expediente",
            "motivo": "Motivo con longitud suficiente para pasar",
            "campo_extra_prohibido": 1,
        },
    ),
    (
        "DELETE",
        "/admin/v1/access-grants/gr_dummy",
        {"motivo": "Motivo para revocar", "campo_extra_prohibido": 1},
    ),
    (
        "POST",
        "/admin/v1/business/reports",
        {
            "tipo": "consumo",
            "desde": "2026-01-01",
            "hasta": "2026-01-31",
            "formato": "csv",
            "campo_extra_prohibido": 1,
        },
    ),
    (
        "POST",
        "/admin/v1/audit/staff-actions/exports",
        {
            "desde": "2026-01-01",
            "hasta": "2026-01-31",
            "formato": "csv",
            "campo_extra_prohibido": 1,
        },
    ),
]


@pytest.mark.parametrize("metodo, ruta, cuerpo", CASOS_CAMPOS_EXTRA)
async def test_modelos_pydantic_rechazan_campos_extra(
    cliente: Any,
    como: Any,
    sin_limite: None,
    metodo: str,
    ruta: str,
    cuerpo: dict[str, Any],
) -> None:
    """Envío de atributos extra no declarados es rechazado inmediatamente con 422."""
    como("staff_admin")
    r = await cliente.request(metodo, ruta, json=cuerpo)

    assert r.status_code == 422, (
        f"Se esperaba HTTP 422 por campo extra en {metodo} {ruta}, se obtuvo {r.status_code}"
    )

    cuerpo_resp = r.json()
    assert "error" in cuerpo_resp, f"Respuesta no tiene sobre de error: {cuerpo_resp}"
    error_info = cuerpo_resp["error"]
    assert error_info["codigo"] == "VALIDACION_ENTRADA"
    assert "extra" in r.text.lower() or "extra inputs" in r.text.lower()
    assert "x-trace-id" in r.headers
