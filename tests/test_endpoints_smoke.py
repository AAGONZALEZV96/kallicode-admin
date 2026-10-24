"""Camino feliz por endpoint de pantalla, y honestidad cuando el dato no está.

Cada una de las siete pantallas de la consola tiene aquí una prueba que la recorre
con datos reales en base: no verifica los números, verifica que la pantalla puede
pintarse. Es cobertura básica a propósito —la profundidad está en autorización,
no-fuga, enmascarado y auditoría— con una excepción deliberada.

La excepción es la **honestidad del dato ausente**, que sí se prueba a fondo. Es el
patrón de defecto más caro de esta consola y no es un error de seguridad sino de
confianza: un panel de operaciones que muestra «0 agentes activos» cuando lo que
pasa es que la telemetría no responde provoca decisiones equivocadas. La regla es
que un agregado viejo o una telemetría caída producen 503 con código propio, nunca
un cero.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
import respx
from httpx import Response
from sqlalchemy import text

pytestmark = pytest.mark.integracion

BASE_TELEMETRIA = "http://localhost:8001/internal/v1"


@pytest.fixture
async def admin(cliente: Any, staff_factory: Any) -> dict[str, str]:
    """Sesión con rol de administración: la única que abre todas las pantallas."""
    from admin_api.security import emitir_tokens_staff

    empleado = await staff_factory("staff_admin")
    acceso = emitir_tokens_staff(empleado["id"], "staff_admin", datetime.now(UTC))
    return {"authorization": f"Bearer {acceso}"}


@pytest.fixture
async def agregados(db: Any, dos_clientes: list[str]) -> None:
    """Refresca los agregados y deja constancia de frescura reciente.

    Sin este paso los endpoints de negocio devuelven 503 —lo cual es correcto— y
    las pruebas de camino feliz no probarían nada.
    """
    await db.execute(text("SELECT admin.refresh_all()"))
    await db.execute(text("SELECT admin.refresh_sla(95, true)"))
    await db.commit()


@pytest.fixture
def telemetria() -> Any:
    """Doble del contrato interno `/internal/v1`, con marcas de tiempo frescas.

    Se dobla el contrato y no el cliente HTTP: así la prueba falla si el contrato
    cambia de forma, que es justo lo que se quiere detectar entre dos equipos.
    """
    ahora = datetime.now(UTC).isoformat()
    with respx.mock(base_url=BASE_TELEMETRIA, assert_all_called=False) as mock:
        mock.get("/telemetry/agents").mock(
            return_value=Response(
                200,
                json={
                    "telemetria_desde": ahora,
                    "etapas": [
                        {
                            "etapa": "gate1",
                            "activos": 3,
                            "en_cola": 7,
                            "latencia_p95_ms": 4200,
                            "errores": 0,
                        }
                    ],
                    "lineas_activas": 12,
                },
            )
        )
        mock.get("/telemetry/queues").mock(
            return_value=Response(
                200,
                json={
                    "telemetria_desde": ahora,
                    "colas": [
                        {
                            "nombre": "fabrica.gate1",
                            "profundidad": 7,
                            "antiguedad_max_s": 45,
                            "dlq": 0,
                        }
                    ],
                },
            )
        )
        mock.get("/telemetry/providers").mock(
            return_value=Response(
                200,
                json={
                    "telemetria_desde": ahora,
                    "proveedores": [
                        {
                            "proveedor": "anthropic",
                            "modelo": "flash",
                            "disponibilidad_pct": 99.8,
                            "latencia_p95_ms": 1800,
                            "error_pct": 0.2,
                            "tokens": 1_240_000,
                        },
                        {
                            "proveedor": "anthropic",
                            "modelo": "fable",
                            "disponibilidad_pct": 99.9,
                            "latencia_p95_ms": 900,
                            "error_pct": 0.1,
                            "tokens": 88_000,
                        },
                    ],
                },
            )
        )
        yield mock


# ============================================ pantalla 1 · panel de negocio
async def test_overview_responde_con_los_bloques_de_la_pantalla(
    cliente: Any, admin: dict[str, str], agregados: None
) -> None:
    r = await cliente.get("/admin/v1/business/overview", headers=admin)
    assert r.status_code == 200, r.text
    cuerpo = r.json()
    for bloque in ("clientes", "ingresos", "consumo", "frescura"):
        assert bloque in cuerpo, f"el panel no trae el bloque «{bloque}»"
    assert cuerpo["frescura"], (
        "el panel no declara la frescura de sus agregados: sin ella, quien lo mira "
        "no puede saber a qué momento corresponden los números"
    )


# ============================================ pantalla 2 · clientes
async def test_listado_de_clientes_pagina_y_ordena(
    cliente: Any, admin: dict[str, str], agregados: None
) -> None:
    r = await cliente.get(
        "/admin/v1/business/customers",
        headers=admin,
        params={"page_size": 1, "sort": "alta-desc"},
    )
    assert r.status_code == 200, r.text
    cuerpo = r.json()
    assert len(cuerpo["items"]) == 1
    assert cuerpo["total"] >= 2
    assert cuerpo["page"] == 1


async def test_un_orden_no_permitido_se_rechaza(
    cliente: Any, admin: dict[str, str], agregados: None
) -> None:
    """El campo de orden se valida contra una lista blanca.

    Es el defecto BE-F36 del backend: el parámetro de orden se interpolaba en el
    SQL. Aquí un campo desconocido es un 422, no una consulta.
    """
    r = await cliente.get(
        "/admin/v1/business/customers", headers=admin, params={"sort": "razon_social;drop-asc"}
    )
    assert r.status_code == 422, r.text


async def test_buscar_clientes_por_nombre_exige_concesion(
    cliente: Any, admin: dict[str, str], agregados: None
) -> None:
    """Buscar por razón social es una revelación, aunque no devuelva el campo.

    Confirmar que «Acme» está entre los clientes de KalliCode ya es información
    sobre Acme. Es el hueco típico de un enmascarado que solo cubre la salida y
    olvida la entrada.
    """
    r = await cliente.get("/admin/v1/business/customers", headers=admin, params={"q": "Acme"})
    assert r.status_code == 403, r.text
    assert r.json()["error"]["code"] == "acceso_no_justificado"


async def test_ficha_de_cliente_declara_sus_bloques_enmascarados(
    cliente: Any, admin: dict[str, str], agregados: None
) -> None:
    r = await cliente.get("/admin/v1/business/customers/org_acme", headers=admin)
    assert r.status_code == 200, r.text
    cuerpo = r.json()
    assert cuerpo["tenant_id"] == "org_acme"
    assert isinstance(cuerpo["enmascarado"], list)
    assert "razon_social" in cuerpo["enmascarado"], (
        "sin concesión, la razón social debe figurar como enmascarada para que la "
        "interfaz pueda ofrecer la solicitud en contexto"
    )


async def test_ficha_de_cliente_inexistente_es_404(
    cliente: Any, admin: dict[str, str], agregados: None
) -> None:
    r = await cliente.get("/admin/v1/business/customers/org_no_existe", headers=admin)
    assert r.status_code == 404


# ============================================ pantalla 3 · suscripciones
async def test_suscripciones_usa_los_estados_reales_del_esquema(
    cliente: Any, admin: dict[str, str], agregados: None
) -> None:
    """Los estados son `activa`, `periodo_gracia`, `suspendida` y `finalizada`.

    Se comprueba contra la restricción del esquema y no contra una lista escrita
    aquí: si el modelo de datos añade un estado, la consola tiene que enterarse por
    una prueba y no por una pantalla en blanco.
    """
    r = await cliente.get("/admin/v1/business/subscriptions", headers=admin)
    assert r.status_code == 200, r.text
    estados = {f["suscripcion_estado"] for f in r.json()["items"]}
    assert estados <= {"activa", "periodo_gracia", "suspendida", "finalizada"}, (
        f"estados desconocidos en la respuesta: {estados}"
    )


async def test_solicitudes_de_cambio_de_plan(
    cliente: Any, admin: dict[str, str], agregados: None
) -> None:
    r = await cliente.get("/admin/v1/business/upgrade-requests", headers=admin)
    assert r.status_code == 200, r.text
    assert "items" in r.json()


# ============================================ pantalla 4 · consumo
async def test_consumo_declara_si_cuadra_con_facturacion(
    cliente: Any, admin: dict[str, str], agregados: None
) -> None:
    """La respuesta dice explícitamente si el consumo cuadra con lo facturado.

    Un descuadre silencioso entre el consumo medido y el facturado es un problema
    de dinero, así que la consola lo expone como un campo y registra el caso como
    crítico en lugar de dejar que alguien lo descubra sumando a mano.
    """
    r = await cliente.get(
        "/admin/v1/business/usage/tokens",
        headers=admin,
        params={"ciclo": datetime.now(UTC).strftime("%Y-%m")},
    )
    assert r.status_code == 200, r.text
    cuerpo = r.json()
    assert "cuadra_con_facturacion" in cuerpo
    assert isinstance(cuerpo["cuadra_con_facturacion"], bool)


# ============================================ pantalla 5 · operaciones
async def test_agentes_con_telemetria_disponible(
    cliente: Any, admin: dict[str, str], telemetria: Any
) -> None:
    r = await cliente.get("/admin/v1/ops/agents", headers=admin)
    assert r.status_code == 200, r.text
    cuerpo = r.json()
    assert cuerpo["etapas"], "no se pintaron las etapas con telemetría disponible"


async def test_sin_telemetria_no_se_muestran_ceros(cliente: Any, admin: dict[str, str]) -> None:
    """La telemetría caída produce 503 con código propio, no un panel de ceros.

    La distinción entre «no hay trabajo» y «no sé si hay trabajo» es la razón de ser
    de este endpoint. Confundirlas es el defecto BE-F29, y es peor que un error
    visible: un cero convincente hace que nadie investigue.
    """
    with respx.mock(base_url=BASE_TELEMETRIA) as mock:
        mock.get("/telemetry/agents").mock(return_value=Response(503))
        r = await cliente.get("/admin/v1/ops/agents", headers=admin)
    assert r.status_code == 503, r.text
    assert r.json()["error"]["code"] == "telemetria_no_disponible"
    assert "0" not in str(r.json()["error"].get("detail", {}).get("etapas", ""))


async def test_telemetria_vieja_se_trata_como_no_disponible(
    cliente: Any, admin: dict[str, str]
) -> None:
    """Un dato de hace dos horas no es un dato actual.

    Sin comprobación de frescura, un recolector parado devuelve su último estado
    indefinidamente y el panel miente con datos que existieron.
    """
    viejo = (datetime.now(UTC) - timedelta(hours=2)).isoformat()
    with respx.mock(base_url=BASE_TELEMETRIA) as mock:
        mock.get("/telemetry/agents").mock(
            return_value=Response(
                200, json={"telemetria_desde": viejo, "etapas": [], "lineas_activas": 0}
            )
        )
        r = await cliente.get("/admin/v1/ops/agents", headers=admin)
    assert r.status_code == 503
    assert r.json()["error"]["code"] == "telemetria_no_disponible"


async def test_colas_derivan_su_estado_del_umbral_configurado(
    cliente: Any, admin: dict[str, str], telemetria: Any
) -> None:
    r = await cliente.get("/admin/v1/ops/queues", headers=admin)
    assert r.status_code == 200, r.text
    for cola in r.json()["colas"]:
        assert cola["estado"] in ("ok", "atencion", "critico"), cola


async def test_modelos_separa_fable_del_resto(
    cliente: Any, admin: dict[str, str], telemetria: Any
) -> None:
    """Fable se contabiliza aparte porque su coste y su uso no son comparables."""
    r = await cliente.get("/admin/v1/ops/models", headers=admin)
    assert r.status_code == 200, r.text
    modelos = {m["modelo"] for m in r.json()["modelos"]}
    assert "fable" in modelos


# ============================================ pantalla 6 · niveles de servicio
async def test_sla_no_publica_porcentajes_con_muestra_insuficiente(
    cliente: Any, admin: dict[str, str], agregados: None
) -> None:
    """Con menos de cinco casos se devuelve el recuento, no un porcentaje.

    «66 % de cumplimiento» sobre tres casos es un número que parece medir algo. El
    umbral evita que la consola produzca cifras con las que no se puede decidir.
    """
    r = await cliente.get("/admin/v1/ops/sla", headers=admin)
    assert r.status_code == 200, r.text
    for fila in r.json()["items"]:
        if fila["casos"] < 5:
            assert fila["cumplimiento_pct"] is None, (
                f"se publicó un porcentaje sobre {fila['casos']} casos: {fila}"
            )


async def test_desglose_del_reloj_de_un_caso(
    cliente: Any, db: Any, admin: dict[str, str], agregados: None
) -> None:
    """El desglose muestra qué tramos computan y por qué se pausó el reloj.

    Sin el desglose, un incumplimiento es indiscutible e injusto a la vez: la
    espera de la firma del cliente en un gate no es tiempo de KalliCode.
    """
    caso = (
        await db.execute(
            text("""
        SELECT job_id FROM admin.sla_cases LIMIT 1
    """)
        )
    ).fetchone()
    if caso is None:
        pytest.skip("no hay casos de nivel de servicio en los datos de prueba")

    r = await cliente.get(f"/admin/v1/ops/sla/cases/{caso[0]}", headers=admin)
    assert r.status_code == 200, r.text
    cuerpo = r.json()
    assert cuerpo["tramos"], "el desglose no trae tramos"
    for tramo in cuerpo["tramos"]:
        assert "computa" in tramo and "horas" in tramo, tramo
        if tramo["computa"] is False:
            assert tramo.get("causa_pausa"), "un tramo que no computa debe decir por qué"


async def test_sla_sin_objetivo_definido_lo_dice(
    cliente: Any, db: Any, admin: dict[str, str], agregados: None
) -> None:
    """Un plan sin objetivo pactado no se evalúa contra un objetivo inventado."""
    await db.execute(text("DELETE FROM admin.sla_targets WHERE plan_codigo = 'growth'"))
    await db.commit()
    r = await cliente.get("/admin/v1/ops/sla", headers=admin, params={"plan": "growth"})
    assert r.status_code in (200, 422)
    if r.status_code == 422:
        assert r.json()["error"]["code"] == "sla_sin_definicion"


# ============================================ pantalla 7 · informes
async def test_informe_se_encola_y_se_consulta(
    cliente: Any, admin: dict[str, str], agregados: None
) -> None:
    r = await cliente.post(
        "/admin/v1/business/reports",
        headers=admin,
        json={
            "tipo": "consumo",
            "desde": "2026-01-01",
            "hasta": "2026-01-31",
            "formato": "csv",
        },
    )
    assert r.status_code in (201, 202), r.text
    report_id = r.json()["report_id"]

    r = await cliente.get(f"/admin/v1/business/reports/{report_id}", headers=admin)
    assert r.status_code == 200, r.text
    assert r.json()["estado"] in ("en_cola", "generando", "listo")


async def test_un_informe_ajeno_no_se_descarga(
    cliente: Any, db: Any, admin: dict[str, str], staff_factory: Any, agregados: None
) -> None:
    """Cada empleado accede a los informes que ha pedido.

    Un informe es una copia congelada de datos de cliente; que sea accesible a
    quien no lo pidió multiplica la superficie sin que nadie lo haya justificado.
    """
    from admin_api.security import emitir_tokens_staff

    r = await cliente.post(
        "/admin/v1/business/reports",
        headers=admin,
        json={
            "tipo": "consumo",
            "desde": "2026-01-01",
            "hasta": "2026-01-31",
            "formato": "csv",
        },
    )
    report_id = r.json()["report_id"]

    otro = await staff_factory("staff_negocio")
    acceso = emitir_tokens_staff(otro["id"], "staff_negocio", datetime.now(UTC))
    r = await cliente.get(
        f"/admin/v1/business/reports/{report_id}", headers={"authorization": f"Bearer {acceso}"}
    )
    assert r.status_code in (403, 404), r.text


async def test_el_informe_se_sube_antes_de_marcarse_listo(
    db: Any, staff_factory: Any, agregados: None, monkeypatch: Any
) -> None:
    """Si la subida falla, el informe queda fallido y sin URL.

    Es el defecto BE-F19 del backend: la exportación se marcaba como lista antes de
    escribir el fichero, así que el usuario recibía un enlace a nada. El orden
    correcto —subir, luego marcar— se comprueba forzando el fallo de la subida.
    """
    from admin_workers import main as workers

    async def _falla(*_a: Any, **_k: Any) -> str:
        raise RuntimeError("almacenamiento no disponible")

    monkeypatch.setattr(workers, "subir_informe", _falla)

    from kallicode_core.ids import nuevo

    solicitante = await staff_factory("staff_negocio")
    rid = nuevo("rp")
    await db.execute(
        text("""
        INSERT INTO admin.reports (id, kind, format, params, requested_by,
                                   status, includes_pii)
        VALUES (:i, 'consumo', 'csv',
                '{"desde":"2026-01-01","hasta":"2026-01-31"}'::jsonb,
                :by, 'en_cola', false)
    """),
        {"i": rid, "by": solicitante["id"]},
    )
    await db.commit()

    await workers.generar_informes(db)

    fila = (
        await db.execute(
            text("""
        SELECT status, blob_ref FROM admin.reports WHERE id = :i
    """),
            {"i": rid},
        )
    ).fetchone()
    assert fila is not None
    assert fila[0] == "fallido", f"el informe quedó en estado «{fila[0]}»"
    assert fila[1] is None, "quedó una referencia a un fichero que no se subió"


# ============================================ salud
async def test_health_distingue_degradado_de_caido(cliente: Any, agregados: None) -> None:
    """La sonda no responde «ok» cuando una dependencia no crítica falla.

    Una sonda que siempre dice «ok» es peor que no tenerla: hace que el
    orquestador mantenga tráfico sobre un proceso que no puede servir. La consola
    distingue tres estados y solo devuelve 503 si la dependencia es crítica.
    """
    r = await cliente.get("/admin/v1/health")
    assert r.status_code in (200, 503), r.text
    cuerpo = r.json()
    assert cuerpo["estado"] in ("ok", "degradado", "no_disponible")
    assert "dependencias" in cuerpo
    if cuerpo["estado"] == "ok":
        assert all(d["ok"] for d in cuerpo["dependencias"].values()), cuerpo


async def test_health_no_expone_detalles_internos(cliente: Any) -> None:
    """Ni cadenas de conexión, ni versiones, ni nombres de excepción.

    La sonda es el único endpoint sin autenticación de toda la consola, así que es
    lo primero que mira quien la encuentra publicada por error.
    """
    r = await cliente.get("/admin/v1/health")
    texto = r.text.lower()
    for filtracion in (
        "postgresql://",
        "password",
        "asyncpg",
        "traceback",
        "kallicode_admin_ro",
        "5432",
    ):
        assert filtracion not in texto, f"la sonda expone «{filtracion}»"


# ============================================ agregados y frescura
async def test_un_agregado_viejo_produce_503_y_no_un_dato_antiguo(
    cliente: Any, db: Any, admin: dict[str, str], agregados: None
) -> None:
    """Pasado el umbral, el panel deja de servir en lugar de mentir.

    Servir un agregado de ayer sin decirlo es la forma más silenciosa de romper la
    confianza en una consola: los números son plausibles y nadie los cuestiona.
    """
    await db.execute(
        text("""
        UPDATE admin.aggregate_state
        SET refreshed_at = now() - interval '48 hours'
    """)
    )
    await db.commit()

    r = await cliente.get("/admin/v1/business/overview", headers=admin)
    assert r.status_code == 503, r.text
    assert r.json()["error"]["code"] == "agregado_no_disponible"
    detalle = r.json()["error"].get("detail", {})
    assert detalle, "el error no dice qué agregado está viejo ni de cuándo es"


async def test_un_agregado_fallido_no_se_sirve_como_actual(
    cliente: Any, db: Any, admin: dict[str, str], agregados: None
) -> None:
    """Un refresco que falló deja el agregado marcado, no aparentemente al día."""
    await db.execute(
        text("""
        UPDATE admin.aggregate_state
        SET status = 'fallido', error = 'fallo simulado'
    """)
    )
    await db.commit()

    r = await cliente.get("/admin/v1/business/overview", headers=admin)
    assert r.status_code == 503, r.text


async def test_el_refresco_de_agregados_es_idempotente(
    db: Any, dos_clientes: list[str]
) -> None:
    """Dos refrescos seguidos dejan el mismo resultado, no lo duplican."""
    await db.execute(text("SELECT admin.refresh_all()"))
    primero = (await db.execute(text("SELECT count(*) FROM admin.agg_customer_state"))).scalar()
    await db.execute(text("SELECT admin.refresh_all()"))
    segundo = (await db.execute(text("SELECT count(*) FROM admin.agg_customer_state"))).scalar()
    assert primero == segundo, f"el refresco duplicó filas: {primero} → {segundo}"


# ============================================ contrato y forma de los errores
async def test_todos_los_errores_tienen_la_misma_forma(
    cliente: Any, como: Any, sin_limite: None
) -> None:
    """`{error: {code, message, detail?}}` y trace_id en la cabecera.

    La forma uniforme es lo que permite que la interfaz reaccione al código en vez
    de al texto, y el identificador de traza es lo que hace que un empleado pueda
    reportar un problema de forma útil.
    """
    como("staff_soporte")
    r = await cliente.get("/admin/v1/business/overview")
    assert r.status_code == 403
    cuerpo = r.json()
    assert set(cuerpo) == {"error"}
    assert {"code", "message"} <= set(cuerpo["error"])
    assert r.headers.get("x-trace-id"), "la respuesta de error no trae trace_id"


async def test_una_excepcion_interna_no_filtra_su_tipo(
    cliente: Any, como: Any, monkeypatch: Any, sin_limite: None
) -> None:
    """Un fallo inesperado responde 500 genérico, sin nombre de excepción.

    El nombre de la clase y el módulo son información de arquitectura gratuita para
    quien esté probando la consola.
    """
    from admin_api.routers import business

    async def _revienta(*_a: Any, **_k: Any) -> Any:
        raise ZeroDivisionError("secreto de implementación")

    monkeypatch.setattr(business, "_frescura", _revienta)
    como("staff_admin")
    r = await cliente.get("/admin/v1/business/overview")
    assert r.status_code == 500
    assert "ZeroDivisionError" not in r.text
    assert "secreto de implementación" not in r.text


async def test_las_cabeceras_de_seguridad_estan_presentes(cliente: Any) -> None:
    r = await cliente.get("/admin/v1/health")
    for cabecera in (
        "strict-transport-security",
        "x-content-type-options",
        "x-frame-options",
        "referrer-policy",
        "content-security-policy",
        "cache-control",
    ):
        assert cabecera in r.headers, f"falta la cabecera «{cabecera}»"
    assert "no-store" in r.headers["cache-control"], (
        "las respuestas de la consola no deben quedar en caché"
    )


async def test_el_cuerpo_de_la_peticion_esta_acotado(
    cliente: Any, como: Any, sin_limite: None
) -> None:
    """Un cuerpo de más de dos megas se rechaza antes de parsearse."""
    como("staff_admin")
    r = await cliente.post(
        "/admin/v1/business/reports",
        content=b"x" * (3 * 1024 * 1024),
        headers={"content-type": "application/json"},
    )
    assert r.status_code == 413, r.status_code


async def test_el_esquema_openapi_se_publica_completo(cliente: Any) -> None:
    """Los 31 endpoints figuran en el esquema, que es el contrato con la interfaz."""
    r = await cliente.get("/admin/v1/openapi.json")
    assert r.status_code == 200, r.text
    esquema = r.json()
    operaciones = sum(
        1
        for camino in esquema["paths"].values()
        for metodo in camino
        if metodo in ("get", "post", "patch", "delete", "put")
    )
    assert operaciones == 31, f"el esquema publica {operaciones} operaciones"
    for camino in esquema["paths"]:
        assert camino.startswith("/admin/v1"), (
            f"«{camino}» está fuera del espacio de la consola"
        )
