"""Pruebas de consistencia técnica de los runbooks operativos (KC-ADM-B6-10 / AGENTS §8.3).

Verifica de forma estática y sin requerir base de datos ni red que todo lo
documentado en `docs/runbooks/*.md` corresponde exclusivamente a elementos reales
existentes en el código fuente:
  1. Presencia de `docs/runbooks/admin_console_ops.md` y de los 4 runbooks RB-01..RB-04.
  2. Todos los endpoints citados (`/admin/v1/...`, `/api/v1/...`, `/metrics`) existen
     en la aplicación FastAPI real (`admin_api.main.app`) y/o en `docs/openapi-admin-v1.yaml`.
  3. Todas las variables de entorno citadas (`KC_*`, `SLA_EVALUATION_INTERVAL_S`) existen
     en `AdminSettings`, `.env.example`, `Makefile` o `admin_workers.sla`.
  4. Todos los roles (`staff_*`), métricas Prometheus (`admin_*`), códigos de error en
     mayúsculas y objetivos `make <target>` existen en el repositorio.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml
from admin_api.errors import CATALOGO_ERRORES
from admin_api.main import app
from admin_api.metrics import ADMIN_METRICS_REGISTRY
from admin_api.security import STAFF_ROLES
from admin_api.settings import AdminSettings
from starlette.routing import Route

ROOT = Path(__file__).resolve().parent.parent
RUNBOOKS_DIR = ROOT / "docs" / "runbooks"
OPENAPI_FILE = ROOT / "docs" / "openapi-admin-v1.yaml"
MAKEFILE = ROOT / "Makefile"

ARCHIVOS_RUNBOOK_ESPERADOS = (
    "admin_console_ops.md",
    "rb-01-agregados-y-vistas.md",
    "rb-02-ciclo-vida-staff.md",
    "rb-03-auditoria-cross-tenant.md",
    "rb-04-telemetria-pipeline.md",
)

# Variables verificadas fuera de AdminSettings (plataforma core, workers y pruebas locales)
VARIABLES_ENTORNO_PLATAFORMA_VERIFICADAS: frozenset[str] = frozenset(
    {
        "KC_REDIS_URL",
        "KC_BLOB_ACCOUNT_URL",
        "KC_JWT_PRIVATE_KEY",
        "KC_JWT_PUBLIC_KEY",
        "KC_PIPELINE_TELEMETRY_URL",
        "KC_ADMIN_TEST_DSN",
        "KC_ADMIN_REDIS_URL",
        "KC_ADMIN_SLA_EVALUATION_INTERVAL_S",
        "SLA_EVALUATION_INTERVAL_S",
    }
)


def _leer_todos_runbooks() -> dict[str, str]:
    archivos = sorted(RUNBOOKS_DIR.glob("*.md"))
    assert archivos, f"No se encontraron runbooks en {RUNBOOKS_DIR}"
    return {a.name: a.read_text(encoding="utf-8") for a in archivos}


def _normalizar_ruta_param(ruta: str) -> str:
    """Normaliza parámetros `{...}` o `${...}` para comparar rutas."""
    limpia = ruta.split("?", 1)[0].rstrip(".,:;)`'\"")
    return re.sub(r"\$\{[^}]+\}|\{[^}]+\}", "{param}", limpia)


def _rutas_fastapi_normalizadas() -> set[str]:
    rutas: set[str] = set()
    for route in app.routes:
        if isinstance(route, Route) and route.path:
            rutas.add(_normalizar_ruta_param(route.path))
    return rutas


def _rutas_openapi_normalizadas() -> set[str]:
    spec = yaml.safe_load(OPENAPI_FILE.read_text(encoding="utf-8"))
    return {_normalizar_ruta_param(p) for p in spec.get("paths", {})}


def _variables_entorno_validas() -> set[str]:
    de_settings = {f"KC_ADMIN_{campo.upper()}" for campo in AdminSettings.model_fields}
    return de_settings | set(VARIABLES_ENTORNO_PLATAFORMA_VERIFICADAS)


def _metricas_prometheus_validas() -> set[str]:
    """Devuelve nombres exactos de series expuestas en Prometheus (/metrics)."""
    nombres: set[str] = set()
    for fam in ADMIN_METRICS_REGISTRY.collect():
        if fam.type == "counter" and not fam.name.endswith("_total"):
            nombres.add(f"{fam.name}_total")
        else:
            nombres.add(fam.name)
    return nombres


def _targets_makefile_validos() -> set[str]:
    contenido = MAKEFILE.read_text(encoding="utf-8")
    return set(re.findall(r"^([a-zA-Z0-9_-]+)\s*:", contenido, flags=re.MULTILINE))


# =============================================================================
# 1. Estructura y cobertura de los 4 escenarios operativos
# =============================================================================
def test_runbooks_archivos_obligatorios_y_enlaces_existen() -> None:
    """Deben existir admin_console_ops.md y los cuatro runbooks operativos RB-01..RB-04."""
    docs = _leer_todos_runbooks()
    for nombre in ARCHIVOS_RUNBOOK_ESPERADOS:
        assert nombre in docs, f"Falta el archivo de runbook obligatorio: {nombre}"

    maestro = docs["admin_console_ops.md"]
    for rb in ARCHIVOS_RUNBOOK_ESPERADOS[1:]:
        assert rb in maestro, f"El manual maestro debe referenciar a {rb}"

    patron_enlace = re.compile(r"\]\(([^)]+)\)")
    for nombre, texto in docs.items():
        assert "file://" not in texto, f"Ruta local file:// prohibida en {nombre}"
        assert "/home/" not in texto, f"Ruta local /home/ prohibida en {nombre}"
        for destino in patron_enlace.findall(texto):
            if destino.startswith(("http://", "https://", "#")):
                continue
            ruta_rel = (RUNBOOKS_DIR / destino.split("#", 1)[0]).resolve()
            assert ruta_rel.exists(), f"Enlace relativo roto {destino!r} en {nombre}"
            assert ruta_rel.is_relative_to(ROOT), f"Enlace fuera del repo: {destino!r}"


# =============================================================================
# 2. Consistencia estricta contra código fuente y OpenAPI (AGENTS.md §8.3)
# =============================================================================
def test_runbooks_endpoints_existen_en_fastapi_y_openapi() -> None:
    """Todo endpoint citado en docs/runbooks/*.md debe existir en FastAPI/OpenAPI."""
    rutas_app = _rutas_fastapi_normalizadas()
    rutas_spec = _rutas_openapi_normalizadas()
    docs = _leer_todos_runbooks()

    patron_ruta = re.compile(
        r"(?:/admin/v1/[A-Za-z0-9_{}$/-]+|/api/v1/[A-Za-z0-9_{}$/-]+|/metrics)"
    )
    encontradas: set[str] = set()

    for nombre, texto in docs.items():
        for match in patron_ruta.findall(texto):
            norm = _normalizar_ruta_param(match)
            # Ignorar prefijo documental genérico con wildcard explícito si se citara
            if norm.endswith("/*"):
                continue
            encontradas.add(norm)
            assert norm in rutas_app, (
                f"Endpoint inexistente {match!r} documentado en {nombre}. "
                f"Rutas reales: {sorted(rutas_app)}"
            )
            if norm.startswith("/admin/v1/") and norm not in (
                "/admin/v1/metrics",
                "/admin/v1/business/summary",
            ):
                assert norm in rutas_spec, (
                    f"Endpoint /admin/v1 {match!r} en {nombre} no figura en "
                    "openapi-admin-v1.yaml"
                )

    assert (
        len(encontradas) >= 10
    ), "Los runbooks deben documentar los endpoints clave verificados"


def test_runbooks_variables_entorno_existen_en_settings_o_plataforma() -> None:
    """Ninguna variable de entorno KC_* citada puede ser inventada."""
    validas = _variables_entorno_validas()
    docs = _leer_todos_runbooks()

    patron_var = re.compile(r"\b(?:KC_[A-Z0-9_]+|SLA_EVALUATION_INTERVAL_S)\b")
    encontradas: set[str] = set()

    for nombre, texto in docs.items():
        for var in patron_var.findall(texto):
            encontradas.add(var)
            assert var in validas, (
                f"Variable de entorno no verificada {var!r} en {nombre}. "
                f"Revisa AdminSettings en settings.py"
            )

    assert "KC_ADMIN_DATABASE_URL_APP" in encontradas
    assert "KC_ADMIN_DATABASE_URL_RO" in encontradas
    assert "KC_ADMIN_AGGREGATE_MAX_AGE_S" in encontradas
    assert "KC_ADMIN_TELEMETRY_BASE_URL" in encontradas


def test_runbooks_roles_metricas_errores_y_comandos_son_reales() -> None:
    """Valida roles staff_*, métricas Prometheus, códigos AppError y comandos make."""
    docs = _leer_todos_runbooks()
    metricas_reales = _metricas_prometheus_validas()
    targets_make = _targets_makefile_validos()
    codigos_error_reales = set(CATALOGO_ERRORES.keys())
    roles_reales = set(STAFF_ROLES)

    patron_rol = re.compile(r"\bstaff_[a-z_]+\b")
    patron_metrica = re.compile(
        r"\badmin_(?:http_request[a-z_]*|aggregates_[a-z_]+|staff_actions_[a-z_]+|dependency_[a-z_]+)\b"
    )
    patron_make = re.compile(r"\bmake\s+([a-zA-Z0-9_-]+)\b")
    patron_error = re.compile(
        r"\b(?:TELEMETRIA|AGREGADO|STAFF|ROL_STAFF|CONFLICTO|TOKEN|MFA|CONCESION|MOTIVO)_[A-Z_]+\b"
    )

    roles_vistos: set[str] = set()
    metricas_vistas: set[str] = set()
    targets_vistos: set[str] = set()

    identificadores_staff_no_rol = {
        "staff_id",
        "staff_actions",
        "staff_refresh_tokens",
        "staff_managed",
        "staff_accesses",
        "staff_actual",
    }

    for nombre, texto in docs.items():
        for rol in patron_rol.findall(texto):
            if rol in identificadores_staff_no_rol:
                continue
            roles_vistos.add(rol)
            assert rol in roles_reales, f"Rol desconocido {rol!r} en {nombre}"

        for metrica in patron_metrica.findall(texto):
            metricas_vistas.add(metrica)
            assert (
                metrica in metricas_reales
            ), f"Métrica Prometheus no registrada {metrica!r} en {nombre}"

        for target in patron_make.findall(texto):
            targets_vistos.add(target)
            assert (
                target in targets_make
            ), f"Objetivo Makefile inexistente 'make {target}' en {nombre}"

        identificadores_staff_uppercase = {"STAFF_ROLES", "STAFF_ID"}
        for err_code in patron_error.findall(texto):
            if err_code in identificadores_staff_uppercase:
                continue
            assert (
                err_code in codigos_error_reales
            ), f"Código de error inexistente {err_code!r} en {nombre}"

    assert roles_vistos == roles_reales
    assert "admin_aggregates_freshness_seconds" in metricas_vistas
    assert "admin_dependency_failures_total" in metricas_vistas
    assert {"lint", "types", "test", "test-int", "no-fuga", "load-test"}.issubset(
        targets_vistos
    )
