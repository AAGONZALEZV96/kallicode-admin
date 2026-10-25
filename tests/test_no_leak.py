"""No-fuga del rol de lectura: lo que la consola puede leer y nada más.

La consola es la excepción declarada al aislamiento por inquilino de KalliCode.
Toda la garantía de esa excepción descansa en una sola afirmación: el rol
`kallicode_admin_ro` puede leer exactamente las columnas del inventario aprobado,
y ninguna otra. Si esa afirmación se rompe, la consola deja de ser una excepción
acotada y pasa a ser un agujero, porque no hay RLS debajo que la contenga.

Por eso estas pruebas no consultan la API: interrogan a `information_schema` y a
`pg_roles` directamente. Comprueban el privilegio real que el motor concede, no lo
que el código cree estar concediendo. Es la diferencia entre la prueba que habría
detectado el defecto DB-F01 de la plataforma —políticas creadas sin `FORCE`, así
que el dueño de la tabla las ignoraba— y la que no.

Todas exigen base de datos real. Con un doble no significan nada.
"""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import text

pytestmark = pytest.mark.integracion

# Tablas cuyo contenido nunca debe ser legible por la consola, en ninguna columna.
# El código fuente del cliente y sus artefactos derivados solo se ven a través de
# una concesión de alcance `contenido_codigo`, que no se implementa con privilegio
# de tabla sino con una lectura puntual y auditada desde el rol de escritura.
PROHIBIDAS = (
    "core.code_blobs",
    "core.repository_files",
    "core.embeddings",
    "core.artifacts",
    "core.api_keys",
    "core.webhook_secrets",
    "core.users",
)


async def _filas(db: Any, sql: str, params: dict[str, Any] | None = None) -> list[Any]:
    res = await db.execute(text(sql), params or {})
    return [tuple(f) for f in res.fetchall()]


# ======================================================== atributos del rol
async def test_el_rol_de_lectura_no_puede_saltarse_rls(db: Any) -> None:
    """Ni `BYPASSRLS` ni `SUPERUSER`, ni por concesión posterior.

    Es la tentación evidente al construir una consola de administración y es la
    decisión que nunca se toma: con `BYPASSRLS` la consola vería todo, las
    políticas de la plataforma quedarían inertes para ella y el aislamiento
    dependería del código de la aplicación en lugar del motor.
    """
    for rol in ("kallicode_admin_ro", "kallicode_admin_app"):
        f = await _filas(
            db,
            """
            SELECT rolbypassrls, rolsuper, rolcreatedb, rolcreaterole, rolcanlogin
            FROM pg_roles WHERE rolname = :r
        """,
            {"r": rol},
        )
        assert f, f"el rol {rol} no existe"
        bypass, superusuario, creardb, crearrol, login = f[0]
        assert bypass is False, f"{rol} tiene BYPASSRLS"
        assert superusuario is False, f"{rol} es superusuario"
        assert creardb is False and crearrol is False, f"{rol} tiene DDL"
        assert login is True, f"{rol} no puede iniciar sesión"


async def test_el_rol_de_lectura_no_hereda_privilegios_por_pertenencia(db: Any) -> None:
    """No pertenece a ningún rol que sí pueda saltarse RLS.

    Un rol sin `BYPASSRLS` que pertenece a otro que sí lo tiene, lo tiene de
    hecho. Este camino indirecto es el que hace que revisar solo `pg_roles` no
    baste.
    """
    f = await _filas(
        db,
        """
        WITH RECURSIVE m AS (
            SELECT roleid FROM pg_auth_members
             WHERE member = 'kallicode_admin_ro'::regrole
            UNION
            SELECT a.roleid FROM pg_auth_members a JOIN m ON a.member = m.roleid)
        SELECT r.rolname FROM m JOIN pg_roles r ON r.oid = m.roleid
         WHERE r.rolbypassrls OR r.rolsuper
    """,
    )
    assert f == [], f"el rol de lectura hereda privilegios peligrosos de {f}"


async def test_la_aplicacion_no_se_conecta_como_superusuario(db: Any) -> None:
    """La sesión efectiva de la consola no es la de un superusuario.

    Comprobar el atributo del rol no basta: lo que importa es con qué usuario
    abre la conexión el pool. El defecto BE-F01 del backend fue exactamente eso —el
    DSN de producción apuntaba al superusuario y todas las políticas quedaban
    inertes— y se corrigió con un validador en la configuración; aquí se verifica
    el resultado.
    """
    f = await _filas(
        db,
        """
        SELECT current_user, session_user,
               (SELECT rolsuper FROM pg_roles WHERE rolname = current_user)
    """,
    )
    actual, sesion, es_super = f[0]
    assert es_super is False, f"la consola conecta como superusuario ({actual})"
    assert actual.startswith("kallicode_admin"), actual
    assert sesion.startswith("kallicode_admin"), sesion


# ==================================================== inventario de columnas
async def test_privilegios_reales_coinciden_con_el_inventario(db: Any) -> None:
    """El rol de lectura tiene SELECT exactamente sobre el inventario aprobado.

    En las dos direcciones. Sobra una columna: fuga silenciosa, alguien concedió
    la tabla entera. Falta una columna: pantalla rota en producción con un error
    de permisos que nadie sabe interpretar.
    """
    inventario = set(
        await _filas(
            db,
            """
        SELECT table_name, column_name FROM admin.access_inventory
    """,
        )
    )
    concedidas = set(
        await _filas(
            db,
            """
        SELECT table_schema || '.' || table_name, column_name
        FROM information_schema.column_privileges
        WHERE grantee = 'kallicode_admin_ro' AND privilege_type = 'SELECT'
    """,
        )
    )

    sobrantes = concedidas - inventario
    assert not sobrantes, (
        "el rol de lectura puede leer columnas fuera del inventario aprobado; "
        f"cada una es una fuga: {sorted(sobrantes)}"
    )

    faltantes = inventario - concedidas
    assert not faltantes, (
        "columnas del inventario sin conceder; las pantallas que las usan "
        f"fallarán con error de permisos: {sorted(faltantes)}"
    )


async def test_ninguna_tabla_esta_concedida_completa(db: Any) -> None:
    """No hay `GRANT SELECT ON tabla`: siempre columna a columna.

    Conceder la tabla entera es cómodo y es el error que se paga después, cuando
    una migración añade una columna con datos identificables y la consola empieza
    a poder leerla sin que nadie lo decida.
    """
    f = await _filas(
        db,
        """
        SELECT table_schema || '.' || table_name
        FROM information_schema.table_privileges
        WHERE grantee = 'kallicode_admin_ro' AND privilege_type = 'SELECT'
    """,
    )
    assert f == [], f"tablas concedidas completas al rol de lectura: {f}"


@pytest.mark.parametrize("tabla", PROHIBIDAS)
async def test_tablas_prohibidas_son_inaccesibles(db_ro: Any, tabla: str) -> None:
    """Leer una tabla prohibida falla con error de permisos, no devuelve vacío.

    La distinción importa: un `SELECT` que devuelve cero filas puede ser un
    aislamiento que funciona o una tabla vacía. Un error de permisos es una
    respuesta inequívoca del motor.
    """
    from sqlalchemy.exc import DBAPIError, ProgrammingError

    with pytest.raises((ProgrammingError, DBAPIError)) as exc:
        await db_ro.execute(text(f"SELECT * FROM {tabla} LIMIT 1"))
    assert "permission denied" in str(exc.value).lower(), str(exc.value)[:400]


async def test_columnas_identificables_estan_marcadas_y_justificadas(db: Any) -> None:
    """Toda columna con datos identificables lleva marca y motivo por escrito.

    El inventario es un documento de gobierno, no una lista técnica: es lo que se
    enseña cuando un cliente pregunta qué ve KalliCode de su organización.
    """
    sin_motivo = await _filas(
        db,
        """
        SELECT table_name, column_name FROM admin.access_inventory
         WHERE rationale IS NULL OR length(trim(rationale)) < 20
    """,
    )
    assert sin_motivo == [], f"columnas sin justificación suficiente: {sin_motivo}"

    sin_pantalla = await _filas(
        db,
        """
        SELECT table_name, column_name FROM admin.access_inventory
         WHERE screens IS NULL OR cardinality(screens) = 0
    """,
    )
    assert sin_pantalla == [], (
        "columnas en el inventario que ninguna pantalla usa; si nadie las "
        f"necesita, no deben estar concedidas: {sin_pantalla}"
    )

    # Las columnas identificables deben estar marcadas: el enmascarado se apoya en
    # esta marca para decidir qué oculta sin concesión.
    marcadas = await _filas(
        db,
        """
        SELECT column_name FROM admin.access_inventory
         WHERE column_name IN ('nombre', 'razon_social', 'email', 'telefono',
                               'direccion', 'nif')
           AND pii IS NOT TRUE
    """,
    )
    assert marcadas == [], f"columnas identificables sin marcar como pii: {marcadas}"


# ============================================================== solo lectura
@pytest.mark.parametrize(
    "sentencia",
    [
        "INSERT INTO core.organizations (id, nombre) VALUES ('x', 'y')",
        "UPDATE core.organizations SET nombre = 'z'",
        "DELETE FROM core.subscriptions",
        "CREATE TABLE publico_prueba (i int)",
        "ALTER TABLE core.organizations ADD COLUMN colado text",
        "GRANT SELECT ON core.code_blobs TO kallicode_admin_ro",
    ],
)
async def test_el_rol_de_lectura_no_puede_escribir_nada(db_ro: Any, sentencia: str) -> None:
    """Ni datos, ni esquema, ni privilegios.

    El último caso es el más importante: si el rol de lectura pudiera concederse
    privilegios a sí mismo, todo el inventario sería decorativo.
    """
    from sqlalchemy.exc import DBAPIError, InternalError, ProgrammingError

    with pytest.raises((ProgrammingError, InternalError, DBAPIError)):
        await db_ro.execute(text(sentencia))


async def test_la_transaccion_de_lectura_es_read_only(db_ro: Any) -> None:
    """La sesión analítica declara `READ ONLY` además de tener el rol acotado.

    Dos barreras para lo mismo, a propósito: el privilegio protege de un error de
    permisos y el modo de transacción protege de un error de configuración. La que
    falle primero, protege.
    """
    f = await _filas(db_ro, "SHOW transaction_read_only")
    assert f[0][0] == "on"


async def test_el_rol_de_escritura_no_ve_datos_de_cliente(db: Any) -> None:
    """El rol de escritura opera sobre `admin` y no lee tablas de cliente.

    La separación es la que hace que un fallo en la lógica de la consola no pueda
    convertirse en una escritura sobre datos del cliente: el rol que puede
    escribir no alcanza sus tablas, y el que las alcanza no puede escribir.
    """
    from sqlalchemy.exc import DBAPIError, ProgrammingError

    with pytest.raises((ProgrammingError, DBAPIError)) as exc:
        await db.execute(text("SELECT nombre FROM core.organizations LIMIT 1"))
    assert "permission denied" in str(exc.value).lower()


# =========================================== validación empaquetada en la base
async def test_validate_read_role_pasa_sus_seis_comprobaciones(db: Any) -> None:
    """La función de validación de la migración 002 no reporta ningún fallo.

    Duplica a propósito parte de lo que comprueba esta suite, porque también se
    ejecuta en cada despliegue: la suite protege el desarrollo y la función
    protege la producción, donde no hay pytest.
    """
    filas = await _filas(db, "SELECT * FROM admin.validate_read_role()")
    assert filas, "la función de validación no devolvió nada"
    fallos = [f for f in filas if f[-1] is not True and "ok" not in str(f).lower()]
    assert not fallos, f"comprobaciones de validate_read_role en fallo: {fallos}"
    assert len(filas) >= 6, f"se esperaban 6 comprobaciones, hay {len(filas)}"


async def test_los_agregados_no_amplian_el_alcance(db: Any) -> None:
    """Las funciones de agregación son `SECURITY DEFINER` de un tercer rol.

    Ese rol calcula los agregados y no puede iniciar sesión, así que el privilegio
    ampliado existe solo durante el cálculo. Si alguna función fuera propiedad del
    rol de lectura, ese rol tendría de hecho el alcance de la función.
    """
    f = await _filas(
        db,
        """
        SELECT p.proname, r.rolname, p.prosecdef
        FROM pg_proc p
        JOIN pg_namespace n ON n.oid = p.pronamespace
        JOIN pg_roles r ON r.oid = p.proowner
        WHERE n.nspname = 'admin' AND p.proname LIKE 'refresh%'
    """,
    )
    assert f, "no hay funciones de refresco de agregados"
    for nombre, dueno, secdef in f:
        assert secdef is True, f"{nombre} no es SECURITY DEFINER"
        assert dueno == "kallicode_admin_agg", (
            f"{nombre} pertenece a {dueno}; debe pertenecer al rol de agregación"
        )

    login = await _filas(
        db,
        """
        SELECT rolcanlogin FROM pg_roles WHERE rolname = 'kallicode_admin_agg'
    """,
    )
    assert login[0][0] is False, "el rol de agregación puede iniciar sesión"

    # Y el rol de lectura no puede ejecutarlas: no le corresponde recalcular.
    ejecutables = await _filas(
        db,
        """
        SELECT p.proname FROM pg_proc p
        JOIN pg_namespace n ON n.oid = p.pronamespace
        WHERE n.nspname = 'admin' AND p.proname LIKE 'refresh%'
          AND has_function_privilege('kallicode_admin_ro', p.oid, 'EXECUTE')
    """,
    )
    assert ejecutables == [], f"el rol de lectura puede ejecutar refrescos: {ejecutables}"
