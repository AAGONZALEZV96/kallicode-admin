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

import json
import re
from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Path, Query
from kallicode_core.errors import validacion
from kallicode_core.logging import log

from .. import telemetry
from ..audit import registrar_lectura
from ..db import admin_session, read_session, todos, uno
from ..deps import OPS, OPS_NEGOCIO, Staff, exigir, limite_vivo
from ..errors import agregado_no_disponible, job_no_encontrado, sla_sin_definicion
from ..masking import enmascarar_filas, enmascarar_texto
from ..pagination import Pagina, paginacion, sobre
from ..schemas.ops import (
    AlertaOpsOut,
    ColaPipelineOut,
    ColasResumenOut,
    ComparacionModelosOut,
    EscaladosLlmOut,
    EtapaAgentesOut,
    LineasProduccionOut,
    OpsAgentsResponse,
    OpsModelsResponse,
    OpsQueuesResponse,
    ProveedorModeloOut,
    SlaCaseDetailResponse,
    SlaCaseRiskItemOut,
    SlaClockSegmentOut,
    SlaPlanBreakdownOut,
    SlaResumenOut,
    SlaSummaryResponse,
    SlaTenantRowOut,
    TelemetriaEstadoOut,
)
from ..settings import get_admin_settings

router = APIRouter(prefix="/admin/v1/ops", tags=["Consola de operaciones"])

_VENTANAS_AGENTES = ("5m", "1h", "24h")
_VENTANAS_MODELOS = ("1h", "24h", "7d", "30d")
_ETAPAS = ("triage", "design", "build", "qa", "security", "deploy")
_PROVEEDORES_MODELOS = ("anthropic", "google", "deepseek", "openai")
_TIERS_MODELOS = ("flash", "pro", "fable")
_COMPARACIONES_MODELOS = ("periodo_anterior",)
# Tarifas oficiales ratificadas en docs/decisiones-negocio.md §2.3 (EUR por 1.000 tokens)
_TARIFAS_OFICIALES_1K: dict[str, tuple[float, float]] = {
    "flash": (0.000150, 0.000600),
    "pro": (0.001200, 0.004800),
    "fable": (0.012000, 0.060000),
}
_PLANES_CANONICOS = ("starter", "growth", "enterprise")
_CICLO_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
_UMBRAL_RIESGO_RATIO = 0.75


def _concesiones(st: Staff, tenants: list[str]) -> dict[str, list[str]]:
    return {t: st.concedidos(t) for t in tenants}


def _opt_int(raw: dict[str, Any], clave: str) -> int | None:
    val = raw.get(clave)
    return int(val) if val is not None else None


def _opt_float(raw: dict[str, Any], clave: str) -> float | None:
    val = raw.get(clave)
    return float(val) if val is not None else None


def _normalizar_etapas(
    raw_etapas: list[dict[str, Any]], etapa_filtro: str | None
) -> list[EtapaAgentesOut]:
    salida: list[EtapaAgentesOut] = []
    for raw in raw_etapas:
        nombre = str(raw.get("etapa") or "")
        if etapa_filtro is not None and nombre != etapa_filtro:
            continue
        agentes_total = raw.get("agentes_total")
        if agentes_total is None and raw.get("activos") is not None:
            agentes_total = raw.get("activos")
        salida.append(
            EtapaAgentesOut(
                etapa=nombre,
                agentes_total=int(agentes_total) if agentes_total is not None else None,
                agentes_ocupados=_opt_int(raw, "agentes_ocupados"),
                agentes_caidos=_opt_int(raw, "agentes_caidos"),
                jobs_completados=_opt_int(raw, "jobs_completados"),
                duracion_p95_s=_opt_float(raw, "duracion_p95_s"),
                activos=_opt_int(raw, "activos"),
                en_cola=_opt_int(raw, "en_cola"),
                latencia_p95_ms=_opt_float(raw, "latencia_p95_ms"),
                errores=_opt_int(raw, "errores"),
            )
        )
    return salida


def _construir_alertas_agentes(
    etapas: list[EtapaAgentesOut], lineas: LineasProduccionOut | None
) -> list[AlertaOpsOut]:
    alertas: list[AlertaOpsOut] = []
    for e in etapas:
        caidos = e.agentes_caidos or 0
        if caidos > 0:
            alertas.append(
                AlertaOpsOut(
                    tipo="agentes_caidos",
                    etapa=e.etapa,
                    valor=caidos,
                    umbral=0,
                    mensaje=f"{caidos} agente(s) sin latido en etapa {e.etapa}.",
                )
            )
    if lineas and lineas.mantenimiento > 0:
        alertas.append(
            AlertaOpsOut(
                tipo="lineas_en_mantenimiento",
                valor=lineas.mantenimiento,
                umbral=0,
                mensaje=f"{lineas.mantenimiento} línea(s) en mantenimiento.",
            )
        )
    return alertas


def _normalizar_colas(
    raw_colas: list[dict[str, Any]], incluir_dlq: bool
) -> list[ColaPipelineOut]:
    colas_out: list[ColaPipelineOut] = []
    for c in raw_colas:
        nombre = str(c.get("nombre") or "")
        es_dlq = nombre == "kc:dlq" or nombre.lower().endswith((":dlq", ".dlq"))
        if not incluir_dlq and es_dlq:
            continue

        pendientes = int(
            c["pendientes"] if c.get("pendientes") is not None else (c.get("profundidad") or 0)
        )
        reclamados = int(
            c["reclamados"]
            if c.get("reclamados") is not None
            else (c.get("no_confirmados") or 0)
        )
        fallidos = int(c["fallidos"] if c.get("fallidos") is not None else (c.get("dlq") or 0))
        antiguedad = int(c.get("antiguedad_max_s") or 0)
        umbral = int(c.get("umbral_atencion_s") or 0)

        # El estado se deriva del umbral configurado y la presencia de mensajes en DLQ.
        estado: Literal["normal", "atencion", "critico"]
        if (
            fallidos > 0
            or (umbral > 0 and antiguedad > umbral * 2)
            or (es_dlq and pendientes > 0)
        ):
            estado = "critico"
        elif umbral > 0 and antiguedad > umbral:
            estado = "atencion"
        else:
            estado = "normal"

        colas_out.append(
            ColaPipelineOut(
                nombre=nombre,
                pendientes=pendientes,
                reclamados=reclamados,
                fallidos=fallidos,
                profundidad=pendientes,
                no_confirmados=reclamados,
                dlq=fallidos,
                antiguedad_max_s=antiguedad,
                umbral_atencion_s=umbral,
                estado=estado,
            )
        )
    return colas_out


def _inferir_tier_modelo(raw: dict[str, Any]) -> Literal["flash", "pro", "fable"]:
    tier_raw = str(raw.get("tier") or "").strip().lower()
    if tier_raw == "flash":
        return "flash"
    if tier_raw == "pro":
        return "pro"
    if tier_raw == "fable":
        return "fable"

    modelo = str(raw.get("modelo") or "").lower()
    if any(clave in modelo for clave in ("fable", "sonnet", "opus")):
        return "fable"
    if any(clave in modelo for clave in ("pro", "deepseek")):
        return "pro"
    return "flash"


def _normalizar_proveedores(
    raw_items: list[dict[str, Any]],
    proveedor_filtro: str | None,
    tier_filtro: str | None,
) -> list[ProveedorModeloOut]:
    salida: list[ProveedorModeloOut] = []
    for raw in raw_items:
        proveedor_val = str(raw.get("proveedor") or "").strip()
        tier_val = _inferir_tier_modelo(raw)
        if proveedor_filtro is not None and proveedor_val.lower() != proveedor_filtro:
            continue
        if tier_filtro is not None and tier_val != tier_filtro:
            continue

        tasa_error_raw = raw.get("tasa_error_pct")
        if tasa_error_raw is None:
            tasa_error_raw = raw.get("error_pct")
        lat_p50 = raw.get("latencia_p50_ms")
        salida.append(
            ProveedorModeloOut(
                proveedor=proveedor_val,
                modelo=str(raw.get("modelo") or ""),
                tier=tier_val,
                llamadas=int(raw.get("llamadas") or 0),
                disponibilidad_pct=float(
                    raw["disponibilidad_pct"]
                    if raw.get("disponibilidad_pct") is not None
                    else 100.0
                ),
                latencia_p50_ms=float(lat_p50) if lat_p50 is not None else None,
                latencia_p95_ms=float(raw.get("latencia_p95_ms") or 0.0),
                tasa_error_pct=0.0 if tasa_error_raw is None else float(tasa_error_raw),
            )
        )
    return salida


def _normalizar_escalados(raw: dict[str, Any] | None) -> EscaladosLlmOut:
    datos = raw or {}
    return EscaladosLlmOut(
        flash_a_pro=int(datos.get("flash_a_pro") or 0),
        pro_a_fable=int(datos.get("pro_a_fable") or 0),
        a_humano=int(datos.get("a_humano") or 0),
    )


def _calcular_tokens_y_costes(
    db_rows: list[dict[str, Any]],
    raw_proveedores: list[dict[str, Any]],
    tarifas: dict[str, tuple[float, float]],
    tier_filtro: str | None,
) -> tuple[dict[str, int], dict[str, float]]:
    tokens_tier: dict[str, int] = {}
    coste_tier: dict[str, float] = {}

    for row in db_rows:
        tier = str(row["tier"])
        if tier_filtro is not None and tier != tier_filtro:
            continue
        t_in = int(row.get("tokens_in") or 0)
        t_out = int(row.get("tokens_out") or 0)
        t_total = int(row.get("tokens") or (t_in + t_out))
        coste_db = float(row.get("coste") or 0.0)
        if coste_db == 0.0 and (t_in > 0 or t_out > 0):
            p_in, p_out = tarifas.get(tier, (0.0, 0.0))
            coste_db = (t_in / 1000.0) * p_in + (t_out / 1000.0) * p_out
        tokens_tier[tier] = tokens_tier.get(tier, 0) + t_total
        coste_tier[tier] = round(coste_tier.get(tier, 0.0) + coste_db, 6)

    # Si no hay agregados diarios aún para algún tier reportado en telemetría,
    # estimamos con las tarifas oficiales sin mezclar jamás `fable` con `pro`.
    for raw in raw_proveedores:
        tier = _inferir_tier_modelo(raw)
        if tier_filtro is not None and tier != tier_filtro:
            continue
        if tier in tokens_tier and tokens_tier[tier] > 0:
            continue
        t_in = int(raw.get("tokens_in") or 0)
        t_out = int(raw.get("tokens_out") or 0)
        t_total = int(raw.get("tokens") or (t_in + t_out))
        if t_total <= 0:
            continue
        p_in, p_out = tarifas.get(tier, (0.0, 0.0))
        if t_in > 0 or t_out > 0:
            est = (t_in / 1000.0) * p_in + (t_out / 1000.0) * p_out
        else:
            est = (t_total / 1000.0) * p_in
        tokens_tier[tier] = tokens_tier.get(tier, 0) + t_total
        coste_tier[tier] = round(coste_tier.get(tier, 0.0) + est, 6)

    return tokens_tier, coste_tier


# ------------------------------------------------------------------ §18.24
@router.get(
    "/agents",
    response_model=OpsAgentsResponse,
    summary="Agentes y líneas de producción",
)
async def agents(
    st: Annotated[Staff, Depends(exigir(*OPS))],
    _lim: Annotated[Staff, Depends(limite_vivo)],
    ventana: Annotated[str, Query(description="5m | 1h | 24h.")] = "1h",
    etapa: Annotated[str | None, Query()] = None,
) -> OpsAgentsResponse:
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
        lineas_row = await uno(
            db,
            """
            SELECT count(*) FILTER (WHERE estado = 'ocupada')       AS activas,
                   count(*) FILTER (WHERE estado = 'mantenimiento') AS mantenimiento,
                   count(*) FILTER (WHERE estado = 'libre')         AS libres
            FROM core.production_lines
        """,
        )

    lineas_out = (
        LineasProduccionOut(
            activas=int(lineas_row["activas"] or 0),
            mantenimiento=int(lineas_row["mantenimiento"] or 0),
            libres=int(lineas_row["libres"] or 0),
        )
        if lineas_row
        else None
    )

    etapas_out = (
        None if sin_telemetria else _normalizar_etapas(datos.get("etapas") or [], etapa)
    )
    alertas_out = _construir_alertas_agentes(etapas_out or [], lineas_out)

    return OpsAgentsResponse(
        ventana=str(datos.get("ventana") or ventana),
        telemetria=TelemetriaEstadoOut(
            disponible=not sin_telemetria,
            antiguedad_s=datos.get("_antiguedad_s"),
            desde=datos.get("telemetria_desde"),
        ),
        # Sin telemetría no se inventan ceros: el consumidor debe mostrar
        # «sin telemetría» y no «sin trabajo».
        etapas=etapas_out,
        lineas=lineas_out,
        alertas=alertas_out,
    )


# ------------------------------------------------------------------ §18.25
@router.get("/queues", response_model=OpsQueuesResponse, summary="Colas del pipeline")
async def queues(
    st: Annotated[Staff, Depends(exigir(*OPS))],
    _lim: Annotated[Staff, Depends(limite_vivo)],
    incluir_dlq: Annotated[bool, Query()] = True,
) -> OpsQueuesResponse:
    """Profundidad, antigüedad y cola de fallidos de cada cola del pipeline.

    Complementa §18.24: una etapa sin agentes caídos y con la cola creciendo indica
    un problema distinto que una etapa con agentes caídos. El endpoint no consume
    mensajes ni altera ninguna cola: reprocesar o purgar es una operación de
    plataforma y no de la consola en esta versión.
    """
    datos = await telemetry.colas(incluir_dlq)
    colas_out = _normalizar_colas(datos.get("colas") or [], incluir_dlq)

    criticas = [c.nombre for c in colas_out if c.estado == "critico"]
    if criticas:
        log.warning("admin.ops.cola_critica", colas=criticas)

    return OpsQueuesResponse(
        telemetria_desde=datos.get("telemetria_desde"),
        colas=colas_out,
        resumen=ColasResumenOut(
            criticas=len(criticas),
            atencion=sum(1 for c in colas_out if c.estado == "atencion"),
            pendientes_total=sum(c.pendientes for c in colas_out),
            fallidos_total=sum(c.fallidos for c in colas_out),
        ),
    )


# ------------------------------------------------------------------ §18.26
@router.get("/models", response_model=OpsModelsResponse, summary="Modelos y proveedores")
async def models(
    st: Annotated[Staff, Depends(exigir(*OPS_NEGOCIO))],
    _lim: Annotated[Staff, Depends(limite_vivo)],
    ventana: Annotated[str, Query(description="1h | 24h | 7d | 30d.")] = "24h",
    proveedor: Annotated[str | None, Query()] = None,
    tier: Annotated[str | None, Query(description="flash | pro | fable.")] = None,
    comparar: Annotated[bool, Query()] = False,
    comparar_con: Annotated[str | None, Query(description="periodo_anterior.")] = None,
) -> OpsModelsResponse:
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

    proveedor_norm = proveedor.strip().lower() if proveedor is not None else None
    if proveedor_norm is not None and proveedor_norm not in _PROVEEDORES_MODELOS:
        raise validacion(
            "Proveedor no válido.",
            {"proveedor": proveedor, "permitidos": list(_PROVEEDORES_MODELOS)},
        )

    tier_norm = tier.strip().lower() if tier is not None else None
    if tier_norm is not None and tier_norm not in _TIERS_MODELOS:
        raise validacion("Tier no válido.", {"tier": tier, "permitidos": list(_TIERS_MODELOS)})

    comparar_con_norm = comparar_con.strip().lower() if comparar_con is not None else None
    if comparar_con_norm is not None and comparar_con_norm not in _COMPARACIONES_MODELOS:
        raise validacion(
            "Comparación no válida.",
            {"comparar_con": comparar_con, "permitidas": list(_COMPARACIONES_MODELOS)},
        )

    datos = await telemetry.proveedores(ventana, proveedor_norm, tier_norm)
    raw_proveedores = datos.get("proveedores") or []
    proveedores_out = _normalizar_proveedores(raw_proveedores, proveedor_norm, tier_norm)
    raw_modelos = datos.get("modelos")
    modelos_out = (
        _normalizar_proveedores(raw_modelos, proveedor_norm, tier_norm)
        if raw_modelos
        else list(proveedores_out)
    )

    degradados = [p for p in proveedores_out if p.disponibilidad_pct < 99.0]
    if degradados and ventana == "1h":
        log.warning(
            "admin.ops.proveedor_degradado",
            proveedores=[p.proveedor for p in degradados],
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
        tarifas_rows = await todos(
            db,
            """
            SELECT DISTINCT ON (tier) tier, precio_in, precio_out
            FROM admin.token_rates
            WHERE modelo = '*'
            ORDER BY tier, vigente_desde DESC
        """,
        )
        filtro_tier_sql = "AND d.tier = :tier" if tier_norm is not None else ""
        params_coste: dict[str, Any] = {"dias": dias}
        if tier_norm is not None:
            params_coste["tier"] = tier_norm
        coste_rows = await todos(
            db,
            f"""
            SELECT d.tier,
                   coalesce(sum(d.tokens_in), 0) AS tokens_in,
                   coalesce(sum(d.tokens_out), 0) AS tokens_out,
                   sum(d.tokens_in + d.tokens_out) AS tokens,
                   sum(d.coste) AS coste
            FROM admin.agg_tokens_daily d
            WHERE d.dia > current_date - CAST(:dias AS int)
              {filtro_tier_sql}
            GROUP BY d.tier
        """,
            params_coste,
        )

    tarifas = dict(_TARIFAS_OFICIALES_1K)
    for t_row in tarifas_rows:
        tarifas[str(t_row["tier"])] = (float(t_row["precio_in"]), float(t_row["precio_out"]))

    tokens_tier, coste_tier = _calcular_tokens_y_costes(
        coste_rows, raw_proveedores, tarifas, tier_norm
    )

    comparacion_out: ComparacionModelosOut | None = None
    if comparar or comparar_con_norm == "periodo_anterior":
        anterior = {"1h": "1h", "24h": "24h", "7d": "7d", "30d": "30d"}[ventana]
        previa = await telemetry.proveedores(anterior, proveedor_norm, tier_norm)
        prev_proveedores = _normalizar_proveedores(
            previa.get("proveedores") or [], proveedor_norm, tier_norm
        )
        comparacion_out = ComparacionModelosOut(
            periodo="periodo_anterior",
            escalados=_normalizar_escalados(previa.get("escalados")),
            proveedores=prev_proveedores,
        )

    return OpsModelsResponse(
        ventana=str(datos.get("ventana") or ventana),
        proveedores=proveedores_out,
        modelos=modelos_out,
        escalados=_normalizar_escalados(datos.get("escalados")),
        tokens_por_tier=tokens_tier,
        coste_por_tier=coste_tier,
        degradados=[p.proveedor for p in degradados] or None,
        comparacion=comparacion_out,
    )


async def _frescura_sla(db: Any) -> datetime:
    """Valida la frescura del agregado SLA (`sla_cases`) según §18.16 / §18.27.

    Emite log WARN si supera 6h (`aggregate_max_age_s`) y lanza 503 si falta,
    falló o supera 24h (`aggregate_stale_s`).
    """
    s = get_admin_settings()
    estado = await uno(
        db,
        """
        SELECT status, refreshed_at,
               extract(epoch FROM now() - refreshed_at)::int AS edad
        FROM admin.aggregate_state
        WHERE agregado = 'sla_cases'
    """,
    )
    if estado is None or estado["status"] == "fallido" or estado["refreshed_at"] is None:
        edad = int(estado["edad"]) if estado and estado.get("edad") is not None else None
        raise agregado_no_disponible("sla_cases", edad)

    edad_s = int(estado["edad"] or 0)
    if edad_s > s.aggregate_stale_s:
        raise agregado_no_disponible("sla_cases", edad_s)
    if edad_s > s.aggregate_max_age_s:
        log.warning("admin.ops.sla_frescura_alta", antiguedad_s=edad_s, agregado="sla_cases")

    refreshed_at: datetime = estado["refreshed_at"]
    return refreshed_at


def _tenant_visible(st: Staff, tenant_id: str) -> tuple[str, bool]:
    """Devuelve `(tenant_id_efectivo, enmascarado)` respetando concesiones activas."""
    if st.puede(tenant_id, "datos_negocio"):
        return tenant_id, False
    enmascarado = enmascarar_texto(tenant_id) or tenant_id
    return enmascarado, True


async def _registrar_lecturas_sla(st: Staff, endpoint: str, tenants: set[str]) -> None:
    """Registra en `admin.staff_actions` cada lectura desbloqueada por concesión activa."""
    alcanzados = tenants & set(st.grant_detalle)
    if not alcanzados:
        return
    async with admin_session() as db:
        for tenant in sorted(alcanzados):
            grant_id, alcance, motivo = st.grant_detalle[tenant]
            await registrar_lectura(
                db,
                staff_id=st.id,
                staff_role=st.role,
                endpoint=endpoint,
                tenant_id=tenant,
                grant_id=grant_id,
                scope=alcance,
                reason=motivo,
                ip=st.ip,
                user_agent=st.user_agent,
                request_id=st.request_id,
            )


def _normalizar_tramos(tramos_raw: Any) -> list[SlaClockSegmentOut]:
    """Parsea y ordena cronológicamente los tramos JSONB del reloj de un caso."""
    if isinstance(tramos_raw, str):
        parsed: list[dict[str, Any]] = json.loads(tramos_raw)
    elif isinstance(tramos_raw, list):
        parsed = list(tramos_raw)
    else:
        parsed = []

    parsed.sort(key=lambda t: str(t.get("inicio") or ""))
    salida: list[SlaClockSegmentOut] = []
    for tramo in parsed:
        raw_dur = tramo.get("duracion_h")
        if raw_dur is None:
            raw_dur = tramo.get("horas") or 0.0
        dur = round(max(0.0, float(raw_dur)), 3)
        salida.append(
            SlaClockSegmentOut(
                inicio=tramo["inicio"],
                fin=tramo.get("fin"),
                duracion_h=dur,
                horas=dur,
                computa=bool(tramo.get("computa", True)),
                etapa=tramo.get("etapa"),
                causa_pausa=tramo.get("causa_pausa"),
            )
        )
    return salida


_SQL_CASOS_UNIFICADOS_CTE = """
    WITH candidatos AS (
        SELECT s.job_id
        FROM admin.sla_clock_segments s
        WHERE (CAST(:t AS text) IS NULL OR s.tenant_id = :t)
        GROUP BY s.job_id
        HAVING to_char(min(s.inicio), 'YYYY-MM') = :ciclo
        UNION
        SELECT c.job_id
        FROM admin.sla_cases c
        WHERE to_char(c.iniciado_en, 'YYYY-MM') = :ciclo
          AND (CAST(:t AS text) IS NULL OR c.tenant_id = :t)
        UNION
        SELECT jb.id AS job_id
        FROM core.jobs jb
        WHERE to_char(jb.creado_en, 'YYYY-MM') = :ciclo
          AND (CAST(:t AS text) IS NULL OR jb.tenant_id = :t)
    ),
    reloj_vivo AS (
        SELECT rc.job_id, rc.tenant_id, rc.plan_codigo, rc.objetivo_h,
               rc.transcurrido_h, rc.bruto_h, rc.resultado, rc.tramos,
               sc.ticket_id AS sc_ticket_id,
               sc.etapa_final AS sc_etapa_final,
               jb.ticket_id AS jb_ticket_id,
               seg.ultima_etapa,
               seg.seg_ticket_id
        FROM candidatos cc
        CROSS JOIN LATERAL admin.calcular_reloj_caso(cc.job_id) rc
        LEFT JOIN admin.sla_cases sc ON sc.job_id = rc.job_id
        LEFT JOIN core.jobs jb ON jb.id = rc.job_id
        LEFT JOIN LATERAL (
            SELECT (ARRAY_AGG(s.etapa ORDER BY s.inicio DESC, s.id DESC))[1] AS ultima_etapa,
                   max(s.ticket_id) AS seg_ticket_id
            FROM admin.sla_clock_segments s
            WHERE s.job_id = rc.job_id
        ) seg ON true
    ),
    casos_unificados AS (
        SELECT rv.job_id,
               coalesce(rv.sc_ticket_id, rv.jb_ticket_id, rv.seg_ticket_id) AS ticket_id,
               rv.tenant_id,
               rv.plan_codigo AS plan,
               coalesce(rv.objetivo_h, tgt.objetivo_h) AS objetivo_h,
               rv.transcurrido_h,
               rv.bruto_h,
               rv.resultado,
               coalesce(rv.ultima_etapa, rv.sc_etapa_final) AS etapa_actual
        FROM reloj_vivo rv
        LEFT JOIN LATERAL (
            SELECT t.objetivo_h
            FROM admin.sla_targets t
            WHERE t.plan_codigo = rv.plan_codigo
              AND t.etapa IN ('total_e2e', '*')
              AND t.activo = true
            ORDER BY (t.etapa = 'total_e2e') DESC, t.vigente_desde DESC
            LIMIT 1
        ) tgt ON rv.objetivo_h IS NULL
        UNION ALL
        SELECT c.job_id,
               c.ticket_id,
               c.tenant_id,
               c.plan_codigo AS plan,
               c.objetivo_h,
               c.transcurrido_h,
               c.bruto_h,
               c.resultado,
               c.etapa_final AS etapa_actual
        FROM admin.sla_cases c
        WHERE to_char(c.iniciado_en, 'YYYY-MM') = :ciclo
          AND (CAST(:t AS text) IS NULL OR c.tenant_id = :t)
          AND NOT EXISTS (SELECT 1 FROM reloj_vivo rv WHERE rv.job_id = c.job_id)
    ),
    casos_filtrados AS (
        SELECT * FROM casos_unificados cu
        WHERE (CAST(:plan AS text) IS NULL OR cu.plan = :plan)
    )
"""


# ------------------------------------------------------------------ §18.27
@router.get(
    "/sla", summary="Cumplimiento de niveles de servicio", response_model=SlaSummaryResponse
)
async def sla(
    st: Annotated[Staff, Depends(exigir(*OPS_NEGOCIO))],
    p: Annotated[Pagina, Depends(paginacion)],
    ciclo: Annotated[str | None, Query(description="AAAA-MM; defecto, mes actual.")] = None,
    tenant_id: Annotated[str | None, Query()] = None,
    plan: Annotated[Literal["starter", "growth", "enterprise"] | None, Query()] = None,
    solo_incumplidos: Annotated[bool, Query()] = False,
) -> SlaSummaryResponse:
    """Cumplimiento por plan y cliente, percentiles, casos en riesgo y frescura (§18.27).

    Consume la función determinista `admin.calcular_cumplimiento_sla_ciclo()` y
    complementa con objetivos activos, latencias p95/media y casos activos >75%.
    """
    s = get_admin_settings()
    if ciclo is not None and not _CICLO_RE.match(ciclo):
        raise validacion("El ciclo debe tener el formato AAAA-MM.", {"ciclo": ciclo})

    ciclo_efectivo = ciclo or datetime.now(UTC).strftime("%Y-%m")
    params: dict[str, Any] = {
        "ciclo": ciclo_efectivo,
        "t": tenant_id,
        "plan": plan,
        "min": s.sla_min_cases,
        "solo": solo_incumplidos,
        "lim": p.page_size,
        "off": p.offset,
    }

    async with read_session() as db:
        frescura_dt = await _frescura_sla(db)

        # Invocar la función canónica B5-01 para trazabilidad y validación de ciclo
        await todos(
            db,
            "SELECT * FROM admin.calcular_cumplimiento_sla_ciclo(:ciclo, :t)",
            {"ciclo": ciclo_efectivo, "t": tenant_id},
        )

        objetivos_rows = await todos(
            db,
            """
            SELECT DISTINCT ON (t.plan_codigo)
                   t.plan_codigo AS plan,
                   t.objetivo_h
            FROM admin.sla_targets t
            WHERE t.etapa IN ('total_e2e', '*')
              AND t.activo = true
            ORDER BY t.plan_codigo, (t.etapa = 'total_e2e') DESC, t.vigente_desde DESC
        """,
        )
        objetivos_por_plan: dict[str, float] = {
            r["plan"]: float(r["objetivo_h"]) for r in objetivos_rows
        }

        planes_sin_def_rows = await todos(
            db,
            """
            SELECT DISTINCT p.codigo AS plan
            FROM core.plans p
            WHERE (CAST(:plan AS text) IS NULL OR p.codigo = :plan)
              AND NOT EXISTS (
                  SELECT 1 FROM admin.sla_targets t
                  WHERE t.plan_codigo = p.codigo
                    AND t.etapa IN ('total_e2e', '*')
                    AND t.activo = true
              )
            ORDER BY p.codigo
        """,
            {"plan": plan},
        )
        sin_definicion = [str(r["plan"]) for r in planes_sin_def_rows]

        resumen_row = await uno(
            db,
            _SQL_CASOS_UNIFICADOS_CTE
            + """
            SELECT count(*)::int AS casos_totales,
                   count(*) FILTER (
                       WHERE cf.resultado IN ('dentro', 'incumplido')
                   )::int AS casos_evaluados,
                   count(*) FILTER (WHERE cf.resultado = 'dentro')::int AS casos_dentro,
                   count(*) FILTER (
                       WHERE cf.resultado = 'incumplido'
                   )::int AS casos_incumplidos,
                   count(*) FILTER (
                       WHERE cf.resultado IN ('en_curso', 'en_riesgo')
                         AND cf.objetivo_h IS NOT NULL
                         AND cf.objetivo_h > 0
                         AND cf.transcurrido_h > cf.objetivo_h * 0.75
                   )::int AS casos_en_riesgo,
                   count(*) FILTER (
                       WHERE cf.resultado IN ('en_curso', 'en_riesgo')
                   )::int AS casos_en_curso,
                   count(*) FILTER (
                       WHERE cf.resultado = 'sin_objetivo'
                   )::int AS casos_sin_objetivo,
                   round(
                       100.0 * count(*) FILTER (WHERE cf.resultado = 'dentro')
                       / nullif(count(*) FILTER (
                           WHERE cf.resultado IN ('dentro', 'incumplido')
                       ), 0),
                       2
                   ) AS cumplimiento_pct_raw,
                   round(
                       avg(cf.transcurrido_h) FILTER (
                           WHERE cf.resultado IN ('dentro', 'incumplido')
                       )::numeric,
                       2
                   ) AS tiempo_medio_h,
                   round(
                       (
                           percentile_cont(0.95) WITHIN GROUP (ORDER BY cf.transcurrido_h)
                           FILTER (WHERE cf.resultado IN ('dentro', 'incumplido'))
                       )::numeric,
                       2
                   ) AS p95_h
            FROM casos_filtrados cf
        """,
            params,
        )

        por_plan_rows = await todos(
            db,
            _SQL_CASOS_UNIFICADOS_CTE
            + """
            SELECT cf.plan,
                   count(*)::int AS casos,
                   count(*) FILTER (
                       WHERE cf.resultado IN ('dentro', 'incumplido')
                   )::int AS casos_evaluados,
                   round(
                       100.0 * count(*) FILTER (WHERE cf.resultado = 'dentro')
                       / nullif(count(*) FILTER (
                           WHERE cf.resultado IN ('dentro', 'incumplido')
                       ), 0),
                       2
                   ) AS cumplimiento_pct_raw,
                   round(
                       avg(cf.transcurrido_h) FILTER (
                           WHERE cf.resultado IN ('dentro', 'incumplido')
                       )::numeric,
                       2
                   ) AS tiempo_medio_h,
                   round(
                       (
                           percentile_cont(0.95) WITHIN GROUP (ORDER BY cf.transcurrido_h)
                           FILTER (WHERE cf.resultado IN ('dentro', 'incumplido'))
                       )::numeric,
                       2
                   ) AS p95_h
            FROM casos_filtrados cf
            WHERE cf.plan IS NOT NULL
            GROUP BY cf.plan
        """,
            params,
        )

        riesgo_rows = await todos(
            db,
            _SQL_CASOS_UNIFICADOS_CTE
            + """
            SELECT cf.job_id,
                   cf.ticket_id,
                   cf.tenant_id,
                   cf.plan,
                   cf.etapa_actual,
                   cf.objetivo_h,
                   cf.transcurrido_h,
                   cf.bruto_h,
                   cf.resultado,
                   round((100.0 * cf.transcurrido_h / cf.objetivo_h)::numeric, 2)
                       AS porcentaje_objetivo
            FROM casos_filtrados cf
            WHERE cf.resultado IN ('en_curso', 'en_riesgo')
              AND cf.objetivo_h IS NOT NULL
              AND cf.objetivo_h > 0
              AND cf.transcurrido_h > cf.objetivo_h * 0.75
            ORDER BY (cf.transcurrido_h / cf.objetivo_h) DESC, cf.job_id
            LIMIT 100
        """,
            params,
        )

        total_row = await uno(
            db,
            _SQL_CASOS_UNIFICADOS_CTE
            + """
            SELECT count(DISTINCT (cf.tenant_id, coalesce(cf.plan, ''))) AS n
            FROM casos_filtrados cf
            WHERE (NOT :solo OR cf.resultado = 'incumplido')
        """,
            params,
        )

        filas_raw = await todos(
            db,
            _SQL_CASOS_UNIFICADOS_CTE
            + """
            SELECT cf.tenant_id,
                   cf.plan,
                   max(cf.objetivo_h) AS objetivo_h,
                   count(*)::int AS casos,
                   count(*) FILTER (
                       WHERE cf.resultado IN ('dentro', 'incumplido')
                   )::int AS evaluados,
                   count(*) FILTER (WHERE cf.resultado = 'incumplido')::int AS incumplidos,
                   count(*) FILTER (
                       WHERE cf.resultado IN ('en_curso', 'en_riesgo')
                         AND cf.objetivo_h IS NOT NULL
                         AND cf.objetivo_h > 0
                         AND cf.transcurrido_h > cf.objetivo_h * 0.75
                   )::int AS en_riesgo,
                   CASE
                       WHEN count(*) FILTER (
                           WHERE cf.resultado IN ('dentro', 'incumplido')
                       ) >= :min
                       THEN round(
                           100.0 * count(*) FILTER (WHERE cf.resultado = 'dentro')
                           / count(*) FILTER (WHERE cf.resultado IN ('dentro', 'incumplido')),
                           2
                       )
                   END AS cumplimiento_pct,
                   round(
                       avg(cf.transcurrido_h) FILTER (
                           WHERE cf.resultado IN ('dentro', 'incumplido')
                       )::numeric,
                       2
                   ) AS tiempo_medio_h,
                   round(
                       (
                           percentile_cont(0.95) WITHIN GROUP (ORDER BY cf.transcurrido_h)
                           FILTER (WHERE cf.resultado IN ('dentro', 'incumplido'))
                       )::numeric,
                       2
                   ) AS p95_h,
                   (SELECT cs.razon_social FROM admin.agg_customer_state cs
                    WHERE cs.tenant_id = cf.tenant_id) AS razon_social
            FROM casos_filtrados cf
            WHERE (NOT :solo OR cf.resultado = 'incumplido')
            GROUP BY cf.tenant_id, cf.plan
            ORDER BY count(*) FILTER (WHERE cf.resultado = 'incumplido') DESC, cf.tenant_id
            LIMIT :lim OFFSET :off
        """,
            params,
        )

    totales_cero = int(resumen_row["casos_totales"] or 0) if resumen_row else 0
    if totales_cero == 0 and sin_definicion and tenant_id is None and not solo_incumplidos:
        if plan is not None or len(sin_definicion) >= len(_PLANES_CANONICOS):
            raise sla_sin_definicion(", ".join(sin_definicion))

    tenants_observados: set[str] = {
        str(f["tenant_id"]) for f in filas_raw if f.get("tenant_id")
    }
    tenants_observados.update(str(r["tenant_id"]) for r in riesgo_rows if r.get("tenant_id"))
    await _registrar_lecturas_sla(st, "GET /admin/v1/ops/sla", tenants_observados)

    # Desglose por plan (solo el filtro si `plan` fue especificado, o los 3 canónicos)
    planes_salida = (plan,) if plan is not None else _PLANES_CANONICOS
    stats_por_plan = {r["plan"]: r for r in por_plan_rows if r.get("plan")}
    por_plan: dict[str, SlaPlanBreakdownOut] = {}
    for p_cod in planes_salida:
        dato = stats_por_plan.get(p_cod, {})
        evaluados_p = int(dato.get("casos_evaluados") or 0)
        raw_pct_p = dato.get("cumplimiento_pct_raw")
        pct_p = (
            float(raw_pct_p)
            if evaluados_p >= s.sla_min_cases and raw_pct_p is not None
            else None
        )
        por_plan[p_cod] = SlaPlanBreakdownOut(
            plan=p_cod,
            objetivo_h=objetivos_por_plan.get(p_cod),
            casos=int(dato.get("casos") or 0),
            casos_evaluados=evaluados_p,
            cumplimiento_pct=pct_p,
            tiempo_medio_h=(
                float(dato["tiempo_medio_h"])
                if dato.get("tiempo_medio_h") is not None
                else None
            ),
            p95_h=float(dato["p95_h"]) if dato.get("p95_h") is not None else None,
            sin_definicion=p_cod in sin_definicion,
        )

    # Enmascarado estricto de `casos_en_riesgo`
    casos_en_riesgo: list[SlaCaseRiskItemOut] = []
    for r in riesgo_rows:
        raw_tid = str(r["tenant_id"])
        tid_vis, mask_tid = _tenant_visible(st, raw_tid)
        res_riesgo: Literal["en_riesgo", "en_curso"] = (
            "en_riesgo" if r["resultado"] == "en_riesgo" else "en_curso"
        )
        casos_en_riesgo.append(
            SlaCaseRiskItemOut(
                job_id=str(r["job_id"]),
                ticket_id=r.get("ticket_id"),
                tenant_id=tid_vis,
                plan=str(r.get("plan") or ""),
                etapa_actual=r.get("etapa_actual"),
                objetivo_h=float(r["objetivo_h"]),
                transcurrido_h=float(r["transcurrido_h"]),
                bruto_h=float(r["bruto_h"]),
                porcentaje_objetivo=float(r["porcentaje_objetivo"]),
                resultado=res_riesgo,
                enmascarado=mask_tid,
            )
        )

    # Enmascarado estricto de filas paginadas (`items`)
    filas_masked, _ = enmascarar_filas(
        filas_raw, {str(f["tenant_id"]): st.concedidos(str(f["tenant_id"])) for f in filas_raw}
    )
    items_out: list[SlaTenantRowOut] = []
    for fila in filas_masked:
        raw_tid = str(fila["tenant_id"])
        tid_vis, _ = _tenant_visible(st, raw_tid)
        items_out.append(
            SlaTenantRowOut(
                tenant_id=tid_vis,
                razon_social=fila.get("razon_social"),
                plan=fila.get("plan"),
                objetivo_h=(
                    float(fila["objetivo_h"]) if fila.get("objetivo_h") is not None else None
                ),
                casos=int(fila["casos"]),
                evaluados=int(fila["evaluados"]),
                incumplidos=int(fila["incumplidos"]),
                en_riesgo=int(fila["en_riesgo"]),
                cumplimiento_pct=(
                    float(fila["cumplimiento_pct"])
                    if fila.get("cumplimiento_pct") is not None
                    else None
                ),
                tiempo_medio_h=(
                    float(fila["tiempo_medio_h"])
                    if fila.get("tiempo_medio_h") is not None
                    else None
                ),
                p95_h=float(fila["p95_h"]) if fila.get("p95_h") is not None else None,
            )
        )

    evaluados_tot = int(resumen_row["casos_evaluados"] or 0) if resumen_row else 0
    raw_pct_tot = resumen_row["cumplimiento_pct_raw"] if resumen_row else None
    pct_tot = (
        float(raw_pct_tot)
        if evaluados_tot >= s.sla_min_cases and raw_pct_tot is not None
        else None
    )
    resumen_out = SlaResumenOut(
        casos_totales=int(resumen_row["casos_totales"] or 0) if resumen_row else 0,
        casos_evaluados=evaluados_tot,
        casos_dentro=int(resumen_row["casos_dentro"] or 0) if resumen_row else 0,
        casos_incumplidos=int(resumen_row["casos_incumplidos"] or 0) if resumen_row else 0,
        casos_en_riesgo=int(resumen_row["casos_en_riesgo"] or 0) if resumen_row else 0,
        casos_en_curso=int(resumen_row["casos_en_curso"] or 0) if resumen_row else 0,
        casos_sin_objetivo=int(resumen_row["casos_sin_objetivo"] or 0) if resumen_row else 0,
        cumplimiento_pct=pct_tot,
        tiempo_medio_h=(
            float(resumen_row["tiempo_medio_h"])
            if resumen_row and resumen_row.get("tiempo_medio_h") is not None
            else None
        ),
        p95_h=(
            float(resumen_row["p95_h"])
            if resumen_row and resumen_row.get("p95_h") is not None
            else None
        ),
        evaluados=evaluados_tot,
        incumplidos=int(resumen_row["casos_incumplidos"] or 0) if resumen_row else 0,
        en_riesgo=int(resumen_row["casos_en_riesgo"] or 0) if resumen_row else 0,
        sin_objetivo=int(resumen_row["casos_sin_objetivo"] or 0) if resumen_row else 0,
    )

    sobre_pag = sobre(items_out, int(total_row["n"]) if total_row else 0, p)
    return SlaSummaryResponse(
        ciclo=ciclo_efectivo,
        resumen=resumen_out,
        por_plan=por_plan,
        casos_en_riesgo=casos_en_riesgo,
        frescura=frescura_dt,
        sin_definicion=sin_definicion,
        items=sobre_pag["items"],
        total=sobre_pag["total"],
        page=sobre_pag["page"],
        page_size=sobre_pag["page_size"],
        pages=sobre_pag["pages"],
    )


# ------------------------------------------------------------------ §18.28
@router.get(
    "/sla/cases/{job_id}",
    summary="Desglose del reloj de un caso",
    response_model=SlaCaseDetailResponse,
)
async def sla_case(
    st: Annotated[Staff, Depends(exigir(*OPS_NEGOCIO))],
    job_id: Annotated[str, Path(description="Caso cuyo reloj se desglosa.")],
) -> SlaCaseDetailResponse:
    """Desglose completo y explicabilidad matemática del reloj de SLA de un caso (§18.28).

    Invoca la función determinista `admin.calcular_reloj_caso(job_id)` y realiza
    respaldo seguro sobre `admin.sla_cases` cuando el caso fue sembrado de forma sintética.
    """
    async with read_session() as db:
        vivo = await uno(db, "SELECT * FROM admin.calcular_reloj_caso(:j)", {"j": job_id})
        meta = await uno(
            db,
            """
            SELECT c.job_id, c.tenant_id, c.ticket_id, c.ticket_numero, c.plan_codigo,
                   c.etapa_final, c.objetivo_h, c.transcurrido_h, c.bruto_h, c.resultado,
                   c.tramos, c.reglas, c.iniciado_en, c.terminado_en, c.calculado_en,
                   (SELECT s.razon_social FROM admin.agg_customer_state s
                    WHERE s.tenant_id = c.tenant_id) AS razon_social
            FROM admin.sla_cases c
            WHERE c.job_id = :j
        """,
            {"j": job_id},
        )
        if vivo is None and meta is None:
            raise job_no_encontrado(job_id)

        fuente = vivo if vivo is not None else meta
        assert fuente is not None
        raw_tenant_id = str(fuente["tenant_id"])
        ticket_id_db = meta.get("ticket_id") if meta else None
        if ticket_id_db is None:
            job_meta = await uno(
                db,
                """
                SELECT coalesce(
                    (SELECT jb.ticket_id FROM core.jobs jb WHERE jb.id = :j),
                    (
                        SELECT max(s.ticket_id)
                        FROM admin.sla_clock_segments s
                        WHERE s.job_id = :j
                    )
                ) AS ticket_id
            """,
                {"j": job_id},
            )
            ticket_id_db = job_meta.get("ticket_id") if job_meta else None

        razon_social_raw = meta.get("razon_social") if meta else None
        if razon_social_raw is None:
            org_meta = await uno(
                db,
                "SELECT razon_social FROM admin.agg_customer_state WHERE tenant_id = :t",
                {"t": raw_tenant_id},
            )
            razon_social_raw = org_meta.get("razon_social") if org_meta else None

        plan_cod: str | None = fuente.get("plan_codigo")
        objetivo_raw = fuente.get("objetivo_h")

        if objetivo_raw is None and plan_cod is not None:
            tgt = await uno(
                db,
                """
                SELECT t.objetivo_h
                FROM admin.sla_targets t
                WHERE t.plan_codigo = :p
                  AND t.etapa IN ('total_e2e', '*')
                  AND t.activo = true
                ORDER BY (t.etapa = 'total_e2e') DESC, t.vigente_desde DESC
                LIMIT 1
            """,
                {"p": plan_cod},
            )
            objetivo_raw = tgt.get("objetivo_h") if tgt else None

    if objetivo_raw is None:
        raise sla_sin_definicion(plan_cod)

    await _registrar_lecturas_sla(st, f"GET /admin/v1/ops/sla/cases/{job_id}", {raw_tenant_id})

    objetivo_h = float(objetivo_raw)
    bruto_h = round(float(fuente["bruto_h"]), 2)
    transcurrido_h = round(float(fuente["transcurrido_h"]), 2)
    pausa_total_h = round(max(0.0, bruto_h - transcurrido_h), 2)

    raw_resultado = str(fuente["resultado"])
    if (
        raw_resultado == "en_curso"
        and objetivo_h > 0
        and transcurrido_h > objetivo_h * _UMBRAL_RIESGO_RATIO
    ):
        raw_resultado = "en_riesgo"
    resultado_val: Literal["dentro", "incumplido", "en_curso", "en_riesgo", "sin_objetivo"] = (
        raw_resultado  # type: ignore[assignment]
    )

    tramos = _normalizar_tramos(fuente.get("tramos"))
    etapa_actual = (
        tramos[-1].etapa
        if tramos and tramos[-1].etapa
        else (meta.get("etapa_final") if meta else None)
    )

    reglas_raw = (
        vivo.get("reglas_aplicadas")
        if vivo is not None
        else (meta.get("reglas") if meta else [])
    )
    if isinstance(reglas_raw, str):
        reglas_list: list[str] = [str(r) for r in json.loads(reglas_raw)]
    else:
        reglas_list = [str(r) for r in (reglas_raw or [])]

    caso_dict: dict[str, Any] = {
        "tenant_id": raw_tenant_id,
        "razon_social": razon_social_raw,
        "ticket_numero": meta.get("ticket_numero") if meta else None,
    }
    caso_masked, enmascarados = _enmascarar_caso(caso_dict, st)
    tid_vis, mask_tid = _tenant_visible(st, raw_tenant_id)
    if mask_tid and "tenant_id" not in enmascarados:
        enmascarados.append("tenant_id")

    return SlaCaseDetailResponse(
        job_id=str(fuente["job_id"]),
        ticket_id=ticket_id_db,
        ticket_numero=caso_masked.get("ticket_numero"),
        razon_social=caso_masked.get("razon_social"),
        tenant_id=tid_vis,
        plan=plan_cod,
        etapa_actual=etapa_actual,
        objetivo_h=objetivo_h,
        bruto_h=bruto_h,
        transcurrido_h=transcurrido_h,
        pausa_total_h=pausa_total_h,
        resultado=resultado_val,
        tramos=tramos,
        reglas_aplicadas=reglas_list,
        iniciado_en=meta.get("iniciado_en") if meta else (tramos[0].inicio if tramos else None),
        terminado_en=meta.get("terminado_en") if meta else None,
        calculado_en=meta.get("calculado_en") if meta else None,
        enmascarado=enmascarados,
    )


def _enmascarar_caso(caso: dict[str, Any], st: Staff) -> tuple[dict[str, Any], list[str]]:
    """El número de ticket y la razón social identifican al cliente."""
    from ..masking import enmascarar

    return enmascarar(caso, st.concedidos(str(caso["tenant_id"])))


__all__ = ["router"]
