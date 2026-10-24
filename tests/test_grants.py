"""Ciclo de vida de las concesiones de acceso justificadas y temporales.

La concesión es la tercera regla de la excepción: la consola no ve datos
identificables de un cliente porque su rol lo permita, sino porque alguien ha
escrito por qué necesita verlos, durante cuánto tiempo, y ha aceptado que el
cliente lo vea en su portal.

Lo que estas pruebas defienden es que ese mecanismo no se pueda vaciar de
contenido. Un sistema de justificaciones donde vale escribir «revisión» y la
concesión dura hasta que alguien la cierre a mano es papeleo, no control. De ahí
que la mayoría de los casos sean negativos: motivos genéricos rechazados, techo de
duración para el código fuente, límite de concesiones simultáneas, y caducidad que
ocurre sola.

Todas exigen base de datos real: el vencimiento, la unicidad y el techo de
duración están en restricciones del esquema, no en el código Python.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy import text

pytestmark = pytest.mark.integracion

MOTIVO_BUENO = "El cliente reporta que el gate 2 no avanza desde el martes en el caso SUP-4471"


async def _crear(cliente: Any, cabeceras: dict[str, str], **campos: Any) -> Any:
    cuerpo = {
        "tenant_id": "org_acme",
        "alcance": "expediente",
        "motivo": MOTIVO_BUENO,
        "referencia": "SUP-4471",
    }
    cuerpo.update(campos)
    return await cliente.post("/admin/v1/access-grants", json=cuerpo, headers=cabeceras)


@pytest.fixture
async def sesion(staff_factory: Any) -> Any:
    """Empleado de soporte con sesión y segundo factor vigente."""
    from admin_api.security import emitir_tokens_staff

    empleado = await staff_factory("staff_soporte")
    acceso = emitir_tokens_staff(empleado["id"], "staff_soporte", datetime.now(UTC))
    return {"empleado": empleado, "cabeceras": {"authorization": f"Bearer {acceso}"}}


# ============================================================ camino completo
async def test_ciclo_completo_conceder_leer_revocar(
    cliente: Any, db: Any, dos_clientes: list[str], sesion: Any
) -> None:
    """Conceder, leer con la concesión, revocar, y volver a estar enmascarado.

    Es el recorrido que hace soporte veinte veces al día y la prueba comprueba las
    cuatro transiciones, no solo la primera. La que más importa es la última: tras
    revocar, el dato vuelve a estar oculto sin necesidad de cerrar la sesión.
    """
    cab = sesion["cabeceras"]

    # 1. Sin concesión, la ficha llega enmascarada.
    r = await cliente.get("/admin/v1/business/customers/org_acme", headers=cab)
    assert r.status_code == 200, r.text
    assert r.json()["razon_social"] != "Acme Logística S.L."
    assert "razon_social" in r.json()["enmascarado"]

    # 2. Se concede.
    r = await _crear(cliente, cab)
    assert r.status_code == 201, r.text
    concesion = r.json()
    assert concesion["alcance"] == "expediente"
    assert concesion["visible_para_cliente_en"] is not None, (
        "la concesión debe declarar cuándo la ve el cliente: si el cliente no lo "
        "ve, no es una excepción acordada sino un acceso oculto"
    )

    # 3. Ahora el dato se revela.
    r = await cliente.get("/admin/v1/business/customers/org_acme", headers=cab)
    assert r.status_code == 200, r.text
    assert r.json()["razon_social"] == "Acme Logística S.L."
    assert r.json()["enmascarado"] == []

    # 4. Cada lectura queda registrada y cuenta contra la concesión.
    lecturas = await db.execute(
        text("""
        SELECT reads FROM admin.access_grants WHERE id = :g
    """),
        {"g": concesion["grant_id"]},
    )
    assert (lecturas.scalar() or 0) >= 1, "la lectura no incrementó el contador de la concesión"

    # 5. Se revoca y el dato vuelve a ocultarse de inmediato.
    r = await cliente.request(
        "DELETE",
        f"/admin/v1/access-grants/{concesion['grant_id']}",
        json={"motivo": "Incidencia SUP-4471 resuelta"},
        headers=cab,
    )
    assert r.status_code == 200, r.text

    r = await cliente.get("/admin/v1/business/customers/org_acme", headers=cab)
    assert r.json()["razon_social"] != "Acme Logística S.L."


async def test_la_concesion_de_un_cliente_no_alcanza_a_otro(
    cliente: Any, dos_clientes: list[str], sesion: Any
) -> None:
    """Con concesión sobre Acme, Globex sigue enmascarado.

    El alcance de la concesión es por inquilino y no por empleado. Sin esta
    propiedad, una única justificación abriría toda la cartera de clientes.
    """
    cab = sesion["cabeceras"]
    assert (await _crear(cliente, cab)).status_code == 201

    r = await cliente.get("/admin/v1/business/customers/org_globex", headers=cab)
    assert r.status_code == 200, r.text
    assert r.json()["razon_social"] != "Globex Industrial S.A."

    # Y en el listado, cada fila lleva su propio estado.
    r = await cliente.get("/admin/v1/business/customers", headers=cab)
    filas = {f["tenant_id"]: f for f in r.json()["items"]}
    assert filas["org_acme"]["enmascarado"] is False
    assert filas["org_globex"]["enmascarado"] is True


# ======================================================= calidad del motivo
@pytest.mark.parametrize(
    "motivo",
    [
        "revisión",
        "prueba",
        "soporte",
        "comprobación",
        "análisis",
        "consulta",
        "verificación",
        "mirar",
        "debug",
        "depuración",
        "Revisión.",
        "TEST",
    ],
)
async def test_motivos_genericos_se_rechazan(
    cliente: Any, dos_clientes: list[str], sesion: Any, motivo: str
) -> None:
    """Una palabra suelta no es una justificación.

    Estos son literalmente los motivos que aparecen en los registros de acceso de
    cualquier consola interna que no los valida. Rechazarlos en el momento de
    escribirlos es la única forma de que el registro de auditoría sirva de algo
    seis meses después.
    """
    # El campo exige 20 caracteres, así que se rellena para llegar al validador.
    r = await _crear(cliente, sesion["cabeceras"], motivo=motivo.ljust(20, "."))
    assert r.status_code == 422, r.text
    assert r.json()["error"]["code"] == "motivo_insuficiente", r.text


async def test_motivo_con_pocas_palabras_distintas_se_rechaza(
    cliente: Any, dos_clientes: list[str], sesion: Any
) -> None:
    """Repetir una palabra hasta llegar al mínimo de caracteres no cuenta."""
    r = await _crear(
        cliente, sesion["cabeceras"], motivo="urgente urgente urgente urgente urgente urgente"
    )
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "motivo_insuficiente"


async def test_el_contenido_de_codigo_exige_referencia_verificable(
    cliente: Any, dos_clientes: list[str], sesion: Any
) -> None:
    """Leer el código de un cliente exige apuntar a un caso comprobable.

    El código fuente es el activo del cliente y el acceso más sensible de la
    plataforma. Un motivo en prosa, por bien escrito que esté, no permite después
    comprobar si el acceso estaba justificado; un número de caso sí.
    """
    cab = sesion["cabeceras"]
    r = await _crear(
        cliente,
        cab,
        alcance="contenido_codigo",
        motivo="Necesito revisar el fichero que falla al compilar",
        referencia=None,
    )
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "motivo_insuficiente"

    # Con la referencia en el motivo, se acepta.
    r = await _crear(
        cliente,
        cab,
        alcance="contenido_codigo",
        motivo="El caso SUP-4471 requiere revisar el fichero que "
        "falla al compilar en la línea de pedidos",
        referencia=None,
    )
    assert r.status_code == 201, r.text


async def test_alcance_desconocido_se_rechaza(
    cliente: Any, dos_clientes: list[str], sesion: Any
) -> None:
    r = await _crear(cliente, sesion["cabeceras"], alcance="todo")
    assert r.status_code == 422
    assert "permitidos" in r.text


# ============================================================== temporalidad
async def test_el_contenido_de_codigo_tiene_techo_de_una_hora(
    cliente: Any, db: Any, dos_clientes: list[str], sesion: Any
) -> None:
    """Pedir ocho horas de acceso al código concede como máximo sesenta minutos.

    El techo no se negocia con el solicitante: se recorta en silencio y se
    devuelve el vencimiento real, de modo que la interfaz muestre la verdad. Está
    además en una restricción del esquema, así que ni una inserción directa lo
    puede saltar.
    """
    r = await _crear(
        cliente,
        sesion["cabeceras"],
        alcance="contenido_codigo",
        motivo="El caso SUP-4471 exige leer el módulo de facturación",
        referencia="SUP-4471",
        duracion_min=480,
    )
    assert r.status_code == 201, r.text

    minutos = await db.execute(
        text("""
        SELECT extract(epoch FROM (expires_at - granted_at)) / 60
        FROM admin.access_grants WHERE id = :g
    """),
        {"g": r.json()["grant_id"]},
    )
    assert round(minutos.scalar() or 0) <= 60


async def test_el_esquema_rechaza_una_concesion_de_codigo_larga(
    db: Any, dos_clientes: list[str], staff_factory: Any
) -> None:
    """El techo está en la base, no solo en el endpoint.

    Es la diferencia entre una regla de negocio y una garantía. Un script de
    mantenimiento, una migración o un endpoint futuro no pueden crear una
    concesión de código de ocho horas ni por descuido.
    """
    from sqlalchemy.exc import IntegrityError

    empleado = await staff_factory("staff_soporte")
    with pytest.raises(IntegrityError):
        await db.execute(
            text("""
            INSERT INTO admin.access_grants
                (id, staff_id, tenant_id, scope, reason, reference,
                 granted_at, expires_at)
            VALUES ('gr_ilegal', :s, 'org_acme', 'contenido_codigo', :m,
                    'SUP-1', now(), now() + interval '8 hours')
        """),
            {"s": empleado["id"], "m": MOTIVO_BUENO},
        )
    await db.rollback()


async def test_una_concesion_vencida_no_revela_nada(
    cliente: Any, db: Any, dos_clientes: list[str], sesion: Any
) -> None:
    """El vencimiento actúa solo, sin que nadie ejecute nada.

    El worker que cierra concesiones vencidas registra la caducidad en la
    auditoría, pero la concesión deja de valer por su propia fecha: si el efecto
    dependiera del worker, una réplica caída ampliaría accesos.
    """
    cab = sesion["cabeceras"]
    r = await _crear(cliente, cab)
    grant_id = r.json()["grant_id"]

    await db.execute(
        text("""
        UPDATE admin.access_grants SET expires_at = now() - interval '1 minute'
        WHERE id = :g
    """),
        {"g": grant_id},
    )
    await db.commit()

    r = await cliente.get("/admin/v1/business/customers/org_acme", headers=cab)
    assert r.status_code == 200, r.text
    assert r.json()["razon_social"] != "Acme Logística S.L.", (
        "una concesión vencida siguió revelando datos"
    )


async def test_el_worker_registra_la_caducidad_una_sola_vez(
    db: Any, dos_clientes: list[str], staff_factory: Any
) -> None:
    """`caducar_concesiones` es idempotente: dos pasadas, un solo registro.

    Los tres trabajos de la consola corren en varias réplicas con elección de
    líder, pero la idempotencia se prueba aparte del liderazgo: un bloqueo que
    falla no debe poder duplicar registros de auditoría.
    """
    from admin_workers.main import caducar_concesiones

    empleado = await staff_factory("staff_soporte")
    await db.execute(
        text("""
        INSERT INTO admin.access_grants
            (id, staff_id, tenant_id, scope, reason, granted_at, expires_at)
        VALUES ('gr_vencida', :s, 'org_acme', 'expediente', :m,
                now() - interval '2 hours', now() - interval '1 hour')
    """),
        {"s": empleado["id"], "m": MOTIVO_BUENO},
    )
    await db.commit()

    await caducar_concesiones(db)
    await caducar_concesiones(db)

    n = await db.execute(
        text("""
        SELECT count(*) FROM admin.staff_actions
        WHERE grant_id = 'gr_vencida' AND action = 'grant_revoked'
    """)
    )
    assert n.scalar() == 1, "la caducidad se registró más de una vez"


# ================================================== duplicados y concurrencia
async def test_no_se_pueden_duplicar_concesiones_del_mismo_alcance(
    cliente: Any, dos_clientes: list[str], sesion: Any
) -> None:
    """Pedir dos veces lo mismo devuelve el conflicto con el identificador vigente.

    Devolver el identificador y no un error opaco es deliberado: quien lo pide
    normalmente ya tiene el acceso y solo necesita saberlo.
    """
    cab = sesion["cabeceras"]
    assert (await _crear(cliente, cab)).status_code == 201
    r = await _crear(cliente, cab)
    assert r.status_code == 409, r.text
    assert r.json()["error"]["code"] == "concesion_duplicada"
    assert "gr_" in r.text


async def test_el_esquema_impide_dos_concesiones_activas_iguales(
    db: Any, dos_clientes: list[str], staff_factory: Any
) -> None:
    """El índice parcial único garantiza lo que el endpoint comprueba.

    Sin él, dos peticiones simultáneas pasarían las dos la comprobación de
    duplicado y crearían dos concesiones: la clásica carrera entre el `SELECT` y
    el `INSERT`.
    """
    from sqlalchemy.exc import IntegrityError

    empleado = await staff_factory("staff_soporte")
    for i in (1, 2):
        sql = text("""
            INSERT INTO admin.access_grants
                (id, staff_id, tenant_id, scope, reason, granted_at, expires_at)
            VALUES (:id, :s, 'org_acme', 'expediente', :m, now(),
                    now() + interval '30 minutes')
        """)
        params = {"id": f"gr_carrera_{i}", "s": empleado["id"], "m": MOTIVO_BUENO}
        if i == 1:
            await db.execute(sql, params)
        else:
            with pytest.raises(IntegrityError):
                await db.execute(sql, params)
    await db.rollback()


async def test_hay_techo_de_concesiones_simultaneas(cliente: Any, db: Any, sesion: Any) -> None:
    """Un empleado no puede tener abiertas más de tres a la vez.

    El techo convierte el acceso en algo puntual. Sin él, acumular concesiones
    sobre veinte clientes a lo largo de una mañana equivale a un rol permanente
    con acceso a todo, construido en pequeños pasos justificados.
    """
    from sqlalchemy import text as t

    cab = sesion["cabeceras"]
    for i in range(4):
        tid = f"org_lote_{i}"
        await db.execute(
            t("""
            INSERT INTO core.organizations (id, nombre, idioma, timezone,
                                            despliegue, fabrica_activa)
            VALUES (:i, :n, 'es', 'Europe/Madrid', 'cloud', true)
            ON CONFLICT (id) DO NOTHING
        """),
            {"i": tid, "n": f"Cliente Lote {i} S.L."},
        )
    await db.commit()

    codigos = []
    for i in range(4):
        r = await _crear(cliente, cab, tenant_id=f"org_lote_{i}")
        codigos.append(r.status_code)
    assert codigos[:3] == [201, 201, 201], codigos
    assert codigos[3] == 429, f"la cuarta concesión simultánea debió rechazarse: {codigos}"


# ==================================================================== revocar
async def test_revocar_es_idempotente(
    cliente: Any, dos_clientes: list[str], sesion: Any
) -> None:
    """Revocar dos veces no falla ni cambia la fecha de revocación.

    Cerrar la propia concesión al terminar es la práctica que se quiere fomentar,
    y una práctica que a veces devuelve error es una práctica que se abandona.
    """
    cab = sesion["cabeceras"]
    grant_id = (await _crear(cliente, cab)).json()["grant_id"]
    ruta = f"/admin/v1/access-grants/{grant_id}"

    primera = await cliente.request("DELETE", ruta, headers=cab)
    segunda = await cliente.request("DELETE", ruta, headers=cab)
    assert primera.status_code == 200, primera.text
    assert segunda.status_code == 200, segunda.text
    assert primera.json()["revocada_en"] == segunda.json()["revocada_en"]


async def test_no_se_revoca_la_concesion_de_otro_empleado(
    cliente: Any, db: Any, dos_clientes: list[str], sesion: Any, staff_factory: Any
) -> None:
    """Solo el titular —o administración— cierra una concesión."""
    otro = await staff_factory("staff_soporte")
    await db.execute(
        text("""
        INSERT INTO admin.access_grants
            (id, staff_id, tenant_id, scope, reason, granted_at, expires_at)
        VALUES ('gr_ajena', :s, 'org_acme', 'expediente', :m, now(),
                now() + interval '30 minutes')
    """),
        {"s": otro["id"], "m": MOTIVO_BUENO},
    )
    await db.commit()

    r = await cliente.request(
        "DELETE", "/admin/v1/access-grants/gr_ajena", headers=sesion["cabeceras"]
    )
    assert r.status_code in (403, 404), r.text


async def test_desactivar_a_un_empleado_cierra_sus_concesiones(
    cliente: Any, db: Any, dos_clientes: list[str], sesion: Any, staff_factory: Any
) -> None:
    """Al desactivar, se revocan sesiones **y** concesiones.

    Revocar solo las sesiones deja concesiones vigentes a nombre de alguien que ya
    no trabaja aquí. No conceden acceso por sí solas, pero el registro queda sucio
    y una reactivación futura las resucitaría.
    """
    from admin_api.security import emitir_tokens_staff

    cab = sesion["cabeceras"]
    grant_id = (await _crear(cliente, cab)).json()["grant_id"]

    admin = await staff_factory("staff_admin")
    acceso = emitir_tokens_staff(admin["id"], "staff_admin", datetime.now(UTC))
    r = await cliente.patch(
        f"/admin/v1/staff/{sesion['empleado']['id']}",
        json={"estado": "disabled", "motivo": "Fin de contrato el 31 de julio"},
        headers={"authorization": f"Bearer {acceso}"},
    )
    assert r.status_code == 200, r.text

    fila = await db.execute(
        text("""
        SELECT revoked_at FROM admin.access_grants WHERE id = :g
    """),
        {"g": grant_id},
    )
    assert fila.scalar() is not None, "la concesión siguió vigente tras desactivar al empleado"


# ================================================================ visibilidad
async def test_la_concesion_es_visible_para_el_cliente(
    cliente: Any, db: Any, dos_clientes: list[str], sesion: Any
) -> None:
    """El acceso queda sellado en la cadena de auditoría del propio cliente.

    Es la cuarta regla y la que hace que la excepción sea aceptable: el cliente ve
    en su portal quién de KalliCode accedió a sus datos, cuándo y por qué. Una
    consola que ve todo sin dejar rastro visible para el afectado no es una
    excepción acordada.
    """
    cab = sesion["cabeceras"]
    grant_id = (await _crear(cliente, cab)).json()["grant_id"]

    fila = await db.execute(
        text("""
        SELECT tenant_id, action, reason, scope, seal
        FROM admin.staff_actions WHERE grant_id = :g AND action = 'grant_created'
    """),
        {"g": grant_id},
    )
    registro = fila.fetchone()
    assert registro is not None, "la concesión no se registró"
    assert registro[0] == "org_acme", (
        "el registro no está asociado al cliente afectado, así que su portal no lo mostrará"
    )
    assert registro[2] == MOTIVO_BUENO, "el motivo no se guardó literal"
    assert registro[4], "el registro no lleva sello"
