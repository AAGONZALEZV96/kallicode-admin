"""Enmascarado por defecto de los datos identificables de cliente (ADM-G09).

Regla del capítulo 18: los datos identificables van enmascarados en toda
respuesta y su revelación exige una concesión de acceso vigente. El enmascarado
es por defecto y no opcional, así que la función que lo aplica no recibe un
«enmascarar sí o no» sino el conjunto de alcances concedidos: sin alcance, se
enmascara.

El diseño evita el error habitual, que es enmascarar en la capa de presentación:
aquí se enmascara antes de construir la respuesta, de modo que ningún campo
identificable pueda llegar al navegador ni siquiera en una respuesta que la
interfaz no pinta. La prueba de extremo a extremo por rol comprueba exactamente
eso capturando el tráfico de red.

Jerarquía de alcances: `contenido_codigo` implica `expediente`, que implica
`datos_negocio`. Una concesión de alcance mayor sirve para lo menor.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

# Orden de menor a mayor. Un alcance concede todo lo anterior.
JERARQUIA: tuple[str, ...] = ("datos_negocio", "expediente", "contenido_codigo")

# Campos identificables por bloque, tal como los declara el inventario de
# acceso de 002_read_role.sql (columna `pii`).
PII_NEGOCIO: frozenset[str] = frozenset(
    {
        "razon_social",
        "nombre",
        "dominio",
        "comentario",
        "conexion_nombre",
    }
)
PII_EXPEDIENTE: frozenset[str] = frozenset(
    {
        "ticket_numero",
        "numero",
        "usuarios",
        "integraciones",
        "titulo",
    }
)
PII_CODIGO: frozenset[str] = frozenset(
    {
        "diff",
        "contenido",
        "entrada",
        "salida",
        "fragmento",
    }
)

_MARCA = "•" * 4


def alcance_suficiente(concedidos: Iterable[str], requerido: str) -> bool:
    """¿Alguno de los alcances concedidos cubre el requerido?"""
    if requerido not in JERARQUIA:
        raise ValueError(f"alcance desconocido: {requerido}")
    minimo = JERARQUIA.index(requerido)
    return any(a in JERARQUIA and JERARQUIA.index(a) >= minimo for a in concedidos)


def enmascarar_texto(valor: str | None) -> str | None:
    """Deja la inicial y enmascara el resto: «Acme Logística S.L.» → «A•••• S.L.».

    Se conserva la inicial y el sufijo societario cuando existe, porque un
    listado de treinta clientes totalmente enmascarados es inoperante para
    soporte, y la inicial no identifica por sí sola.
    """
    if not valor:
        return valor
    partes = valor.strip().split()
    if not partes:
        return valor
    cabeza = partes[0]
    visible = f"{cabeza[0]}{_MARCA}" if len(cabeza) > 1 else cabeza
    cola = partes[-1] if len(partes) > 1 and len(partes[-1]) <= 5 else ""
    return f"{visible} {cola}".strip()


def _campos_a_enmascarar(concedidos: Iterable[str]) -> frozenset[str]:
    concedidos = list(concedidos)
    pendientes: set[str] = set()
    if not alcance_suficiente(concedidos, "datos_negocio"):
        pendientes |= PII_NEGOCIO
    if not alcance_suficiente(concedidos, "expediente"):
        pendientes |= PII_EXPEDIENTE
    if not alcance_suficiente(concedidos, "contenido_codigo"):
        pendientes |= PII_CODIGO
    return frozenset(pendientes)


def enmascarar(
    datos: dict[str, Any],
    concedidos: Iterable[str],
) -> tuple[dict[str, Any], list[str]]:
    """Enmascara los campos identificables de un diccionario de respuesta.

    Parámetros:
        datos: el diccionario a devolver, ya construido desde la consulta.
        concedidos: alcances de las concesiones vigentes del empleado sobre el
                    cliente al que pertenecen estos datos.

    Devuelve `(datos_enmascarados, bloques_enmascarados)`. La lista se expone en
    la respuesta como campo `enmascarado`, para que la interfaz pueda ofrecer la
    solicitud de concesión en contexto en lugar de mostrar un dato roto.
    """
    pendientes = _campos_a_enmascarar(concedidos)
    if not pendientes:
        return datos, []

    enmascarados: list[str] = []
    salida = dict(datos)
    for clave, valor in datos.items():
        if clave not in pendientes:
            continue
        enmascarados.append(clave)
        if isinstance(valor, str):
            salida[clave] = enmascarar_texto(valor)
        elif isinstance(valor, list):
            # listas de personas o de integraciones: se sustituye por el recuento
            salida[clave] = None
            salida[f"{clave}_total"] = len(valor)
        else:
            salida[clave] = None
    return salida, sorted(enmascarados)


def enmascarar_filas(
    filas: list[dict[str, Any]],
    concedidos_por_tenant: dict[str, list[str]],
    clave_tenant: str = "tenant_id",
) -> tuple[list[dict[str, Any]], bool]:
    """Enmascara un listado en el que cada fila pertenece a un cliente distinto.

    Es el caso de los listados de negocio (§18.17, §18.19, §18.20): el empleado
    puede tener concesión sobre un cliente y no sobre los otros veinte, así que
    el enmascarado se resuelve fila a fila y no para toda la respuesta.

    Devuelve `(filas, alguna_enmascarada)`; cada fila lleva su propio campo
    booleano `enmascarado`.
    """
    salida: list[dict[str, Any]] = []
    alguna = False
    for fila in filas:
        tenant = str(fila.get(clave_tenant, ""))
        nueva, enmascarados = enmascarar(fila, concedidos_por_tenant.get(tenant, []))
        nueva["enmascarado"] = bool(enmascarados)
        alguna = alguna or bool(enmascarados)
        salida.append(nueva)
    return salida, alguna
