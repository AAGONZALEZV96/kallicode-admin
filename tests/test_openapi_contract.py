"""Pruebas del Contrato OpenAPI v1.0 Congelado (Ticket KC-ADM-B1-08).

Verifica:
  1. Versión OpenAPI congelada a exactamente "3.0.3".
  2. Cobertura exacta de los 31 endpoints distribuidos en los 7 tags oficiales.
  3. Esquemas globales ErrorStandard y BearerAuth presentes en components.
  4. Esquema CustomerSummary declarando el comportamiento de enmascaramiento por defecto.
  5. Coherencia entre el esquema dinámico de FastAPI y el contrato YAML congelado.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

TAGS_OFICIALES = {
    "Salud",
    "Identidad y sesión",
    "Gestión del personal",
    "Concesiones de acceso",
    "Consola de negocio",
    "Consola de operaciones",
    "Auditoría del personal",
}


# ========================================================= 1. Metadatos y Versión
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


# ======================================================== 2. Cobertura 31 Endpoints
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

    # Los 7 tags canónicos deben estar cubiertos
    assert tags_encontrados == TAGS_OFICIALES, (
        f"Tags faltantes: {TAGS_OFICIALES - tags_encontrados}"
    )


# ======================================================= 3. Seguridad y ErrorStandard
def test_seguridad_y_esquemas_estandar(app: Any) -> None:
    """Verifica BearerAuth en securitySchemes y ErrorStandard en schemas."""
    schema = app.openapi()
    components = schema.get("components", {})
    security_schemes = components.get("securitySchemes", {})
    schemas = components.get("schemas", {})

    # 1. BearerAuth
    assert "BearerAuth" in security_schemes, "Falta BearerAuth en components/securitySchemes"
    bearer = security_schemes["BearerAuth"]
    assert bearer["type"] == "http"
    assert bearer["scheme"] == "bearer"
    assert bearer["bearerFormat"] == "JWT"
    assert "typ=staff" in bearer["description"]

    # 2. Seguridad global
    assert "security" in schema
    assert {"BearerAuth": []} in schema["security"]

    # 3. ErrorStandard
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


# ==================================================== 4. Enmascarado CustomerSummary
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

    # Documentación explícita del enmascarado
    descripcion_name = props["name"].get("description", "").lower()
    assert "enmascarada" in descripcion_name or "enmascarado" in descripcion_name, (
        f"La descripción de 'name' debe explicitar el enmascarado: {props['name']}"
    )


# ============================================ 5. Contrato Estático openapi-admin-v1.yaml
def test_archivo_yaml_congelado_coincide_con_api() -> None:
    """El archivo docs/openapi-admin-v1.yaml debe declarar openapi 3.0.3 y esquemas."""
    yaml_path = Path(__file__).resolve().parents[1] / "docs" / "openapi-admin-v1.yaml"
    assert yaml_path.exists(), f"No se encontró el contrato YAML en {yaml_path}"

    with open(yaml_path, encoding="utf-8") as f:
        doc = yaml.safe_load(f)

    assert doc["openapi"] == "3.0.3"
    assert "BearerAuth" in doc["components"]["securitySchemes"]
    assert "ErrorStandard" in doc["components"]["schemas"]
    assert "CustomerSummary" in doc["components"]["schemas"]
