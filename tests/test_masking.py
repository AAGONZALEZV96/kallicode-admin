"""Enmascarado y jerarquía de alcances.

El enmascarado es la segunda de las cuatro reglas que sostienen la excepción de la
consola, y la única que actúa dentro del proceso: el rol acotado decide qué
columnas llegan a la memoria de la aplicación, y el enmascarado decide qué sale de
ella. Estas pruebas son unitarias y rápidas a propósito, porque la propiedad que
comprueban es aritmética —qué campo se oculta con qué alcance— y conviene poder
ejecutarlas en cada guardado.

La afirmación central es negativa: **con cero concesiones, ningún campo
identificable sobrevive a `enmascarar`**. Se comprueba por enumeración de los tres
bloques y no por lista de casos escritos a mano, para que añadir un campo
identificable al módulo sin cubrirlo sea imposible.
"""

from __future__ import annotations

import pytest
from admin_api.masking import (
    JERARQUIA,
    PII_CODIGO,
    PII_EXPEDIENTE,
    PII_NEGOCIO,
    alcance_suficiente,
    enmascarar,
    enmascarar_filas,
    enmascarar_texto,
)

TODOS_LOS_CAMPOS = PII_NEGOCIO | PII_EXPEDIENTE | PII_CODIGO


# ================================================== jerarquía de alcances
def test_la_jerarquia_es_transitiva_hacia_abajo() -> None:
    """Un alcance mayor concede todos los menores, y ninguno concede hacia arriba.

    Se recorre el producto completo de la jerarquía en vez de escribir los seis
    casos: si mañana se añade un cuarto alcance, la prueba lo incluye sola.
    """
    for i, concedido in enumerate(JERARQUIA):
        for j, requerido in enumerate(JERARQUIA):
            esperado = i >= j
            assert alcance_suficiente([concedido], requerido) is esperado, (
                f"«{concedido}» {'debería' if esperado else 'no debería'} cubrir «{requerido}»"
            )


def test_sin_concesiones_no_se_cubre_ningun_alcance() -> None:
    for requerido in JERARQUIA:
        assert alcance_suficiente([], requerido) is False


def test_un_alcance_inventado_no_concede_nada() -> None:
    """Un valor desconocido no se interpreta con benevolencia.

    Si un alcance escrito mal en base de datos concediera acceso por descuido, la
    revelación de datos dependería de un error tipográfico.
    """
    assert alcance_suficiente(["administrador"], "datos_negocio") is False
    assert alcance_suficiente(["expedientes"], "expediente") is False  # plural
    with pytest.raises(ValueError, match="alcance desconocido"):
        alcance_suficiente(["datos_negocio"], "todo")


# ================================================== enmascarado por defecto
@pytest.mark.parametrize("campo", sorted(TODOS_LOS_CAMPOS))
def test_sin_concesion_ningun_campo_identificable_sobrevive(campo: str) -> None:
    """Enumerado sobre los tres bloques: nada identificable sale sin concesión."""
    original = "Acme Logística S.L."
    salida, bloques = enmascarar({campo: original, "tenant_id": "org_acme"}, [])
    assert salida[campo] != original, f"«{campo}» salió sin enmascarar"
    assert campo in bloques
    # El identificador técnico no es dato identificable y debe pasar intacto: sin
    # él la interfaz no puede ni ofrecer la solicitud de concesión.
    assert salida["tenant_id"] == "org_acme"


def test_el_alcance_maximo_revela_todo() -> None:
    datos = dict.fromkeys(sorted(TODOS_LOS_CAMPOS), "valor original")
    salida, bloques = enmascarar(datos, ["contenido_codigo"])
    assert bloques == []
    assert salida == datos


@pytest.mark.parametrize(
    ("alcance", "revelados", "ocultos"),
    [
        ("datos_negocio", PII_NEGOCIO, PII_EXPEDIENTE | PII_CODIGO),
        ("expediente", PII_NEGOCIO | PII_EXPEDIENTE, PII_CODIGO),
    ],
)
def test_cada_alcance_revela_su_bloque_y_no_los_superiores(
    alcance: str, revelados: frozenset[str], ocultos: frozenset[str]
) -> None:
    """Una concesión de expediente no abre el código fuente del cliente.

    Es la distinción que hace útil la jerarquía: soporte necesita ver de qué caso
    habla el cliente sin poder leer su código, que es su activo.
    """
    datos = dict.fromkeys(sorted(TODOS_LOS_CAMPOS), "valor original")
    salida, bloques = enmascarar(datos, [alcance])
    for campo in revelados:
        assert salida[campo] == "valor original", f"«{campo}» debería revelarse"
    for campo in ocultos:
        assert salida[campo] != "valor original", f"«{campo}» debería ocultarse"
    assert set(bloques) == ocultos


def test_las_listas_se_sustituyen_por_su_recuento() -> None:
    """Una lista de personas se convierte en cuántas son, no en `null`.

    El recuento no identifica a nadie y es justo el dato que soporte necesita para
    saber si el problema afecta a un usuario o a doscientos.
    """
    salida, bloques = enmascarar(
        {"usuarios": ["ana@acme.es", "luis@acme.es", "sofia@acme.es"]}, []
    )
    assert salida["usuarios"] is None
    assert salida["usuarios_total"] == 3
    assert bloques == ["usuarios"]


def test_los_valores_no_textuales_se_anulan_sin_reventar() -> None:
    """Números, fechas y anidados se anulan; el enmascarado no lanza excepciones.

    Si enmascarar pudiera fallar por el tipo de un valor, el camino de error más
    probable sería devolver la respuesta sin enmascarar.
    """
    for valor in (42, 3.5, True, {"a": 1}, None):
        salida, _ = enmascarar({"razon_social": valor}, [])
        assert salida["razon_social"] in (None, valor if valor is None else None)


def test_enmascarar_no_muta_el_diccionario_de_entrada() -> None:
    """La entrada queda intacta.

    Importa porque varios endpoints construyen la fila una vez y la usan para
    responder y para auditar: si enmascarar mutara la fila, el registro de
    auditoría guardaría el valor enmascarado y perdería la traza de qué se leyó.
    """
    original = {"razon_social": "Acme Logística S.L.", "tenant_id": "org_acme"}
    copia = dict(original)
    enmascarar(original, [])
    assert original == copia


# ============================================================== forma del texto
@pytest.mark.parametrize(
    ("entrada", "esperado"),
    [
        ("Acme Logística S.L.", "A•••• S.L."),
        ("Globex Industrial S.A.", "G•••• S.A."),
        ("Nortec", "N••••"),
        ("A", "A"),
        ("", ""),
    ],
)
def test_forma_del_texto_enmascarado(entrada: str, esperado: str) -> None:
    assert enmascarar_texto(entrada) == esperado


def test_el_texto_enmascarado_no_filtra_la_longitud_real() -> None:
    """La marca es de longitud fija: no revela cuántos caracteres tenía.

    Un enmascarado que respeta la longitud original permite adivinar el nombre en
    un listado corto de clientes conocidos.
    """
    cortos = enmascarar_texto("Nortec") or ""
    largos = enmascarar_texto("Internacional") or ""
    assert len(cortos) == len(largos)


def test_el_texto_enmascarado_no_conserva_palabras_largas() -> None:
    """Solo se conserva el sufijo societario, que es genérico y no identifica."""
    salida = enmascarar_texto("Construcciones Mediterráneas Reunidas") or ""
    assert "Mediterráneas" not in salida
    assert "Reunidas" not in salida


def test_none_se_propaga_sin_convertirse_en_texto() -> None:
    assert enmascarar_texto(None) is None


# ======================================================= listados mixtos
def test_una_concesion_no_revela_los_demas_clientes() -> None:
    """El caso que importa en un listado: concesión sobre uno de veinte.

    Es el patrón del defecto BE-F09 del backend —el filtro se aplicaba a la
    consulta pero no a la agregación— trasladado aquí: el enmascarado se resuelve
    fila a fila, nunca para la respuesta entera.
    """
    filas = [
        {"tenant_id": "org_acme", "razon_social": "Acme Logística S.L."},
        {"tenant_id": "org_globex", "razon_social": "Globex Industrial S.A."},
        {"tenant_id": "org_nortec", "razon_social": "Nortec Sistemas S.L."},
    ]
    salida, alguna = enmascarar_filas(filas, {"org_acme": ["datos_negocio"]})

    assert alguna is True
    por_tenant = {f["tenant_id"]: f for f in salida}
    assert por_tenant["org_acme"]["razon_social"] == "Acme Logística S.L."
    assert por_tenant["org_acme"]["enmascarado"] is False
    for tid in ("org_globex", "org_nortec"):
        assert por_tenant[tid]["razon_social"] != filas[1]["razon_social"]
        assert por_tenant[tid]["enmascarado"] is True


def test_una_fila_sin_tenant_se_enmascara_por_defecto() -> None:
    """Si no se puede determinar de quién es la fila, se enmascara.

    El fallo seguro va hacia ocultar. Una fila cuyo inquilino no se identifica es
    exactamente el caso en el que no se puede afirmar que haya concesión.
    """
    salida, alguna = enmascarar_filas(
        [{"razon_social": "Sin dueño S.L."}], {"org_acme": ["contenido_codigo"]}
    )
    assert alguna is True
    assert salida[0]["razon_social"] != "Sin dueño S.L."


def test_la_concesion_de_otro_cliente_no_sirve() -> None:
    """Tener concesión sobre Globex no revela nada de Acme.

    Suena obvio y es la comprobación que faltaba en el kanban del portal: allí el
    identificador venía del cuerpo de la petición y no se validaba contra el
    inquilino de la sesión.
    """
    salida, _ = enmascarar_filas(
        [{"tenant_id": "org_acme", "razon_social": "Acme Logística S.L."}],
        {"org_globex": ["contenido_codigo"]},
    )
    assert salida[0]["razon_social"] != "Acme Logística S.L."
    assert salida[0]["enmascarado"] is True


def test_listado_vacio_no_reporta_enmascarado() -> None:
    salida, alguna = enmascarar_filas([], {})
    assert salida == []
    assert alguna is False
