"""Pruebas de congelación de contrato /admin/v1 y política de versionado (KC-ADM-B6-13).

Complementa `tests/test_openapi_contract.py` validando sin necesidad de BD ni red:
1. Inmutabilidad de `docs/openapi-admin-v1.yaml` (versión 1.0.0, 31 operaciones y
   huella SHA-256 congelada).
2. Ausencia de *breaking changes* en `app.openapi()` vivo respecto al contrato v1.0.0
   (ninguna ruta eliminada, ningún parámetro requerido añadido, esquemas críticos intactos
   y catálogo `_ERRORES_ADMIN` preservado).
3. Consistencia documental y enlaces portables en `docs/politica_contrato_admin.md`.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import yaml
from admin_api.errors import _ERRORES_ADMIN, CATALOGO_ERRORES
from admin_api.main import app

REPO_ROOT = Path(__file__).resolve().parent.parent
OPENAPI_FILE = REPO_ROOT / "docs" / "openapi-admin-v1.yaml"
POLITICA_FILE = REPO_ROOT / "docs" / "politica_contrato_admin.md"

SHA256_ARCHIVO_CONGELADO = "092541b0e37858c396dda59eb4f47cb4f1e011a4bb27050dced71dbc9331a43c"
SHA256_CANONICO_CONGELADO = "ce5d2c918d57d45477e4d637855784919088e3016f9f7e28d9885351c85ebcee"

METODOS_HTTP = frozenset({"get", "post", "put", "patch", "delete"})
TAGS_CANONICOS = {
    "Salud",
    "Identidad y sesión",
    "Gestión del personal",
    "Concesiones de acceso",
    "Consola de negocio",
    "Consola de operaciones",
    "Auditoría del personal",
}


def _cargar_contrato_congelado() -> dict:
    return yaml.safe_load(OPENAPI_FILE.read_text(encoding="utf-8"))  # type: ignore[no-any-return]


# =============================================================================
# 1. Verificación de línea base congelada en docs/openapi-admin-v1.yaml
# =============================================================================
def test_contrato_openapi_v1_congelado_metadata_y_operaciones() -> None:
    """docs/openapi-admin-v1.yaml debe permanecer congelado en v1.0.0 (31 operaciones)."""
    assert OPENAPI_FILE.exists(), f"Falta contrato congelado: {OPENAPI_FILE}"
    raw_bytes = OPENAPI_FILE.read_bytes()
    doc = yaml.safe_load(raw_bytes.decode("utf-8"))

    assert doc["openapi"] == "3.0.3"
    assert doc["info"]["version"] == "1.0.0"

    raw_sha = hashlib.sha256(raw_bytes).hexdigest()
    canon_bytes = json.dumps(doc, sort_keys=True, ensure_ascii=False).encode("utf-8")
    canon_sha = hashlib.sha256(canon_bytes).hexdigest()

    assert raw_sha == SHA256_ARCHIVO_CONGELADO, (
        "docs/openapi-admin-v1.yaml ha sido modificado tras la congelación v1.0.0 "
        f"(SHA-256 esperado {SHA256_ARCHIVO_CONGELADO}, obtenido {raw_sha}). "
        "Si es un breaking change, crea /admin/v2 según docs/politica_contrato_admin.md."
    )
    assert canon_sha == SHA256_CANONICO_CONGELADO

    operaciones = [
        (metodo.upper(), ruta)
        for ruta, item in doc.get("paths", {}).items()
        for metodo in item
        if metodo.lower() in METODOS_HTTP
    ]
    assert len(operaciones) == 31
    assert all(ruta.startswith("/admin/v1/") for _, ruta in operaciones)


# =============================================================================
# 2. Detección de Breaking Changes entre FastAPI vivo y YAML v1.0.0
# =============================================================================
def test_fastapi_vivo_sin_breaking_changes_respecto_a_openapi_v1() -> None:
    """La app FastAPI viva no debe introducir breaking changes frente a v1.0.0."""
    doc = _cargar_contrato_congelado()
    vivo = app.openapi()

    assert vivo["openapi"] == "3.0.3"

    ops_doc = {
        (m.upper(), p)
        for p, item in doc.get("paths", {}).items()
        for m in item
        if m.lower() in METODOS_HTTP
    }
    ops_vivo = {
        (m.upper(), p)
        for p, item in vivo.get("paths", {}).items()
        for m in item
        if m.lower() in METODOS_HTTP
    }

    eliminadas = ops_doc - ops_vivo
    assert not eliminadas, f"Operaciones eliminadas de /admin/v1: {sorted(eliminadas)}"

    # Ninguna operación puede añadir parámetros obligatorios nuevos ni borrar previos
    for metodo, ruta in sorted(ops_doc):
        op_d = doc["paths"][ruta][metodo.lower()]
        op_v = vivo["paths"][ruta][metodo.lower()]

        params_d = {
            (x["in"], x["name"]): bool(x.get("required")) for x in op_d.get("parameters", [])
        }
        params_v = {
            (x["in"], x["name"]): bool(x.get("required")) for x in op_v.get("parameters", [])
        }

        for clave in params_d:
            assert clave in params_v, f"Parámetro eliminado en {metodo} {ruta}: {clave}"
        for clave, es_req in params_v.items():
            if es_req and not params_d.get(clave, False):
                raise AssertionError(
                    f"Nuevo parámetro obligatorio {clave} rompe {metodo} {ruta}"
                )

    # Esquemas presentes, sin campos requeridos borrados ni nuevos requeridos de entrada
    schemas_d = doc.get("components", {}).get("schemas", {})
    schemas_v = vivo.get("components", {}).get("schemas", {})
    assert not (set(schemas_d) - set(schemas_v))

    for nombre, sch_d in schemas_d.items():
        sch_v = schemas_v[nombre]
        req_d = set(sch_d.get("required", []))
        req_v = set(sch_v.get("required", []))
        assert not (req_d - req_v), f"Campos requeridos eliminados en {nombre}: {req_d - req_v}"
        if nombre.endswith("In"):
            assert not (
                req_v - req_d
            ), f"Nuevos campos requeridos de entrada en {nombre}: {req_v - req_d}"

    # Todos los códigos de error canónicos de admin_api permanecen registrados
    for codigo in _ERRORES_ADMIN:
        assert codigo in CATALOGO_ERRORES


# =============================================================================
# 3. Validación documental de docs/politica_contrato_admin.md
# =============================================================================
def test_politica_contrato_admin_consistente_y_portable() -> None:
    """docs/politica_contrato_admin.md debe ser portable y coherente con el código real."""
    assert POLITICA_FILE.exists(), f"Falta documento de política: {POLITICA_FILE}"
    texto = POLITICA_FILE.read_text(encoding="utf-8")

    assert "file://" not in texto, "Prohibidos enlaces file:// en politica_contrato_admin.md"
    assert "/home/" not in texto, "Prohibidas rutas /home/ en politica_contrato_admin.md"

    for destino in re.findall(r"\]\(([^)]+)\)", texto):
        if destino.startswith(("http://", "https://", "#")):
            continue
        resuelto = (POLITICA_FILE.parent / destino.split("#", 1)[0]).resolve()
        assert resuelto.exists(), f"Enlace relativo roto en política: {destino!r}"
        assert resuelto.is_relative_to(REPO_ROOT)

    for fragmento in (
        "1.0.0",
        "/admin/v1",
        "/admin/v2",
        "31",
        "Deprecation",
        "Sunset",
        "Link",
        "Scrum de Scrums",
        "Architecture Board",
        "docs/adr/",
        'extra="forbid"',
        SHA256_ARCHIVO_CONGELADO,
        SHA256_CANONICO_CONGELADO,
    ):
        assert fragmento in texto, f"Falta referencia clave: {fragmento!r}"

    for tag in TAGS_CANONICOS:
        assert tag in texto, f"Falta tag oficial {tag!r} en politica_contrato_admin.md"

    for codigo in _ERRORES_ADMIN:
        assert codigo in texto, f"Falta código {codigo!r} en politica_contrato_admin.md"
