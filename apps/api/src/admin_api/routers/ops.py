"""§18.24 – §18.28 · Consola de operaciones.

Las tres pantallas de guardia. Su criterio de aceptación no es que muestren datos
correctos sino que permitan diagnosticar un incidente sin abrir otra herramienta.

Dos reglas de diseño que atraviesan el bloque y que importan más que el código:

  · Se distingue «sin trabajo» de «sin telemetría». Una cola vacía y un agente que
    no reporta no se muestran igual, porque en la pantalla de guardia son
    situaciones opuestas y confundirlas es el error clásico de este tipo de panel.
  · Los umbrales de atención se leen de la configuración de plataforma, no se
    codifican aquí: consola, alertas e informes deben usar el mismo criterio.

Y una del bloque de niveles de servicio: el reloj no cuenta el tiempo en que la
pelota está en el tejado del cliente. Contar la espera de una firma de gate como
incumplimiento del proveedor produciría incumplimientos ficticios el primer mes.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Path, Query
from kallicode_core.errors import no_encontrado, validacion
from kallicode_core.logging import log

from .. import telemetry
from ..db import read_session, todos, uno
from ..deps import OPS, OPS_NEGOCIO, Staff, exigir, limite_vivo
from ..errors import agregado_no_disponible, sla_sin_definicion
from ..masking import enmascarar_filas
from ..pagination import Pagina, paginacion, sobre
from ..settings import get_admin_settings

router = APIRouter(prefix="/admin/v1/ops", tags=["Consola de operaciones"])

_VENTANAS_AGENTES = ("5m", "1h", "24h")
_VENTANAS_MODELOS = ("1h", "24h", "7d", "30d")
_ETAPAS = ("triage", "design", "build", "qa", "security", "deploy")


def _concesiones(st: Staff, tenants: list[str]) -> dict[str, list[str]]:
    return {t: st.concedidos(t) for t in tenants}


# ------------------------------------------------------------------ §18.24
@router.get("/agents", summary="Agentes y líneas de producción")
async def agents(
    st: Annotated[Staff, Depends(exigir(*OPS))],
    _lim: Annotated[Staff, Depends(limite_vivo)],
    ventana: Annotated[str, Query(description="5m | 1h | 24h.")] = "1h",
    etapa: Annotated[str | None, Query()] = None,
) -> dict[str, Any]:
    """Estado de los agentes, rendimiento por etapa y ocupación de las líneas.

    Consume el agregado de §17.14. Si la telemetría no está disponible, los
    contadores se devuelven nulos y el campo `telemetria` lo declara: no se
    devuelven ceros, que serían indistinguibles de «no hay trabajo».
    """
    if ventana not in _VENTANAS_AGENTES:
        raise validacion(
            "Ventana no válida.", {"ventana": ventana, "permitidas": list(_VENTANAS_AGENTES)}
        )
    if etapa is not None and etapa not in _ETAPAS:
        raise validacion("Etapa no válida.", {"etapa": etapa, "permitidas": list(_ETAPAS)})

    datos = await telemetry.agentes(ventana, etapa)
    sin_telemetria = bool(datos.get("_sin_telemetria"))

    # Las líneas salen del esquema, no de la telemetría: existen aunque ningún
    # agente esté reportando, y su estado es un dato de negocio.
    async with read_session() as db:
        lineas = await uno(
            db,
            """
            SELECT count(*) FILTER (WHERE estado = 'ocupada')       AS activas,
                   count(*) FILTER (WHERE estado = 'mantenimiento') AS mantenimiento,
                   count(*) FILTER (WHERE estado = 'libre')         AS libres
            FROM core.production_lines
        """,
        )

    etapas = datos.get("etapas") or []
    alertas = [
        {"tipo": "agentes_caidos", "etapa": e.get("etapa"), "valor": e.get("agentes_caidos")}
        for e in etapas
        if (e.get("agentes_caidos") or 0) > 0
    ]
    if lineas and (lineas["mantenimiento"] or 0) > 0:
        alertas.append({"tipo": "lineas_en_mantenimiento", "valor": lineas["mantenimiento"]})

    return {
        "ventana": datos.get("ventana", ventana),
        "telemetria": {
            "disponible": not sin_telemetria,
            "antiguedad_s": datos.get("_antiguedad_s"),
            "desde": datos.get("telemetria_desde"),
        },
        # Sin telemetría no se inventan ceros: el consumidor debe mostrar
        # «sin telemetría» y no «sin trabajo».
        "etapas": None if sin_telemetria else etapas,
        "lineas": dict(lineas) if lineas else None,
        "alertas": alertas,
    }


# ------------------------------------------------------------------ §18.25
@router.get("/queues", summary="Colas del pipeline")
async def queues(
    st: Annotated[Staff, Depends(exigir(*OPS))],
    _lim: Annotated[Staff, Depends(limite_vivo)],
    incluir_dlq: Annotated[bool, Query()] = True,
) -> dict[str, Any]:
    """Profundidad, antigüedad y cola de fallidos de cada cola del pipeline.

    Complementa §18.24: una etapa sin agentes caídos y con la cola creciendo indica
    un problema distinto que una etapa con agentes caídos. El endpoint no consume
    mensajes ni altera ninguna cola: reprocesar o purgar es una operación de
    plataforma y no de la consola en esta versión.
    """
    datos = await telemetry.colas(incluir_dlq)
    colas = datos.get("colas") or []

    for c in colas:
        umbral = c.get("umbral_atencion_s") or 0
        antiguedad = c.get("antiguedad_max_s") or 0
        fallidos = c.get("fallidos") or 0
        # El estado se deriva del umbral configurado, no de un criterio propio.
        if fallidos > 0 or (umbral and antiguedad > umbral * 2):
            c["estado"] = "critico"
        elif umbral and antiguedad > umbral:
            c["estado"] = "atencion"
        else:
            c["estado"] = "normal"

    criticas = [c["nombre"] for c in colas if c["estado"] == "critico"]
    if criticas:
        log.warning("admin.ops.cola_critica", colas=criticas)

    return {
        "colas": colas,
        "resumen": {
            "criticas": len(criticas),
            "atencion": sum(1 for c in colas if c["estado"] == "atencion"),
            "pendientes_total": sum(c.get("pendientes") or 0 for c in colas),
            "fallidos_total": sum(c.get("fallidos") or 0 for c in colas),
        },
    }


# ------------------------------------------------------------------ §18.26
@router.get("/models", summary="Modelos y proveedores")
async def models(
    st: Annotated[Staff, Depends(exigir(*OPS_NEGOCIO))],
    _lim: Annotated[Staff, Depends(limite_vivo)],
    ventana: Annotated[str, Query(description="1h | 24h | 7d | 30d.")] = "24h",
    proveedor: Annotated[str | None, Query()] = None,
    comparar: Annotated[bool, Query()] = False,
) -> dict[str, Any]:
    """Disponibilidad, latencia, tasa de error y escalados por proveedor y modelo.

    Responde la pregunta operativa —si un proveedor está degradado— y la económica,
    porque un escalado por encima de lo previsto encarece cada ticket. El tier fable
    se reporta por separado: su coste no es comparable con el de pro y agregarlos
    invalidaría el cálculo.
    """
    if ventana not in _VENTANAS_MODELOS:
        raise validacion(
            "Ventana no válida.", {"ventana": ventana, "permitidas": list(_VENTANAS_MODELOS)}
        )

    datos = await telemetry.proveedores(ventana, proveedor)
    degradados = [
        p
        for p in (datos.get("proveedores") or [])
        if (p.get("disponibilidad_pct") or 100) < 99.0
    ]
    if degradados and ventana == "1h":
        log.warning(
            "admin.ops.proveedor_degradado",
            proveedores=[p.get("proveedor") for p in degradados],
        )

    # El coste se toma de los agregados propios, que aplican la tarifa vigente:
    # la telemetría del pipeline no conoce precios.
    dias = {"1h": 1, "24h": 1, "7d": 7, "30d": 30}[ventana]
    async with read_session() as db:
        estado = await uno(
            db, "SELECT status FROM admin.aggregate_state WHERE agregado = 'tokens_daily'"
        )
        if estado is None or estado["status"] == "fallido":
            raise agregado_no_disponible("tokens_daily")
        coste = await todos(
            db,
            """
            SELECT d.tier, sum(d.tokens_in + d.tokens_out) AS tokens,
                   sum(d.coste) AS coste
            FROM admin.agg_tokens_daily d
            WHERE d.dia > current_date - CAST(:dias AS int)
            GROUP BY d.tier
        """,
            {"dias": dias},
        )

    salida: dict[str, Any] = {
        "ventana": datos.get("ventana", ventana),
        "proveedores": datos.get("proveedores") or [],
        "escalados": datos.get("escalados") or {},
        "tokens_por_tier": {c["tier"]: int(c["tokens"] or 0) for c in coste},
        "coste_por_tier": {c["tier"]: float(c["coste"] or 0) for c in coste},
        "degradados": [p.get("proveedor") for p in degradados] or None,
    }
    if comparar:
        anterior = {"1h": "1h", "24h": "24h", "7d": "7d", "30d": "30d"}[ventana]
        previa = await telemetry.proveedores(anterior, proveedor)
        salida["comparacion"] = {"escalados": previa.get("escalados") or {}}
    else:
        salida["comparacion"] = None
    return salida


# ------------------------------------------------------------------ §18.27
@router.get("/sla", summary="Cumplimiento de niveles de servicio")
async def sla(
    st: Annotated[Staff, Depends(exigir(*OPS_NEGOCIO))],
    p: Annotated[Pagina, Depends(paginacion)],
    ciclo: Annotated[str | None, Query(description="AAAA-MM; defecto, en curso.")] = None,
    tenant_id: Annotated[str | None, Query()] = None,
    solo_incumplidos: Annotated[bool, Query()] = False,
) -> dict[str, Any]:
    """Cumplimiento por cliente, con su tendencia y los casos incumplidos.

    Un cliente con menos casos que el mínimo configurado no recibe porcentaje de
    cumplimiento: publicar una cifra sin significado estadístico es peor que no
    publicarla. Y si un plan no tiene objetivos configurados, se declara en
    `sin_definicion` en lugar de calcular sobre un supuesto.
    """
    s = get_admin_settings()
    if ciclo is not None and len(ciclo) != 7:
        raise validacion("El ciclo debe tener el formato AAAA-MM.", {"ciclo": ciclo})

    params: dict[str, Any] = {
        "ciclo": ciclo,
        "t": tenant_id,
        "min": s.sla_min_cases,
        "solo": solo_incumplidos,
        "lim": p.page_size,
        "off": p.offset,
    }
    where = """
        WHERE to_char(c.iniciado_en, 'YYYY-MM')
                  = coalesce(CAST(:ciclo AS text), to_char(current_date, 'YYYY-MM'))
          AND (CAST(:t AS text) IS NULL OR c.tenant_id = :t)
    """

    async with read_session() as db:
        estado = await uno(
            db,
            "SELECT status, refreshed_at "
            "FROM admin.aggregate_state "
            "WHERE agregado = 'sla_cases'",
        )
        if estado is None or estado["status"] == "fallido":
            raise agregado_no_disponible("sla_cases")

        resumen = await uno(
            db,
            f"""
            SELECT count(*) AS evaluados,
                   count(*) FILTER (WHERE c.resultado = 'incumplido') AS incumplidos,
                   count(*) FILTER (WHERE c.resultado = 'en_riesgo')  AS en_riesgo,
                   count(*) FILTER (WHERE c.resultado = 'sin_objetivo') AS sin_objetivo,
                   round(100.0 * count(*) FILTER (WHERE c.resultado = 'dentro')
                         / nullif(count(*) FILTER (
                             WHERE c.resultado IN ('dentro', 'incumplido')), 0), 2)
                       AS cumplimiento_pct
            FROM admin.sla_cases c {where}
        """,
            params,
        )

        total = await uno(
            db,
            f"""
            SELECT count(DISTINCT c.tenant_id) AS n FROM admin.sla_cases c {where}
              AND (NOT :solo OR c.resultado = 'incumplido')
        """,
            params,
        )

        filas = await todos(
            db,
            f"""
            SELECT c.tenant_id, c.plan_codigo AS plan,
                   max(c.objetivo_h) AS objetivo_h,
                   count(*) AS evaluados,
                   count(*) FILTER (WHERE c.resultado = 'incumplido') AS incumplidos,
                   count(*) FILTER (WHERE c.resultado = 'en_riesgo')  AS en_riesgo,
                   CASE WHEN count(*) FILTER (
                             WHERE c.resultado IN ('dentro', 'incumplido'))
                             >= :min
                        THEN round(100.0 * count(*) FILTER (WHERE c.resultado = 'dentro')
                             / count(*) FILTER (
                                 WHERE c.resultado IN ('dentro', 'incumplido')), 2)
                   END AS cumplimiento_pct,
                   (SELECT s.razon_social FROM admin.agg_customer_state s
                     WHERE s.tenant_id = c.tenant_id) AS razon_social
            FROM admin.sla_cases c {where}
              AND (NOT :solo OR c.resultado = 'incumplido')
            GROUP BY c.tenant_id, c.plan_codigo
            ORDER BY count(*) FILTER (WHERE c.resultado = 'incumplido') DESC,
                     c.tenant_id
            LIMIT :lim OFFSET :off
        """,
            params,
        )

        sin_def = await todos(
            db,
            """
            SELECT DISTINCT p.codigo AS plan FROM core.plans p
            WHERE NOT EXISTS (SELECT 1 FROM admin.sla_targets t
                               WHERE t.plan_codigo = p.codigo AND t.etapa = '*')
        """,
        )

    if not filas and sin_def and tenant_id is None and not solo_incumplidos:
        # Ningún plan tiene objetivos: no hay nada que calcular y se declara.
        if len(sin_def) >= 1 and (resumen or {}).get("evaluados", 0) == 0:
            raise sla_sin_definicion(", ".join(f["plan"] for f in sin_def))

    filas, _ = enmascarar_filas(filas, _concesiones(st, [f["tenant_id"] for f in filas]))

    salida = sobre(filas, int(total["n"]) if total else 0, p)
    salida["ciclo"] = ciclo or "en_curso"
    salida["frescura"] = estado["refreshed_at"]
    salida["resumen"] = dict(resumen) if resumen else {}
    salida["sin_definicion"] = [f["plan"] for f in sin_def] or []
    return salida


# ------------------------------------------------------------------ §18.28
@router.get("/sla/cases/{job_id}", summary="Desglose del reloj de un caso")
async def sla_case(
    st: Annotated[Staff, Depends(exigir(*OPS_NEGOCIO))],
    job_id: Annotated[str, Path(description="Caso cuyo reloj se desglosa.")],
) -> dict[str, Any]:
    """Desglose completo del reloj: tramos que computan, pausas y su causa.

    Es el requisito menos obvio de la pantalla de niveles de servicio y el más
    importante: quien vea un incumplimiento tiene que poder explicar por qué el
    reloj contó lo que contó, porque será la primera pregunta que haga el cliente.

    El desglose no revela el contenido del ticket ni de su código: solo etapas,
    tiempos y causas de pausa.
    """
    async with read_session() as db:
        c = await uno(
            db,
            """
            SELECT c.job_id, c.tenant_id, c.ticket_numero, c.plan_codigo,
                   c.objetivo_h, c.transcurrido_h, c.bruto_h, c.resultado,
                   c.tramos, c.reglas, c.iniciado_en, c.terminado_en,
                   c.calculado_en,
                   (SELECT s.razon_social FROM admin.agg_customer_state s
                     WHERE s.tenant_id = c.tenant_id) AS razon_social
            FROM admin.sla_cases c WHERE c.job_id = :j
        """,
            {"j": job_id},
        )
        if c is None:
            raise no_encontrado("El caso")

    if c["objetivo_h"] is None:
        raise sla_sin_definicion(c["plan_codigo"])

    salida: dict[str, Any] = {
        "job_id": c["job_id"],
        "tenant_id": c["tenant_id"],
        "razon_social": c["razon_social"],
        "ticket_numero": c["ticket_numero"],
        "plan": c["plan_codigo"],
        "objetivo_h": float(c["objetivo_h"]),
        "transcurrido_h": float(c["transcurrido_h"]),
        "bruto_h": float(c["bruto_h"]),
        "resultado": c["resultado"],
        "tramos": c["tramos"],
        "reglas_aplicadas": list(c["reglas"] or []),
        "iniciado_en": c["iniciado_en"],
        "terminado_en": c["terminado_en"],
        "calculado_en": c["calculado_en"],
    }
    salida, enmascarados = _enmascarar_caso(salida, st)
    salida["enmascarado"] = enmascarados
    return salida


def _enmascarar_caso(caso: dict[str, Any], st: Staff) -> tuple[dict[str, Any], list[str]]:
    """El número de ticket y la razón social identifican al cliente."""
    from ..masking import enmascarar

    return enmascarar(caso, st.concedidos(str(caso["tenant_id"])))


__all__ = ["router"]
