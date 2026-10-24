"""Paginación y orden: lista blanca, no interpolación.

Módulo pequeño y prueba corta, pero está aquí por un motivo concreto: el defecto
BE-F36 del backend fue un parámetro `sort` interpolado en el SQL. La defensa no es
escapar el valor, es no aceptar ningún valor que no esté en una lista blanca
declarada por el endpoint. Estas pruebas fijan esa propiedad para que no se pueda
relajar en una refactorización.
"""

from __future__ import annotations

import pytest
from admin_api.pagination import MAX_PAGE_SIZE, Pagina, paginacion, sobre

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
    p = paginacion(page=1, page_size=MAX_PAGE_SIZE, sort=None)
    assert p.page_size == MAX_PAGE_SIZE


def test_la_envoltura_del_listado_declara_el_total() -> None:
    """El total va aparte de los elementos: sin él no hay paginador en la interfaz."""
    salida = sobre([{"a": 1}], 137, _pagina())
    assert salida == {"items": [{"a": 1}], "total": 137, "page": 1, "page_size": 25}
