"""Métricas Prometheus de observabilidad para la API de administración (KC-ADM-B6-08).

Expone series con cardinalidad estrictamente acotada y sin datos personales,
identificadores de tenant, staff_id ni consultas SQL en ninguna etiqueta.
"""

from __future__ import annotations

from typing import Any

from fastapi import Request
from prometheus_client import CONTENT_TYPE_LATEST, CollectorRegistry, Counter, Gauge, Histogram
from prometheus_client.exposition import generate_latest

ADMIN_METRICS_REGISTRY = CollectorRegistry(auto_describe=True)

HTTP_REQUEST_DURATION = Histogram(
    "admin_http_request_duration_seconds",
    "Latencia de las peticiones HTTP en la API de administración.",
    labelnames=("method", "route"),
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
    registry=ADMIN_METRICS_REGISTRY,
)

HTTP_REQUESTS_TOTAL = Counter(
    "admin_http_requests_total",
    "Total de peticiones HTTP atendidas por método, ruta normalizada y código.",
    labelnames=("method", "route", "status_code"),
    registry=ADMIN_METRICS_REGISTRY,
)

AGGREGATES_FRESHNESS_SECONDS = Gauge(
    "admin_aggregates_freshness_seconds",
    "Antigüedad en segundos del refresco más viejo de vistas materializadas.",
    labelnames=("vista",),
    registry=ADMIN_METRICS_REGISTRY,
)

STAFF_ACTIONS_TOTAL = Counter(
    "admin_staff_actions_total",
    "Total de acciones de personal registradas por rol y tipo de acción.",
    labelnames=("role", "action"),
    registry=ADMIN_METRICS_REGISTRY,
)

DEPENDENCY_FAILURES_TOTAL = Counter(
    "admin_dependency_failures_total",
    "Total de fallos detectados en dependencias o refrescos de observabilidad.",
    labelnames=("dependency",),
    registry=ADMIN_METRICS_REGISTRY,
)

_ROLES_SEGUROS: frozenset[str] = frozenset(
    {
        "staff_soporte",
        "staff_operaciones",
        "staff_negocio",
        "staff_admin",
    }
)

_DEPENDENCIAS_SEGURAS: frozenset[str] = frozenset(
    {
        "postgres",
        "lectura_analitica",
        "cache",
        "blob",
        "telemetria",
        "agregados",
        "telemetry_circuit_breaker",
    }
)


def obtener_ruta_normalizada(request: Request) -> str:
    """Devuelve la plantilla de ruta FastAPI o 'unmatched' para evitar alta cardinalidad/PII."""
    route: Any = request.scope.get("route")
    path = getattr(route, "path", None)
    if isinstance(path, str) and path.startswith("/"):
        return path
    return "unmatched"


def registrar_peticion_http(
    method: str,
    route: str,
    status_code: int,
    duration_s: float,
) -> None:
    """Registra latencia y conteo HTTP por ruta normalizada y método."""
    metodo = (method or "UNKNOWN").upper()
    ruta = route if route.startswith("/") else "unmatched"
    HTTP_REQUEST_DURATION.labels(method=metodo, route=ruta).observe(max(0.0, float(duration_s)))
    HTTP_REQUESTS_TOTAL.labels(
        method=metodo,
        route=ruta,
        status_code=str(int(status_code)),
    ).inc()


def registrar_frescura_agregados(vista: str, edad_s: float | int) -> None:
    """Actualiza el gauge de frescura (segundos) de las vistas materializadas."""
    vista_limpia = vista if vista in ("global", "business", "sla") else "global"
    AGGREGATES_FRESHNESS_SECONDS.labels(vista=vista_limpia).set(max(0.0, float(edad_s)))


def registrar_accion_personal_metrica(role: str, action: str) -> None:
    """Incrementa el contador de acciones de personal sin exponer staff_id ni tenant."""
    rol_limpio = role if role in _ROLES_SEGUROS else "otro"
    accion_limpia = action.strip().lower() if action else "desconocida"
    STAFF_ACTIONS_TOTAL.labels(role=rol_limpio, action=accion_limpia).inc()


def registrar_fallo_dependencia(dependency: str) -> None:
    """Incrementa el contador de fallos para una dependencia conocida."""
    dep = dependency if dependency in _DEPENDENCIAS_SEGURAS else "otra"
    DEPENDENCY_FAILURES_TOTAL.labels(dependency=dep).inc()


def renderizar_metricas_prometheus() -> tuple[bytes, str]:
    """Serializa el registro oficial en formato de exposición Prometheus."""
    return generate_latest(ADMIN_METRICS_REGISTRY), CONTENT_TYPE_LATEST


__all__ = [
    "ADMIN_METRICS_REGISTRY",
    "AGGREGATES_FRESHNESS_SECONDS",
    "DEPENDENCY_FAILURES_TOTAL",
    "HTTP_REQUESTS_TOTAL",
    "HTTP_REQUEST_DURATION",
    "STAFF_ACTIONS_TOTAL",
    "obtener_ruta_normalizada",
    "registrar_accion_personal_metrica",
    "registrar_fallo_dependencia",
    "registrar_frescura_agregados",
    "registrar_peticion_http",
    "renderizar_metricas_prometheus",
]
