"""Aplicación FastAPI de la consola de administración.

Aplicación propia, imagen propia y despliegue propio, en red privada y sin
ingress público en ningún entorno (ADR 001, brecha ADM-G10). El backend actual
monta la API interna del pipeline en la misma aplicación y el mismo puerto que
el portal cliente, y repetir ese patrón aquí pondría la superficie más sensible
del sistema detrás del mismo ingress público.

Diferencias deliberadas respecto a la aplicación del portal:

  · No hay CORS permisivo. La consola se sirve desde su propio origen y la lista
    de orígenes es explícita; el arranque falla si se configura un comodín junto
    con credenciales, combinación que además de peligrosa es inválida.
  · Hay `TrustedHostMiddleware` y límite global de tamaño de cuerpo.
  · El ciclo de vida cierra los pools y el cliente de Redis al apagar, para no
    dejar conexiones colgadas en cada redespliegue.
  · El arranque verifica en la propia base que el modelo de acceso sigue en pie
    y **se niega a arrancar** si no lo está.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse
from kallicode_core.errors import AppError
from kallicode_core.logging import (
    bind_contexto,
    configurar_logging,
    limpiar_contexto,
    log,
)
from starlette.exceptions import HTTPException as StarletteHTTPException

from . import db as dbmod
from .deps import cerrar_redis
from .settings import get_admin_settings

MAX_BODY_BYTES = 2 * 1024 * 1024  # 2 MB: la consola no recibe adjuntos


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    configurar_logging()
    s = get_admin_settings()
    log.info("admin.arrancando", env=s.env, version=s.app_version)
    # Barrera: sin modelo de acceso válido no se sirve una sola petición.
    await dbmod.verificar_arranque()
    log.info("admin.listo")
    try:
        yield
    finally:
        await dbmod.cerrar()
        await cerrar_redis()
        log.info("admin.apagado")


app = FastAPI(
    title="KalliCode · API de Administración",
    version=get_admin_settings().app_version,
    description=(
        "Superficie interna de la consola de negocio y operaciones. No la "
        "consume ningún cliente ni ningún agente del pipeline. Documentada en "
        "el capítulo 18 del Diseño del backend."
    ),
    openapi_url="/admin/v1/openapi.json",
    docs_url="/admin/v1/docs",
    redoc_url=None,
    lifespan=lifespan,
)

app.add_middleware(TrustedHostMiddleware, allowed_hosts=get_admin_settings().hosts_permitidos)


# ------------------------------------------------------------- middleware
@app.middleware("http")
async def contexto_y_cabeceras(
    request: Request,
    call_next: Callable[[Request], Awaitable[JSONResponse]],
) -> JSONResponse:
    """Traza, contexto de log, cabeceras de seguridad y límite de cuerpo."""
    trace_id = request.headers.get("x-trace-id") or f"tr_{uuid.uuid4().hex[:24]}"
    request.state.trace_id = trace_id
    bind_contexto(trace_id=trace_id)

    largo = request.headers.get("content-length")
    if largo and int(largo) > MAX_BODY_BYTES:
        limpiar_contexto()
        return JSONResponse(
            status_code=413,
            content=_sobre(
                "CUERPO_DEMASIADO_GRANDE",
                "La petición es demasiado grande.",
                trace_id,
                {"maximo_bytes": MAX_BODY_BYTES},
            ),
        )

    inicio = time.perf_counter()
    try:
        resp = await call_next(request)
    except Exception as exc:
        latencia_ms = round((time.perf_counter() - inicio) * 1000, 2)
        log.error(
            "admin.error_no_controlado",
            metodo=request.method,
            ruta=request.url.path,
            latencia_ms=latencia_ms,
            excepcion=type(exc).__name__,
        )
        limpiar_contexto()
        return JSONResponse(
            status_code=500,
            content=_sobre(
                "ERROR_INTERNO",
                "Se ha producido un error interno. Contacta con la plataforma indicando "
                "el identificador de traza.",
                trace_id,
            ),
            headers={
                "X-Trace-Id": trace_id,
                "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
                "X-Content-Type-Options": "nosniff",
                "X-Frame-Options": "DENY",
                "Referrer-Policy": "no-referrer",
                "Content-Security-Policy": (
                    "default-src 'self'; img-src 'self' data:; style-src 'self'; "
                    "script-src 'self'; frame-ancestors 'none'; base-uri 'none'"
                ),
                "Cache-Control": "no-store",
            },
        )
    finally:
        limpiar_contexto()

    latencia_ms = round((time.perf_counter() - inicio) * 1000, 2)
    log.info("http", metodo=request.method, ruta=request.url.path, latencia_ms=latencia_ms)

    resp.headers["X-Trace-Id"] = trace_id
    resp.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["Referrer-Policy"] = "no-referrer"
    resp.headers["Content-Security-Policy"] = (
        "default-src 'self'; img-src 'self' data:; style-src 'self'; "
        "script-src 'self'; frame-ancestors 'none'; base-uri 'none'"
    )
    resp.headers["Cache-Control"] = "no-store"
    return resp


def _sobre(
    codigo: str, mensaje: str, trace_id: str, detalle: dict[str, object] | None = None
) -> dict[str, object]:
    """Sobre de error idéntico al de /api/v1 (§3.6) y ErrorStandard."""
    return {
        "error": {
            "codigo": codigo,
            "code": codigo.lower(),
            "mensaje": mensaje,
            "message": mensaje,
            "detalle": detalle,
            "trace_id": trace_id,
            "timestamp": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        }
    }


# ------------------------------------------------------- manejadores de error
@app.exception_handler(AppError)
async def _app_error(request: Request, exc: AppError) -> JSONResponse:
    trace_id = getattr(request.state, "trace_id", "") or f"tr_{uuid.uuid4().hex[:24]}"
    nivel = log.warning if exc.http < 500 else log.error
    nivel("admin.error", codigo=exc.codigo, http=exc.http, ruta=request.url.path)
    return JSONResponse(
        status_code=exc.http,
        content=_sobre(exc.codigo, exc.mensaje, trace_id, exc.detalle),
        headers={"X-Trace-Id": trace_id},
    )


@app.exception_handler(StarletteHTTPException)
async def _http_exception(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    trace_id = getattr(request.state, "trace_id", "") or f"tr_{uuid.uuid4().hex[:24]}"
    codigo_map = {
        400: "PETICION_INVALIDA",
        401: "TOKEN_INVALIDO",
        403: "ROL_STAFF_INSUFICIENTE",
        404: "RECURSO_NO_ENCONTRADO",
        405: "METODO_NO_PERMITIDO",
        413: "CUERPO_DEMASIADO_GRANDE",
        429: "RATE_LIMIT_EXCEDIDO",
    }
    codigo = codigo_map.get(exc.status_code, "ERROR_HTTP")
    mensaje = exc.detail if isinstance(exc.detail, str) else "Error en la petición HTTP."
    headers = dict(exc.headers or {})
    headers["X-Trace-Id"] = trace_id
    return JSONResponse(
        status_code=exc.status_code,
        content=_sobre(codigo, mensaje, trace_id),
        headers=headers,
    )


@app.exception_handler(RequestValidationError)
async def _validacion(request: Request, exc: RequestValidationError) -> JSONResponse:
    trace_id = getattr(request.state, "trace_id", "") or f"tr_{uuid.uuid4().hex[:24]}"
    campos = [
        {"campo": ".".join(str(p) for p in e["loc"][1:]), "error": e["msg"]}
        for e in exc.errors()
    ]
    return JSONResponse(
        status_code=422,
        content=_sobre(
            "VALIDACION_ENTRADA",
            "Los datos enviados no son válidos.",
            trace_id,
            {"campos": campos},
        ),
        headers={"X-Trace-Id": trace_id},
    )


@app.exception_handler(Exception)
async def _no_controlado(request: Request, exc: Exception) -> JSONResponse:
    """Los 5xx no exponen ni el nombre de la excepción (§3.6, defecto BE-F39)."""
    trace_id = getattr(request.state, "trace_id", "") or f"tr_{uuid.uuid4().hex[:24]}"
    log.error("admin.error_no_controlado", ruta=request.url.path, excepcion=type(exc).__name__)
    return JSONResponse(
        status_code=500,
        content=_sobre(
            "ERROR_INTERNO",
            "Se ha producido un error interno. Contacta con la plataforma indicando "
            "el identificador de traza.",
            trace_id,
        ),
        headers={"X-Trace-Id": trace_id},
    )


# ----------------------------------------------------------------- routers
def registrar_routers() -> None:
    """Monta los routers del capítulo 18.

    Se hace en una función para que las pruebas puedan construir la aplicación
    sin arrancar el ciclo de vida completo.
    """
    from .routers import admin_audit, auth, business, grants, health, ops, staff

    app.include_router(health.router)  # §18.31
    app.include_router(auth.router)  # §18.1 – §18.8
    app.include_router(staff.router)  # §18.9 – §18.12
    app.include_router(grants.router)  # §18.13 – §18.15
    app.include_router(business.router)  # §18.16 – §18.23
    app.include_router(ops.router)  # §18.24 – §18.28
    app.include_router(admin_audit.router)  # §18.29 – §18.30


registrar_routers()

# ----------------------------------------------------------------- openapi 3.0.3
TAGS_METADATA = [
    {
        "name": "Salud",
        "description": "Sonda de disponibilidad e integridad de dependencias de la consola.",
    },
    {
        "name": "Identidad y sesión",
        "description": (
            "Autenticación de personal con MFA obligatorio, rotación de sesiones y "
            "recuperación."
        ),
    },
    {
        "name": "Gestión del personal",
        "description": (
            "Ciclo de vida de empleados de KalliCode: invitaciones, roles y desactivación."
        ),
    },
    {
        "name": "Concesiones de acceso",
        "description": (
            "Solicitud, consulta y revocación de concesiones temporales justificadas."
        ),
    },
    {
        "name": "Consola de negocio",
        "description": (
            "Métricas globales, clientes, suscripciones, tokens y reportes analíticos."
        ),
    },
    {
        "name": "Consola de operaciones",
        "description": (
            "Telemetría de agentes, colas, modelos de IA y acuerdos de nivel de servicio (SLA)."
        ),
    },
    {
        "name": "Auditoría del personal",
        "description": (
            "Registro append-only inmutable de acciones de personal y exportación certificada."
        ),
    },
]


def custom_openapi() -> dict[str, Any]:
    """Genera y congela la especificación OpenAPI 3.0.3 con esquemas globales."""
    if app.openapi_schema:
        return app.openapi_schema

    openapi_schema = get_openapi(
        title=app.title,
        version=app.version,
        openapi_version="3.0.3",
        description=app.description,
        routes=app.routes,
        tags=TAGS_METADATA,
    )

    # 1. Congelar versión exacta a OpenAPI 3.0.3
    openapi_schema["openapi"] = "3.0.3"

    # 2. Inyectar esquema de seguridad BearerAuth
    components = openapi_schema.setdefault("components", {})
    security_schemes = components.setdefault("securitySchemes", {})
    security_schemes["BearerAuth"] = {
        "type": "http",
        "scheme": "bearer",
        "bearerFormat": "JWT",
        "description": (
            "Token de acceso de personal (typ=staff, iss=kallicode-admin, aud=admin-v1)"
        ),
    }

    # 3. Inyectar esquemas globales estandarizados
    schemas = components.setdefault("schemas", {})
    schemas["ErrorStandard"] = {
        "type": "object",
        "title": "ErrorStandard",
        "required": ["codigo", "mensaje", "detalle", "trace_id", "timestamp"],
        "properties": {
            "codigo": {
                "type": "string",
                "title": "Codigo",
                "description": "Código de error canónico en mayúsculas",
            },
            "code": {
                "type": "string",
                "title": "Code",
                "description": "Código canónico en minúsculas",
            },
            "mensaje": {
                "type": "string",
                "title": "Mensaje",
                "description": "Descripción legible del error",
            },
            "detalle": {
                "type": "object",
                "title": "Detalle",
                "nullable": True,
                "description": "Metadatos adicionales del fallo",
            },
            "trace_id": {
                "type": "string",
                "title": "Trace Id",
                "description": "Identificador único de correlación y traza",
            },
            "timestamp": {
                "type": "string",
                "format": "date-time",
                "title": "Timestamp",
                "description": "Momento de la ocurrencia en UTC",
            },
        },
    }

    schemas["CustomerSummary"] = {
        "type": "object",
        "title": "CustomerSummary",
        "required": ["tenant_id", "name", "plan", "status"],
        "properties": {
            "tenant_id": {
                "type": "string",
                "title": "Tenant Id",
                "description": "Identificador de la organización del cliente",
            },
            "name": {
                "type": "string",
                "title": "Name",
                "description": (
                    "Razón social del cliente (enmascarada por defecto salvo concesión activa)"
                ),
            },
            "plan": {
                "type": "string",
                "title": "Plan",
                "description": "Plan contratado actualmente",
            },
            "status": {
                "type": "string",
                "title": "Status",
                "description": "Estado de la suscripción (activa, suspendida, etc.)",
            },
            "created_at": {
                "type": "string",
                "format": "date-time",
                "title": "Created At",
                "description": "Momento del alta del cliente",
            },
        },
    }

    # 4. Esquema global de seguridad para operaciones protegidas
    openapi_schema["security"] = [{"BearerAuth": []}]

    app.openapi_schema = openapi_schema
    return app.openapi_schema


app.openapi = custom_openapi  # type: ignore[method-assign]
