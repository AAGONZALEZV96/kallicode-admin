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

from dataclasses import dataclass
from typing import Any, Generic, TypeVar

from fastapi import Query
from kallicode_core.errors import validacion
from pydantic import BaseModel

T = TypeVar("T")

MAX_PAGE_SIZE = 100
DEFAULT_PAGE_SIZE = 25


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

    def clausula_order(self, permitidos: dict[str, str], defecto: str) -> str:
        """Devuelve el fragmento ORDER BY a partir de la lista blanca.

        Parámetros:
            permitidos: nombre expuesto en la API -> expresión SQL segura.
            defecto: expresión SQL a usar cuando no se pide orden.

        La expresión nunca proviene de la petición: solo se elige de la lista.
        """
        if self.order_by is None:
            return defecto
        expr = permitidos.get(self.order_by)
        if expr is None:
            raise validacion(
                "El campo de orden no es válido.",
                {"campo": self.order_by, "permitidos": sorted(permitidos)},
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


class Listado(BaseModel, Generic[T]):
    """Sobre de respuesta de todo listado paginado."""

    items: list[T]
    total: int
    page: int
    page_size: int


def sobre(items: list[Any], total: int, p: Pagina) -> dict[str, Any]:
    """Construye el sobre de respuesta sin perder el total.

    Devolver el total no es opcional: es lo que impide que un listado descarte
    resultados en silencio, que es el defecto que la vista de Consumo del portal
    cliente tiene hoy.
    """
    return {"items": items, "total": total, "page": p.page, "page_size": p.page_size}
