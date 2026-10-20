"""Cadena de auditoría del personal: sellado, inmutabilidad y detección.

El registro de acciones del personal es el único documento que la consola puede
enseñar cuando un cliente pregunta quién vio sus datos. Su valor depende
enteramente de que nadie pueda alterarlo después, incluidos nosotros. De ahí las
tres propiedades:

  1. **Append-only** — actualizar o borrar una fila lo impide un disparador, no una
     convención de código.
  2. **Encadenado** — cada fila sella la anterior, así que suprimir una fila
     intermedia rompe el enlace de la siguiente.
  3. **Verificable por tramos** — la verificación comprueba el sello **y** que el
     `prev_seal` coincide con el sello real de la fila anterior.

La tercera es la lección de un defecto propio: la primera versión de la función
recalculaba el sello de cada fila usando su propio `prev_seal` almacenado, así que
un atacante que borrara una fila y reescribiera el `prev_seal` de la siguiente
pasaba la verificación. Comprobar el sello de una fila contra sí misma no verifica
nada; hay una prueba dedicada a ese caso exacto.
"""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import text

pytestmark = pytest.mark.integracion


async def _registrar(db: Any, staff_id: str, n: int = 3,
                     tenant: str = "org_acme") -> list[int]:
    """Registra n acciones de lectura y devuelve sus identificadores."""
    from admin_api.audit import registrar_accion

    for i in range(n):
        await registrar_accion(
            db, staff_id=staff_id, staff_role="staff_soporte", action="read",
            endpoint="GET /admin/v1/business/customers/org_acme",
            tenant_id=tenant, scope="expediente",
            reason=f"Caso SUP-100{i} en revisión con el cliente",
            resource=f"customer:{tenant}")
    filas = await db.execute(text("""
        SELECT id FROM admin.staff_actions WHERE staff_id = :s ORDER BY id
    """), {"s": staff_id})
    return [f[0] for f in filas.fetchall()]


# ============================================================ sellado correcto
async def test_cada_accion_se_sella_con_la_anterior(
        db: Any, staff_factory: Any) -> None:
    """El `prev_seal` de cada fila es el `seal` de la fila anterior."""
    empleado = await staff_factory("staff_soporte")
    await _registrar(db, empleado["id"], n=5)

    filas = await db.execute(text("""
        SELECT id, prev_seal, seal FROM admin.staff_actions ORDER BY id
    """))
    anterior = None
    for _id, prev, seal in filas.fetchall():
        assert seal, "fila sin sello"
        assert len(seal) == 64, f"el sello no parece un sha256: {seal!r}"
        if anterior is not None:
            assert prev == anterior, "el eslabón no apunta al sello anterior"
        anterior = seal


async def test_la_cadena_intacta_no_reporta_roturas(
        db: Any, staff_factory: Any) -> None:
    empleado = await staff_factory("staff_soporte")
    await _registrar(db, empleado["id"], n=4)
    await db.commit()

    roturas = await db.execute(text("""
        SELECT * FROM admin.verify_staff_action_chain(NULL, NULL)
    """))
    assert roturas.fetchall() == []


async def test_verificar_cadena_desde_la_api_confirma_la_integridad(
        db: Any, staff_factory: Any) -> None:
    empleado = await staff_factory("staff_soporte")
    await _registrar(db, empleado["id"], n=3)
    await db.commit()

    from admin_api.audit import verificar_cadena

    roturas = await verificar_cadena(db, None, None)
    assert roturas == [], f"la cadena íntegra reportó roturas: {roturas}"


# ================================================================ append-only
async def test_no_se_puede_modificar_una_accion_registrada(
        db: Any, staff_factory: Any) -> None:
    """Cambiar el motivo de una lectura ya registrada es imposible.

    Reescribir el motivo a posteriori es precisamente el fraude que el registro
    debe hacer imposible: convertiría un acceso injustificado en uno justificado.
    """
    from sqlalchemy.exc import DBAPIError, InternalError

    empleado = await staff_factory("staff_soporte")
    ids = await _registrar(db, empleado["id"], n=1)
    await db.commit()

    with pytest.raises((InternalError, DBAPIError)) as exc:
        await db.execute(text("""
            UPDATE admin.staff_actions SET reason = 'motivo reescrito' WHERE id = :i
        """), {"i": ids[0]})
    assert "append" in str(exc.value).lower() or "inmutable" in str(exc.value).lower()
    await db.rollback()


async def test_no_se_puede_borrar_una_accion_registrada(
        db: Any, staff_factory: Any) -> None:
    from sqlalchemy.exc import DBAPIError, InternalError

    empleado = await staff_factory("staff_soporte")
    ids = await _registrar(db, empleado["id"], n=1)
    await db.commit()

    with pytest.raises((InternalError, DBAPIError)):
        await db.execute(text("DELETE FROM admin.staff_actions WHERE id = :i"),
                         {"i": ids[0]})
    await db.rollback()


async def test_el_rol_de_lectura_no_puede_escribir_en_el_registro(
        db_ro: Any) -> None:
    """Quien lee datos de cliente no puede escribir su propio rastro.

    Si el mismo rol que consulta pudiera insertar en el registro, podría fabricar
    entradas. La separación app/ro no es solo defensa contra fugas: también
    protege la integridad del rastro.
    """
    from sqlalchemy.exc import DBAPIError, InternalError, ProgrammingError

    with pytest.raises((ProgrammingError, InternalError, DBAPIError)):
        await db_ro.execute(text("""
            INSERT INTO admin.staff_actions (staff_id, staff_role, action,
                                             endpoint)
            VALUES ('st_x', 'staff_admin', 'read', 'falso')
        """))


# =========================================== detección de manipulación real
async def test_se_detecta_la_supresion_de_un_tramo_intermedio(
        db: Any, staff_factory: Any) -> None:
    """Borrar una fila del medio rompe la cadena y la verificación lo dice.

    Se desactiva el disparador para simular lo que haría alguien con privilegios
    de esquema —el escenario que el registro tiene que hacer *detectable*, no
    imposible: contra un superusuario no hay disparador que valga, así que la
    defensa es que la manipulación deje marca.
    """
    empleado = await staff_factory("staff_soporte")
    ids = await _registrar(db, empleado["id"], n=5)
    await db.commit()

    await db.execute(text("ALTER TABLE admin.staff_actions DISABLE TRIGGER USER"))
    await db.execute(text("DELETE FROM admin.staff_actions WHERE id = :i"),
                     {"i": ids[2]})
    await db.execute(text("ALTER TABLE admin.staff_actions ENABLE TRIGGER USER"))
    await db.commit()

    roturas = (await db.execute(text("""
        SELECT broken_id, motivo FROM admin.verify_staff_action_chain(NULL, NULL)
    """))).fetchall()
    assert roturas, "se borró una fila intermedia y la verificación no lo detectó"
    assert ids[3] in [r[0] for r in roturas], (
        f"la rotura debía señalar la fila {ids[3]}, siguiente a la borrada: "
        f"{roturas}")


async def test_se_detecta_la_reescritura_con_prev_seal_ajustado(
        db: Any, staff_factory: Any) -> None:
    """El ataque que la primera versión de la función no detectaba.

    Alguien con privilegios borra una fila y arregla el `prev_seal` de la siguiente
    para que apunte a la que ahora la precede. Si la verificación solo recalculase
    el sello de cada fila a partir de su propio `prev_seal` almacenado, la cadena
    parecería intacta. La función compara además `prev_seal` con el sello **real**
    de la fila anterior, que es lo que hace que este caso se vea.
    """
    empleado = await staff_factory("staff_soporte")
    ids = await _registrar(db, empleado["id"], n=5)
    await db.commit()

    sellos = dict((await db.execute(text("""
        SELECT id, seal FROM admin.staff_actions ORDER BY id
    """))).fetchall())

    await db.execute(text("ALTER TABLE admin.staff_actions DISABLE TRIGGER USER"))
    await db.execute(text("DELETE FROM admin.staff_actions WHERE id = :i"),
                     {"i": ids[2]})
    # Se recompone el eslabón para que apunte a la fila que ahora la precede.
    await db.execute(text("""
        UPDATE admin.staff_actions SET prev_seal = :p WHERE id = :i
    """), {"p": sellos[ids[1]], "i": ids[3]})
    await db.execute(text("ALTER TABLE admin.staff_actions ENABLE TRIGGER USER"))
    await db.commit()

    roturas = (await db.execute(text("""
        SELECT broken_id, motivo FROM admin.verify_staff_action_chain(NULL, NULL)
    """))).fetchall()
    assert roturas, (
        "se reescribió el eslabón tras borrar una fila y la cadena pareció "
        "intacta: la verificación está comprobando el sello contra sí mismo")


async def test_la_verificacion_por_tramos_no_denuncia_su_propio_corte(
        db: Any, staff_factory: Any) -> None:
    """Verificar de martes a jueves no reporta rotura en la primera fila del martes.

    Es el defecto BE-F32 del backend: la verificación acotada trataba el `prev_seal`
    de la primera fila del rango como una rotura, porque no encontraba a su
    predecesora dentro del rango. El resultado era una alerta crítica cada vez que
    alguien consultaba un rango, lo que en la práctica significa dejar de mirar las
    alertas.
    """
    empleado = await staff_factory("staff_soporte")
    await _registrar(db, empleado["id"], n=6)
    await db.commit()

    fechas = (await db.execute(text("""
        SELECT min(occurred_at), max(occurred_at) FROM admin.staff_actions
    """))).fetchone()
    assert fechas is not None

    roturas = (await db.execute(text("""
        SELECT * FROM admin.verify_staff_action_chain(:d, :h)
    """), {"d": fechas[0], "h": fechas[1]})).fetchall()
    assert roturas == [], (
        "la verificación acotada denunció su propio límite como rotura")

    from admin_api.audit import verificar_cadena

    roturas_api = await verificar_cadena(db, fechas[0].isoformat(),
                                         fechas[1].isoformat())
    assert roturas_api == [], roturas_api


# ================================================= contenido del registro
async def test_una_lectura_sin_cliente_no_se_puede_registrar(
        db: Any, staff_factory: Any) -> None:
    """Registrar una lectura sin decir de qué cliente es un error de programación.

    Un registro de lectura sin inquilino no aparece en el portal de nadie, así que
    la cuarta regla —el cliente lo ve— quedaría incumplida en silencio. El módulo
    lanza en lugar de escribir una fila inútil.
    """
    from admin_api.audit import registrar_accion

    empleado = await staff_factory("staff_soporte")
    with pytest.raises(ValueError, match="tenant"):
        await registrar_accion(
            db, staff_id=empleado["id"], staff_role="staff_soporte",
            action="read", endpoint="GET /algo", tenant_id=None)


async def test_el_registro_guarda_quien_desde_donde_y_por_que(
        db: Any, staff_factory: Any) -> None:
    """Las cinco preguntas que el registro tiene que responder."""
    from admin_api.audit import registrar_accion

    empleado = await staff_factory("staff_negocio")
    await registrar_accion(
        db, staff_id=empleado["id"], staff_role="staff_negocio", action="reveal",
        endpoint="GET /admin/v1/business/customers/org_acme",
        tenant_id="org_acme", scope="expediente",
        reason="El cliente solicita revisión de su consumo, caso SUP-8812",
        resource="customer:org_acme", ip="10.20.30.40",
        user_agent="Mozilla/5.0 (consola)", request_id="tr_abc123")

    fila = (await db.execute(text("""
        SELECT staff_id, staff_role, action, tenant_id, scope, reason, resource,
               endpoint, ip, user_agent, request_id, occurred_at
        FROM admin.staff_actions ORDER BY id DESC LIMIT 1
    """))).fetchone()
    assert fila is not None
    for i, campo in enumerate(("staff_id", "staff_role", "action", "tenant_id",
                               "scope", "reason", "resource", "endpoint", "ip",
                               "user_agent", "request_id", "occurred_at")):
        assert fila[i] is not None, f"el registro no guarda «{campo}»"


async def test_el_registro_no_guarda_el_dato_leido(
        db: Any, staff_factory: Any) -> None:
    """El rastro dice qué se consultó, no qué decía.

    Copiar el contenido revelado al registro de auditoría duplicaría el dato
    sensible en una tabla que además es inmutable y de retención larga: el borrado
    a petición del cliente dejaría de ser posible.
    """
    from admin_api.audit import registrar_accion

    empleado = await staff_factory("staff_soporte")
    await registrar_accion(
        db, staff_id=empleado["id"], staff_role="staff_soporte", action="reveal",
        endpoint="GET /admin/v1/business/customers/org_acme",
        tenant_id="org_acme", scope="expediente",
        reason="Caso SUP-9001 abierto por el cliente esta mañana",
        resource="customer:org_acme",
        payload={"campos": ["razon_social", "usuarios"]})

    fila = (await db.execute(text("""
        SELECT payload::text FROM admin.staff_actions ORDER BY id DESC LIMIT 1
    """))).fetchone()
    assert fila is not None
    texto = fila[0] or ""
    assert "Acme" not in texto, (
        "el registro contiene el valor revelado, no solo el campo consultado")
    assert "razon_social" in texto, "el registro no dice qué campos se revelaron"


# ============================================================== particiones
async def test_hay_particiones_creadas_por_delante(db: Any) -> None:
    """Las particiones mensuales existen antes de necesitarse.

    El defecto DB-F09 de la plataforma fue particionar una tabla cuando ya tenía
    volumen y sin particiones futuras: la primera inserción del mes siguiente
    fallaba. Aquí se crean doce por delante y la prueba comprueba que quedan al
    menos tres desde hoy.
    """
    from datetime import UTC, datetime

    hoy = datetime.now(UTC)
    filas = (await db.execute(text("""
        SELECT c.relname FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'admin' AND c.relname LIKE 'staff_actions_%'
        ORDER BY c.relname
    """))).fetchall()
    nombres = [f[0] for f in filas]
    assert len(nombres) >= 12, f"solo hay {len(nombres)} particiones: {nombres}"

    futuras = [n for n in nombres if n[-7:] >= hoy.strftime("%Y_%m")]
    assert len(futuras) >= 3, (
        f"quedan {len(futuras)} particiones por delante; hay que crear más antes "
        f"de que se agoten: {nombres}")
