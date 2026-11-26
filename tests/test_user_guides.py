"""Pruebas de consistencia técnica para manuales de usuario (KC-ADM-B6-11).

Verifica estáticamente que todo lo documentado en docs/user_guides/*.md —rutas SPA de React,
endpoints FastAPI/OpenAPI, roles de personal, jerarquía de alcances de concesión, límites y
enlaces cruzados— coincida fielmente con el código fuente real del monorepo conforme a
AGENTS.md §8.3.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml
from admin_api.errors import CATALOGO_ERRORES
from admin_api.main import app
from admin_api.masking import JERARQUIA
from admin_api.security import STAFF_ROLES
from starlette.routing import Route

REPO_ROOT = Path(__file__).resolve().parent.parent
USER_GUIDES_DIR = REPO_ROOT / "docs" / "user_guides"
OPENAPI_FILE = REPO_ROOT / "docs" / "openapi-admin-v1.yaml"
APP_ROUTER_FILE = REPO_ROOT / "apps" / "web" / "src" / "router" / "AppRouter.tsx"
MODAL_CONCESION_FILE = (
    REPO_ROOT / "apps" / "web" / "src" / "componentes" / "SolicitudConcesionModal.tsx"
)
AUTH_STATE_FILE = REPO_ROOT / "apps" / "web" / "src" / "estado" / "auth.tsx"
LIVE_REFRESH_FILE = REPO_ROOT / "apps" / "web" / "src" / "hooks" / "useLiveRefresh.ts"

GUIAS_ESPERADAS = (
    "admin_manual.md",
    "guia_soporte.md",
    "guia_operaciones.md",
    "guia_negocio.md",
    "guia_admin.md",
)

IDENTIFICADORES_STAFF_NO_ROL = {
    "staff_id",
    "staff_actions",
    "staff_accesses",
    "staff_managed",
    "staff_refresh_tokens",
    "staff_actual",
}


def _leer_guias() -> dict[str, str]:
    archivos = sorted(USER_GUIDES_DIR.glob("*.md"))
    return {archivo.name: archivo.read_text(encoding="utf-8") for archivo in archivos}


def _normalizar_ruta_api(ruta: str) -> str:
    limpia = ruta.split("?", 1)[0].rstrip(".,:;)`'\"*")
    return re.sub(r"\$\{[^}]+\}|\{[^}]+\}", "{param}", limpia)


def _normalizar_ruta_spa(ruta: str) -> str:
    limpia = ruta.split("?", 1)[0].rstrip(".,:;)`'\"*")
    return re.sub(r":[A-Za-z0-9_]+", ":param", limpia)


def _rutas_spa_reales() -> set[str]:
    texto = APP_ROUTER_FILE.read_text(encoding="utf-8")
    encontradas = set(re.findall(r'<Route\s+path="([^"]+)"', texto))
    return {_normalizar_ruta_spa(r) for r in encontradas if r != "*"}


def _rutas_fastapi_normalizadas() -> set[str]:
    rutas: set[str] = set()
    for route in app.routes:
        if isinstance(route, Route) and route.path:
            rutas.add(_normalizar_ruta_api(route.path))
    return rutas


def _rutas_openapi_normalizadas() -> set[str]:
    spec = yaml.safe_load(OPENAPI_FILE.read_text(encoding="utf-8"))
    return {_normalizar_ruta_api(p) for p in spec.get("paths", {})}


def test_user_guides_archivos_obligatorios_y_enlaces_existen() -> None:
    """Deben existir admin_manual.md, las 4 guías por rol y enlaces válidos."""
    guias = _leer_guias()
    for nombre in GUIAS_ESPERADAS:
        assert nombre in guias, f"Falta guía obligatoria: {nombre}"

    maestro = guias["admin_manual.md"]
    for hija in GUIAS_ESPERADAS[1:]:
        assert hija in maestro, f"admin_manual.md debe referenciar a {hija}"

    patron_enlace = re.compile(r"\]\(([^)]+)\)")
    for nombre, texto in guias.items():
        assert "file://" not in texto, f"Ruta local file:// prohibida en {nombre}"
        assert "/home/" not in texto, f"Ruta local /home/ prohibida en {nombre}"
        for destino in patron_enlace.findall(texto):
            if destino.startswith(("http://", "https://", "#")):
                continue
            ruta_rel = (USER_GUIDES_DIR / destino.split("#", 1)[0]).resolve()
            assert ruta_rel.exists(), f"Enlace relativo roto {destino!r} en {nombre}"
            assert ruta_rel.is_relative_to(REPO_ROOT), f"Enlace fuera del repo: {destino!r}"


def test_user_guides_rutas_spa_existen_en_app_router() -> None:
    """Toda ruta SPA citada en docs/user_guides/*.md debe existir en AppRouter.tsx."""
    guias = _leer_guias()
    rutas_spa = _rutas_spa_reales()

    patron_spa_backtick = re.compile(
        r"`(/(?:login|mfa|403|overview|customers(?:/:[A-Za-z0-9_]+)?|"
        r"subscriptions|tokens|staff|audit[A-Za-z0-9_-]*|"
        r"business/(?:overview|customers(?:/:[A-Za-z0-9_]+)?|subscriptions|tokens)|"
        r"ops/(?:agents|models|sla|queues))|/)`"
    )

    vistas_cubiertas: set[str] = set()
    for nombre, texto in guias.items():
        for ruta in patron_spa_backtick.findall(texto):
            norm = _normalizar_ruta_spa(ruta)
            vistas_cubiertas.add(norm)
            assert norm in rutas_spa, (
                f"Ruta SPA inexistente {ruta!r} citada en {nombre}. "
                f"Rutas reales en AppRouter.tsx: {sorted(rutas_spa)}"
            )

    requeridas = {
        "/login",
        "/mfa",
        "/403",
        "/overview",
        "/business/customers",
        "/business/customers/:param",
        "/business/subscriptions",
        "/business/tokens",
        "/ops/agents",
        "/ops/models",
        "/ops/sla",
    }
    assert requeridas.issubset(vistas_cubiertas)


def test_user_guides_endpoints_existen_en_fastapi_y_openapi() -> None:
    """Todo endpoint API citado en docs/user_guides/*.md debe existir en FastAPI/OpenAPI."""
    guias = _leer_guias()
    rutas_app = _rutas_fastapi_normalizadas()
    rutas_spec = _rutas_openapi_normalizadas()

    patron_endpoint = re.compile(r"(?:/admin/v1/[A-Za-z0-9_{}$/-]+|/api/v1/[A-Za-z0-9_{}$/-]+)")

    encontrados: set[str] = set()
    for nombre, texto in guias.items():
        for match in patron_endpoint.findall(texto):
            norm = _normalizar_ruta_api(match)
            if norm.endswith("/*") or match.rstrip(")") == "/admin/v1":
                continue
            encontrados.add(norm)
            assert norm in rutas_app, (
                f"Endpoint inexistente {match!r} citado en {nombre}. "
                f"Rutas reales: {sorted(rutas_app)}"
            )
            if norm.startswith("/admin/v1/") and norm not in (
                "/admin/v1/metrics",
                "/admin/v1/business/summary",
            ):
                assert (
                    norm in rutas_spec
                ), f"Endpoint {match!r} en {nombre} no figura en openapi-admin-v1.yaml"

    esenciales = {
        "/admin/v1/auth/login",
        "/admin/v1/auth/mfa/enroll",
        "/admin/v1/auth/mfa/verify",
        "/admin/v1/access-grants",
        "/admin/v1/access-grants/{param}",
        "/admin/v1/business/overview",
        "/admin/v1/business/customers",
        "/admin/v1/business/customers/{param}",
        "/admin/v1/business/subscriptions",
        "/admin/v1/business/upgrade-requests",
        "/admin/v1/business/usage/tokens",
        "/admin/v1/business/reports",
        "/admin/v1/ops/agents",
        "/admin/v1/ops/queues",
        "/admin/v1/ops/models",
        "/admin/v1/ops/sla",
        "/admin/v1/ops/sla/cases/{param}",
        "/admin/v1/staff/invitations",
        "/admin/v1/staff/{param}",
        "/admin/v1/audit/staff-actions",
        "/api/v1/audit/staff-accesses",
    }
    assert esenciales.issubset(encontrados)


def test_user_guides_roles_alcances_y_limites_coinciden_con_modelo() -> None:
    """Valida roles STAFF_ROLES, alcances JERARQUIA, códigos de error y umbrales reales."""
    guias = _leer_guias()
    roles_reales = set(STAFF_ROLES)
    errores_reales = set(CATALOGO_ERRORES.keys())

    modal_src = MODAL_CONCESION_FILE.read_text(encoding="utf-8")
    auth_src = AUTH_STATE_FILE.read_text(encoding="utf-8")
    live_src = LIVE_REFRESH_FILE.read_text(encoding="utf-8")

    # Verificar que los 3 alcances de JERARQUIA existen idénticos en SolicitudConcesionModal.tsx
    for alcance in JERARQUIA:
        assert f'"{alcance}"' in modal_src
    assert "TIEMPO_INACTIVIDAD_MS = 15 * 60 * 1000" in auth_src
    assert "presupuestoMaximoPorMinuto = 60" in live_src

    patron_rol = re.compile(r"\bstaff_[a-z_]+\b")
    patron_error = re.compile(
        r"\b(?:TELEMETRIA|AGREGADO|STAFF|ROL_STAFF|CONFLICTO|TOKEN|MFA|CONCESION|MOTIVO)_[A-Z_]+\b"
    )
    roles_vistos: set[str] = set()

    for nombre, texto in guias.items():
        for rol in patron_rol.findall(texto):
            if rol in IDENTIFICADORES_STAFF_NO_ROL:
                continue
            roles_vistos.add(rol)
            assert rol in roles_reales, f"Rol desconocido {rol!r} en {nombre}"

        for err_code in patron_error.findall(texto):
            if err_code in {"STAFF_ROLES", "STAFF_ID"}:
                continue
            assert err_code in errores_reales, f"Código AppError inexistente {err_code!r}"

    assert roles_vistos == roles_reales

    manual = guias["admin_manual.md"]
    soporte = guias["guia_soporte.md"]
    for alcance in JERARQUIA:
        assert alcance in manual, f"Alcance {alcance!r} debe documentarse en admin_manual.md"
        assert alcance in soporte, f"Alcance {alcance!r} debe documentarse en guia_soporte.md"
