"""Paginación y orden: lista blanca, no interpolación (KC-ADM-B3-05).

Módulo transversal de paginación, filtrado y ordenación segura para los endpoints
de la API /admin/v1. Previene inyecciones SQL (BE-F36) obligando al uso de allowlists
estrictas declaradas en cada endpoint, garantizando sobre uniforme
{items, total, page, page_size, pages} y consistencia de filtros.
"""

from __future__ import annotations

from typing import Any

import pytest
from admin_api.pagination import (
    DEFAULT_PAGE_SIZE,
    MAX_PAGE_SIZE,
    ConstructorFiltrosSQL,
    Pagina,
    ResultadoPaginado,
    calcular_paginas,
    paginacion,
    sobre,
)
from admin_workers.main import refrescar_agregados

PERMITIDOS = {"alta": "c.alta_el", "consumo": "a.loc_consumidas"}


def _pagina(order_by: str | None = None, descending: bool = False) -> Pagina:
    return Pagina(page=1, page_size=25, order_by=order_by, descending=descending)


def test_sin_orden_se_usa_el_por_defecto() -> None:
    assert _pagina().clausula_order(PERMITIDOS, "c.alta_el DESC") == "c.alta_el DESC"


@pytest.mark.parametrize(
    ("campo", "desc", "esperado"),
    [
        ("alta", False, "c.alta_el ASC"),
        ("alta", True, "c.alta_el DESC"),
        ("consumo", True, "a.loc_consumidas DESC"),
    ],
)
def test_un_campo_permitido_se_traduce_a_su_expresion(
    campo: str, desc: bool, esperado: str
) -> None:
    """El nombre público nunca llega al SQL: se traduce a la expresión declarada.

    Esta indirección es la que hace imposible la inyección, no la validación del
    texto: lo que se concatena viene siempre del diccionario del endpoint.
    """
    assert _pagina(campo, desc).clausula_order(PERMITIDOS, "x") == esperado


@pytest.mark.parametrize(
    "campo",
    [
        "razon_social",
        "1",
        "c.alta_el",
        "alta;DROP TABLE core.organizations",
        "alta,consumo",
        "alta) --",
        "ALTA",
    ],
)
def test_cualquier_campo_no_declarado_se_rechaza(campo: str) -> None:
    """Incluido el nombre real de la columna y la variante en mayúsculas.

    Aceptar `c.alta_el` porque «coincide con la expresión» sería abrir la puerta a
    cualquier expresión SQL. La comparación es contra la clave pública y exacta.
    """
    from kallicode_core.errors import AppError

    with pytest.raises(AppError):
        _pagina(campo).clausula_order(PERMITIDOS, "x")


def test_la_direccion_solo_puede_ser_asc_o_desc() -> None:
    """`descending` es booleano, así que la dirección nunca es texto de entrada."""
    for desc in (True, False):
        clausula = _pagina("alta", desc).clausula_order(PERMITIDOS, "x")
        assert clausula.endswith("DESC" if desc else "ASC")
        assert clausula.count(" ") == 1


def test_el_desplazamiento_se_calcula_desde_la_pagina_uno() -> None:
    assert Pagina(page=1, page_size=25, order_by=None, descending=False).offset == 0
    assert Pagina(page=4, page_size=25, order_by=None, descending=False).offset == 75


@pytest.mark.parametrize("sort", ["alta", "alta-", "-asc", "asc", "alta-descendente"])
def test_un_parametro_sort_mal_formado_se_rechaza(sort: str) -> None:
    """`campo-asc` o `campo-desc`; cualquier otra forma es un error explícito."""
    from kallicode_core.errors import AppError

    with pytest.raises(AppError):
        paginacion(page=1, page_size=25, sort=sort)


def test_sort_bien_formado_se_descompone() -> None:
    p = paginacion(page=2, page_size=10, sort="consumo-desc")
    assert (p.page, p.page_size, p.order_by, p.descending) == (2, 10, "consumo", True)


def test_el_tamano_de_pagina_tiene_techo() -> None:
    """El techo protege la base de una consulta que pida cien mil filas.

    En una consola que lee datos de todos los clientes, un `page_size` sin límite
    es también una exportación masiva sin registro.
    """
    assert MAX_PAGE_SIZE <= 200
    assert DEFAULT_PAGE_SIZE == 25
    p = paginacion(page=1, page_size=MAX_PAGE_SIZE, sort=None)
    assert p.page_size == MAX_PAGE_SIZE


def test_la_envoltura_del_listado_declara_el_total() -> None:
    """El total y las páginas van en la respuesta para permitir navegación consistente."""
    salida = sobre([{"a": 1}], 137, _pagina())
    assert salida == {
        "items": [{"a": 1}],
        "total": 137,
        "page": 1,
        "page_size": 25,
        "pages": 6,
    }


# ========================================================= Nuevos Tests KC-ADM-B3-05
@pytest.mark.parametrize(
    ("total", "page_size", "esperado"),
    [
        (0, 25, 0),
        (1, 25, 1),
        (25, 25, 1),
        (26, 25, 2),
        (50, 25, 2),
        (51, 25, 3),
        (100, 10, 10),
        (101, 10, 11),
        (137, 25, 6),
        (-1, 25, 0),
        (10, 0, 0),
    ],
)
def test_calculo_matematico_de_paginas(total: int, page_size: int, esperado: int) -> None:
    """Verifica la fórmula ceil(total / page_size) con casos de borde."""
    assert calcular_paginas(total, page_size) == esperado


def test_modelo_resultado_paginado() -> None:
    """Valida el esquema del modelo Pydantic genérico ResultadoPaginado."""
    res = ResultadoPaginado[dict[str, int]](
        items=[{"x": 1}], total=10, page=1, page_size=5, pages=2
    )
    assert res.total == 10
    assert res.pages == 2
    assert res.page == 1
    assert res.page_size == 5
    assert res.items == [{"x": 1}]


def test_constructor_filtros_sql_vacio() -> None:
    """Constructor sin filtros produce WHERE vacío y parámetros vacíos."""
    builder = ConstructorFiltrosSQL()
    assert builder.where == ""
    assert builder.params == {}


def test_constructor_filtros_sql_con_condiciones() -> None:
    """Constructor acumula condiciones y parámetros de manera consistente."""
    builder = ConstructorFiltrosSQL()
    builder.agregar("c.activo = :act", act=True)
    builder.agregar("c.plan = :pl", pl="growth")
    assert builder.where == "WHERE (c.activo = :act) AND (c.plan = :pl)"
    assert builder.params == {"act": True, "pl": "growth"}


def test_clausula_order_con_conjunto_permitidos() -> None:
    """Soporte de allowlist expresada como conjunto (set) de columnas."""
    permitidos_set = {"creado_en", "actualizado_en"}
    assert _pagina("creado_en", False).clausula_order(permitidos_set, "x") == "creado_en ASC"
    assert (
        _pagina("actualizado_en", True).clausula_order(permitidos_set, "x")
        == "actualizado_en DESC"
    )

    from kallicode_core.errors import AppError

    with pytest.raises(AppError) as exc_info:
        _pagina("no_permitido", False).clausula_order(permitidos_set, "x")
    assert exc_info.value.codigo == "VALIDACION_ENTRADA"


def test_rechazo_campo_invalido_devuelve_codigo_validacion_entrada() -> None:
    """Intentar ordenar por un campo no declarado devuelve VALIDACION_ENTRADA con HTTP 422."""
    from kallicode_core.errors import AppError

    with pytest.raises(AppError) as exc_info:
        _pagina("columna_inexistente", False).clausula_order(PERMITIDOS, "defecto")
    assert exc_info.value.codigo == "VALIDACION_ENTRADA"
    assert exc_info.value.http == 422


# ================================================= Pruebas HTTP de Integración
@pytest.fixture
async def _datos_frescos(db: Any, dos_clientes: list[str]) -> None:
    await refrescar_agregados(db)


@pytest.mark.integracion
@pytest.mark.asyncio
async def test_http_page_menor_a_uno_devuelve_422(
    cliente: Any, como: Any, sin_limite: None, _datos_frescos: None
) -> None:
    """page < 1 debe devolver HTTP 422 con código VALIDACION_ENTRADA."""
    como("staff_negocio")
    r0 = await cliente.get("/admin/v1/business/customers", params={"page": 0})
    assert r0.status_code == 422, r0.text
    assert r0.json()["error"]["codigo"] == "VALIDACION_ENTRADA"

    r_neg = await cliente.get("/admin/v1/business/customers", params={"page": -1})
    assert r_neg.status_code == 422, r_neg.text
    assert r_neg.json()["error"]["codigo"] == "VALIDACION_ENTRADA"


@pytest.mark.integracion
@pytest.mark.asyncio
async def test_http_page_size_fuera_de_rango_devuelve_422(
    cliente: Any, como: Any, sin_limite: None, _datos_frescos: None
) -> None:
    """page_size < 1 o page_size > 100 devuelve HTTP 422 con código VALIDACION_ENTRADA."""
    como("staff_negocio")
    r0 = await cliente.get("/admin/v1/business/customers", params={"page_size": 0})
    assert r0.status_code == 422, r0.text
    assert r0.json()["error"]["codigo"] == "VALIDACION_ENTRADA"

    r101 = await cliente.get("/admin/v1/business/customers", params={"page_size": 101})
    assert r101.status_code == 422, r101.text
    assert r101.json()["error"]["codigo"] == "VALIDACION_ENTRADA"


@pytest.mark.integracion
@pytest.mark.asyncio
async def test_http_orden_fuera_de_allowlist_devuelve_422(
    cliente: Any, como: Any, sin_limite: None, _datos_frescos: None
) -> None:
    """Intentar ordenar por columna no autorizada devuelve HTTP 422 VALIDACION_ENTRADA."""
    como("staff_negocio")
    r = await cliente.get(
        "/admin/v1/business/customers", params={"sort": "columna_inexistente-desc"}
    )
    assert r.status_code == 422, r.text
    assert r.json()["error"]["codigo"] == "VALIDACION_ENTRADA"


@pytest.mark.integracion
@pytest.mark.asyncio
async def test_http_intento_inyeccion_sql_en_sort_devuelve_422(
    cliente: Any, como: Any, sin_limite: None, _datos_frescos: None
) -> None:
    """Intentos de inyección SQL en el parámetro sort son bloqueados categóricamente."""
    como("staff_negocio")
    payloads = [
        "alta; DROP TABLE admin.staff;--desc",
        "' OR 1=1;--asc",
        "mrr_eur UNION SELECT 1,2,3-desc",
        "benchmark(5000000,MD5(1))-asc",
    ]
    for p in payloads:
        r = await cliente.get("/admin/v1/business/customers", params={"sort": p})
        assert r.status_code == 422, f"Falló en bloquear payload: {p}"
        assert r.json()["error"]["codigo"] == "VALIDACION_ENTRADA"


@pytest.mark.integracion
@pytest.mark.asyncio
async def test_http_sort_mal_formado_sin_sufijo_devuelve_422(
    cliente: Any, como: Any, sin_limite: None, _datos_frescos: None
) -> None:
    """Parámetro sort sin sufijo -asc o -desc es rechazado con 422 VALIDACION_ENTRADA."""
    como("staff_negocio")
    r = await cliente.get("/admin/v1/business/customers", params={"sort": "mrr_eur"})
    assert r.status_code == 422, r.text
    assert r.json()["error"]["codigo"] == "VALIDACION_ENTRADA"


@pytest.mark.integracion
@pytest.mark.asyncio
async def test_http_orden_valido_en_customers(
    cliente: Any, como: Any, sin_limite: None, _datos_frescos: None
) -> None:
    """Todas las columnas de ALLOWLIST_CLIENTES ordenan correctamente y devuelven pages."""
    como("staff_negocio")
    columnas_sort = [
        "tenant_id-asc",
        "plan-desc",
        "estado-asc",
        "mrr_eur-desc",
        "creado_en-desc",
        "actualizado_en-asc",
        "consumo-desc",
        "alta-asc",
        "nombre-desc",
    ]
    for s in columnas_sort:
        r = await cliente.get("/admin/v1/business/customers", params={"sort": s})
        assert r.status_code == 200, f"Error en orden: {s} - {r.text}"
        body = r.json()
        assert "items" in body
        assert "total" in body
        assert "page" in body
        assert "page_size" in body
        assert "pages" in body
        assert body["pages"] >= 1


@pytest.mark.integracion
@pytest.mark.asyncio
async def test_http_orden_valido_en_subscriptions(
    cliente: Any, como: Any, sin_limite: None, _datos_frescos: None
) -> None:
    """ALLOWLIST_SUSCRIPCIONES funciona en /admin/v1/business/subscriptions y declara pages."""
    como("staff_negocio")
    for s in ("renovacion-asc", "importe-desc", "nombre-asc"):
        r = await cliente.get("/admin/v1/business/subscriptions", params={"sort": s})
        assert r.status_code == 200, f"Error en orden: {s} - {r.text}"
        body = r.json()
        assert "pages" in body
        assert body["page"] == 1


@pytest.mark.integracion
@pytest.mark.asyncio
async def test_http_orden_valido_en_staff_actions(
    cliente: Any, como: Any, sin_limite: None
) -> None:
    """ALLOWLIST_ACCIONES_STAFF funciona en /admin/v1/audit/staff-actions."""
    como("staff_admin")
    for s in ("ocurrido-desc", "occurred_at-asc"):
        r = await cliente.get(
            "/admin/v1/audit/staff-actions", params={"sort": s, "ambito": "todas"}
        )
        assert r.status_code == 200, f"Error en orden: {s} - {r.text}"
        body = r.json()
        assert "pages" in body


@pytest.mark.integracion
@pytest.mark.asyncio
async def test_coherencia_filtros_y_recuento_en_customers(
    cliente: Any, como: Any, sin_limite: None, _datos_frescos: None
) -> None:
    """Verifica que el total refleje exactamente los mismos filtros de la consulta de items."""
    como("staff_negocio")

    # Sin filtro: total >= 2
    r_todo = await cliente.get("/admin/v1/business/customers")
    assert r_todo.status_code == 200
    total_general = r_todo.json()["total"]
    assert total_general >= 2

    # Con filtro restrictivo que devuelva 0 filas
    r_vacio = await cliente.get(
        "/admin/v1/business/customers", params={"plan": "plan_que_no_existe"}
    )
    assert r_vacio.status_code == 200
    body_vacio = r_vacio.json()
    assert body_vacio["total"] == 0
    assert body_vacio["items"] == []
    assert body_vacio["pages"] == 0
