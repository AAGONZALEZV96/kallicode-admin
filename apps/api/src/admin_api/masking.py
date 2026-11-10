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

from sqlalchemy.ext.asyncio import AsyncSession

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
        "email",
        "correo",
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

    Para dominios de cliente («acme.com»), enmascara el nombre: «a••••.com».
    Se conserva la inicial y el sufijo societario cuando existe, porque un
    listado de treinta clientes totalmente enmascarados es inoperante para
    soporte, y la inicial no identifica por sí sola.
    """
    if not valor:
        return valor
    limpio = valor.strip()
    if not limpio:
        return valor
    # Detección de dominio: sin espacios y con al menos un punto intermedio
    if (
        " " not in limpio
        and "." in limpio
        and not limpio.startswith(".")
        and not limpio.endswith(".")
    ):
        partes_dom = limpio.split(".", 1)
        cabeza_dom = partes_dom[0]
        visible_dom = f"{cabeza_dom[0]}{_MARCA}" if len(cabeza_dom) > 1 else cabeza_dom
        return f"{visible_dom}.{partes_dom[1]}"

    partes = limpio.split()
    cabeza = partes[0]
    visible = f"{cabeza[0]}{_MARCA}" if len(cabeza) > 1 else cabeza
    cola = partes[-1] if len(partes) > 1 and len(partes[-1]) <= 5 else ""
    return f"{visible} {cola}".strip()


def enmascarar_email(email: str | None) -> str | None:
    """Enmascara la parte local del correo: «juan@acme.com» → «j••••@acme.com»."""
    if not email:
        return email
    limpio = email.strip()
    if "@" not in limpio:
        return enmascarar_texto(limpio)
    local, dominio = limpio.split("@", 1)
    if not local:
        return f"{_MARCA}@{dominio}"
    visible = f"{local[0]}{_MARCA}" if len(local) > 1 else local
    return f"{visible}@{dominio}"


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
            if "@" in valor:
                salida[clave] = enmascarar_email(valor)
            else:
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


async def evaluar_concesion_activa(
    db: AsyncSession,
    staff_id: str,
    tenant_id: str,
    alcance: str = "datos_negocio",
) -> bool:
    """Consulta admin.access_grants para comprobar si existe concesión vigente y no revocada."""
    from .db import todos

    filas = await todos(
        db,
        """
        SELECT scope FROM admin.access_grants
        WHERE staff_id = :sid AND tenant_id = :tid
          AND revoked_at IS NULL AND expires_at > now()
    """,
        {"sid": staff_id, "tid": tenant_id},
    )
    concedidos = [r["scope"] for r in filas]
    return alcance_suficiente(concedidos, alcance)


def aplicar_politica_enmascarado(
    datos: dict[str, Any] | list[dict[str, Any]],
    tiene_concesion: bool = False,
    alcance: str = "datos_negocio",
) -> dict[str, Any] | list[dict[str, Any]]:
    """Aplica la política de enmascarado por defecto a un payload o lista de datos.

    Si tiene_concesion es True, entrega los datos en claro con "enmascarado": [].
    Si tiene_concesion es False, ofusca campos PII y declara "enmascarado": [...].
    """
    if isinstance(datos, list):
        if tiene_concesion:
            salida_lista: list[dict[str, Any]] = []
            for d in datos:
                copia_d = dict(d)
                copia_d["enmascarado"] = False
                salida_lista.append(copia_d)
            return salida_lista
        concedidos_map: dict[str, list[str]] = {}
        filas_res, _ = enmascarar_filas(datos, concedidos_map)
        return filas_res

    # Es un diccionario
    if tiene_concesion:
        res_dict = dict(datos)
        res_dict["enmascarado"] = []
        return res_dict

    res_dict, campos_enmascarados = enmascarar(datos, [])
    res_dict["enmascarado"] = campos_enmascarados
    return res_dict


__all__ = [
    "JERARQUIA",
    "PII_CODIGO",
    "PII_EXPEDIENTE",
    "PII_NEGOCIO",
    "alcance_suficiente",
    "aplicar_politica_enmascarado",
    "enmascarar",
    "enmascarar_email",
    "enmascarar_filas",
    "enmascarar_texto",
    "evaluar_concesion_activa",
]
