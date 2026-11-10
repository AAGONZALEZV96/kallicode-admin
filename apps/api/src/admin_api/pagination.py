"""Paginación, filtrado y orden transversales (§18.5, convención §3.4).

Se resuelve una sola vez y se aplica a todos los listados. El portal cliente
arrastra el defecto de que cada vista lo resuelve a su manera: una pagina, otra
descarta en silencio lo que no cabe y una tercera calcula el fin de página con un
literal. Aquí el contrato es único y la respuesta declara siempre el total, de
modo que la interfaz pueda ofrecer navegación cuando hay más páginas.

El orden se acepta como `sort=campo-asc|campo-desc` sobre una lista blanca por
endpoint. La lista blanca es obligatoria: el patrón de interpolar el nombre de
columna en el SQL es lo que el hallazgo BE-F36 señaló como frágil, y aquí no se
repite.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Generic, TypeVar

from fastapi import Query
from kallicode_core.errors import validacion
from pydantic import BaseModel

T = TypeVar("T")

MAX_PAGE_SIZE = 100
DEFAULT_PAGE_SIZE = 25


def calcular_paginas(total: int, page_size: int) -> int:
    """Calcula el total de páginas ceil(total / page_size)."""
    if total <= 0 or page_size <= 0:
        return 0
    return math.ceil(total / page_size)


@dataclass(slots=True)
class Pagina:
    """Parámetros de paginación y orden ya validados."""

    page: int
    page_size: int
    order_by: str | None = None
    descending: bool = True

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size

    def clausula_order(
        self, permitidos: dict[str, str] | set[str] | list[str], defecto: str
    ) -> str:
        """Devuelve el fragmento ORDER BY a partir de la lista blanca.

        Parámetros:
            permitidos: nombre expuesto en la API -> expresión SQL segura,
                        o conjunto/lista de nombres de campo permitidos.
            defecto: expresión SQL a usar cuando no se pide orden.

        La expresión nunca proviene directamente de la petición: solo se elige
        o traduce desde la lista blanca para prevenir inyecciones SQL (BE-F36).
        """
        if self.order_by is None:
            return defecto

        if isinstance(permitidos, dict):
            expr = permitidos.get(self.order_by)
        elif self.order_by in permitidos:
            expr = self.order_by
        else:
            expr = None

        if expr is None:
            nombres = sorted(permitidos.keys() if isinstance(permitidos, dict) else permitidos)
            raise validacion(
                "El campo de orden no es válido.",
                {"campo": self.order_by, "permitidos": nombres},
            )
        return f"{expr} {'DESC' if self.descending else 'ASC'}"


def paginacion(
    page: int = Query(1, ge=1, description="Página, empezando en 1."),
    page_size: int = Query(
        DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE, description="Tamaño de página, 1–100."
    ),
    sort: str | None = Query(None, description="Orden: campo-asc o campo-desc."),
) -> Pagina:
    """Dependencia de paginación común a todos los listados del capítulo 18."""
    campo: str | None = None
    desc = True
    if sort:
        if sort.endswith("-asc"):
            campo, desc = sort[:-4], False
        elif sort.endswith("-desc"):
            campo, desc = sort[:-5], True
        else:
            raise validacion(
                "El parámetro de orden debe terminar en -asc o -desc.", {"sort": sort}
            )
        if not campo:
            raise validacion("Falta el campo de orden.", {"sort": sort})
    return Pagina(page=page, page_size=page_size, order_by=campo, descending=desc)


class ResultadoPaginado(BaseModel, Generic[T]):
    """Sobre genérico de respuesta para todo listado paginado."""

    items: list[T]
    total: int
    page: int
    page_size: int
    pages: int


Listado = ResultadoPaginado


def sobre(items: list[Any], total: int, p: Pagina) -> dict[str, Any]:
    """Construye el sobre de respuesta sin perder el total ni el recuento de páginas.

    Devolver el total y el número total de páginas es obligatorio para evitar
    descartes silenciosos y permitir una navegación consistente.
    """
    pages = calcular_paginas(total, p.page_size)
    return {
        "items": items,
        "total": total,
        "page": p.page,
        "page_size": p.page_size,
        "pages": pages,
    }


class ConstructorFiltrosSQL:
    """Construye cláusulas WHERE y parámetros vinculados garantizando que la
    consulta principal y la consulta de recuento (total) comparten exactamente
    los mismos predicados y enlaces, evitando discrepancias de paginación.
    """

    def __init__(self) -> None:
        self._condiciones: list[str] = []
        self._parametros: dict[str, Any] = {}

    def agregar(self, condicion_sql: str, **parametros: Any) -> None:
        """Añade una condición con sus parámetros asociados."""
        self._condiciones.append(condicion_sql)
        self._parametros.update(parametros)

    @property
    def where(self) -> str:
        """Genera la cláusula WHERE o cadena vacía si no hay condiciones."""
        if not self._condiciones:
            return ""
        return "WHERE " + " AND ".join(f"({c})" for c in self._condiciones)

    @property
    def params(self) -> dict[str, Any]:
        """Devuelve una copia de los parámetros acumulados."""
        return dict(self._parametros)


__all__ = [
    "DEFAULT_PAGE_SIZE",
    "MAX_PAGE_SIZE",
    "ConstructorFiltrosSQL",
    "Listado",
    "Pagina",
    "ResultadoPaginado",
    "calcular_paginas",
    "paginacion",
    "sobre",
]
