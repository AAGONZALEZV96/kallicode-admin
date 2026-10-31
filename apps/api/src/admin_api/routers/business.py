"""§18.16 – §18.23 · Consola de negocio.

Los cuatro paneles que responden a las preguntas que la empresa se hace a diario:
cuántos clientes hay y qué pagan, quién es cada uno, qué renovaciones vienen y
cuánto consume cada cual. Todo sale de los agregados de 003, nunca de las tablas
base: consultarlas en vivo produciría esperas de segundos compitiendo con el
tráfico del portal.

Tres reglas que atraviesan el bloque:

  · La frescura es parte de la respuesta. Si el agregado está obsoleto se devuelve
    503 AGREGADO_NO_DISPONIBLE en lugar de servir un dato viejo como si fuera de
    ahora, que es peor que no mostrarlo.
  · Los datos identificables van enmascarados por defecto y su revelación exige
    concesión vigente. Se enmascara antes de construir la respuesta, no en
    presentación.
  · Ningún endpoint devuelve campos que su especificación no declare: cada campo
    extra es superficie de exposición que habría que justificar.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Path, Query, status
from kallicode_core.errors import no_encontrado, validacion
from kallicode_core.ids import nuevo
from kallicode_core.logging import log
from pydantic import BaseModel, ConfigDict, Field

from ..audit import registrar_accion, registrar_lectura
from ..consultas.business import (
    consultar_ficha_cliente,
    consultar_listado_clientes,
    consultar_resumen_negocio,
)
from ..db import admin_session, read_session, todos, uno
from ..deps import CLIENTES, NEGOCIO, Staff, exigir, exigir_concesion, limite_rl4
from ..errors import acceso_no_justificado, agregado_no_disponible
from ..masking import enmascarar, enmascarar_filas
from ..pagination import Pagina, paginacion, sobre
from ..settings import get_admin_settings

router = APIRouter(prefix="/admin/v1/business", tags=["Consola de negocio"])

_ESTADOS_SUS = ("activa", "periodo_gracia", "suspendida", "finalizada")
_MAPEO_ESTADOS: dict[str, str] = {
    "activo": "activa",
    "activa": "activa",
    "periodo_gracia": "periodo_gracia",
    "suspendido": "suspendida",
    "suspendida": "suspendida",
    "moroso": "periodo_gracia",
    "baja": "finalizada",
    "finalizada": "finalizada",
}


class _Base(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ReporteIn(_Base):
    tipo: str
    desde: date
    hasta: date
    formato: str = "csv"
    tenant_id: str | None = Field(default=None, max_length=64)
    incluir_identificables: bool = False


class ReporteOut(_Base):
    report_id: str
    estado: str
    estimacion_s: int


# --------------------------------------------------------------------- helpers
async def _frescura(db: Any, *agregados: str) -> Any:
    """Comprueba que los agregados están dentro de su ventana de frescura.

    Devuelve el refresco más antiguo, que la respuesta expone para que la interfaz
    pueda mostrarlo. Lanza 503 si alguno falló o está obsoleto: servir un dato
    viejo como si fuera actual es peor que no servirlo.
    """
    s = get_admin_settings()
    filas = await todos(
        db,
        """
        SELECT agregado, refreshed_at, status,
               extract(epoch FROM now() - refreshed_at)::int AS edad
        FROM admin.aggregate_state WHERE agregado = ANY(:ns)
    """,
        {"ns": list(agregados)},
    )
    if len(filas) < len(agregados):
        faltan = set(agregados) - {f["agregado"] for f in filas}
        raise agregado_no_disponible(", ".join(sorted(faltan)))
    for f in filas:
        if f["status"] == "fallido" or f["refreshed_at"] is None:
            raise agregado_no_disponible(f["agregado"], f["edad"])
        if f["edad"] is not None and f["edad"] > s.aggregate_stale_s:
            raise agregado_no_disponible(f["agregado"], f["edad"])
    edad = max(f["edad"] or 0 for f in filas)
    if edad > s.aggregate_max_age_s:
        log.warning(
            "admin.business.frescura_alta", antiguedad_s=edad, agregados=list(agregados)
        )
    return min(f["refreshed_at"] for f in filas)


def _concesiones(st: Staff, tenants: list[str]) -> dict[str, list[str]]:
    return {t: st.concedidos(t) for t in tenants}


async def _registrar_lecturas(st: Staff, endpoint: str, tenants: set[str]) -> None:
    """Registra una lectura por cada cliente alcanzado con concesión vigente."""
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


# ------------------------------------------------------------------ §18.16
@router.get("/summary", summary="Resumen de negocio", include_in_schema=False)
async def summary(
    st: Annotated[Staff, Depends(exigir(*NEGOCIO))],
) -> dict[str, Any]:
    """Indicadores consolidados del negocio (< 200 ms) sobre la capa agregada."""
    async with read_session() as db:
        return await consultar_resumen_negocio(db)


@router.get("/overview", summary="Panel general de negocio")
async def overview(
    st: Annotated[Staff, Depends(exigir(*NEGOCIO))],
    periodo: Annotated[
        str, Query(description="mes_actual | mes_anterior | trimestre | ano.")
    ] = "mes_actual",
    comparar_con: Annotated[
        str, Query(description="periodo_anterior | mismo_periodo_ano_anterior.")
    ] = "periodo_anterior",
) -> dict[str, Any]:
    """Indicadores agregados del negocio, con su frescura declarada.

    Ningún indicador de este endpoint identifica a un cliente concreto, así que no
    requiere concesión de acceso.
    """
    rangos = {
        "mes_actual": ("date_trunc('month', current_date)", "current_date + 1"),
        "mes_anterior": (
            "date_trunc('month', current_date) - interval '1 month'",
            "date_trunc('month', current_date)",
        ),
        "trimestre": ("date_trunc('quarter', current_date)", "current_date + 1"),
        "ano": ("date_trunc('year', current_date)", "current_date + 1"),
    }
    if periodo not in rangos:
        raise validacion(
            "Periodo no válido.", {"periodo": periodo, "permitidos": sorted(rangos)}
        )
    if comparar_con not in ("periodo_anterior", "mismo_periodo_ano_anterior"):
        raise validacion("Comparación no válida.", {"comparar_con": comparar_con})

    ini_sql, fin_sql = rangos[periodo]
    if comparar_con == "mismo_periodo_ano_anterior":
        desplaz = "interval '1 year'"
    elif periodo.startswith("mes"):
        desplaz = "interval '1 month'"
    elif periodo == "trimestre":
        desplaz = "interval '3 months'"
    else:
        desplaz = "interval '1 year'"

    async with read_session() as db:
        frescura = await _frescura(db, "customer_state", "usage_cycle", "pipeline_daily")
        datos = await uno(
            db,
            f"""
            WITH rango AS (
                SELECT ({ini_sql})::date AS ini, ({fin_sql})::date AS fin,
                       (({ini_sql}) - {desplaz})::date AS ini_prev,
                       (({fin_sql}) - {desplaz})::date AS fin_prev),
            cli AS (
                SELECT count(*) FILTER (
                        WHERE c.eliminado_en IS NULL
                          AND c.suscripcion_estado IN ('activa', 'periodo_gracia')
                       ) AS activos,
                       count(*) FILTER (
                        WHERE c.alta_el >= (SELECT ini FROM rango)
                          AND c.alta_el < (SELECT fin FROM rango)) AS nuevos,
                       count(*) FILTER (
                        WHERE c.eliminado_en >= (SELECT ini FROM rango)
                          AND c.eliminado_en < (SELECT fin FROM rango)) AS perdidos,
                       coalesce(sum(c.importe_mes) FILTER (
                        WHERE c.suscripcion_estado = 'activa'), 0) AS mrr,
                       max(c.moneda) AS moneda
                FROM admin.agg_customer_state c),
            por_plan AS (
                SELECT jsonb_object_agg(plan_codigo, n) AS j FROM (
                    SELECT coalesce(plan_codigo, 'sin_plan') AS plan_codigo,
                           count(*) AS n
                    FROM admin.agg_customer_state
                    WHERE eliminado_en IS NULL
                      AND suscripcion_estado IN ('activa', 'periodo_gracia')
                    GROUP BY 1) x),
            cons AS (
                SELECT coalesce(sum(u.loc_consumidas), 0) AS loc,
                       coalesce(sum(u.tokens_in + u.tokens_out), 0) AS tokens,
                       coalesce(sum(u.coste), 0) AS coste
                FROM admin.agg_usage_cycle u
                WHERE to_date(u.ciclo || '-01', 'YYYY-MM-DD')
                          >= date_trunc('month', (SELECT ini FROM rango))
                  AND to_date(u.ciclo || '-01', 'YYYY-MM-DD')
                          < (SELECT fin FROM rango)),
            cons_prev AS (
                SELECT coalesce(sum(u.loc_consumidas), 0) AS loc
                FROM admin.agg_usage_cycle u
                WHERE to_date(u.ciclo || '-01', 'YYYY-MM-DD')
                          >= date_trunc('month', (SELECT ini_prev FROM rango))
                  AND to_date(u.ciclo || '-01', 'YYYY-MM-DD')
                          < (SELECT fin_prev FROM rango)),
            pipe AS (
                SELECT coalesce(sum(p.tickets_entregados), 0) AS entregados,
                       round(avg(p.tiempo_e2e_p50_h), 2) AS e2e_p50,
                       coalesce(sum(p.escalados_humano), 0) AS escalados,
                       coalesce(sum(p.jobs_completados), 0) AS jobs
                FROM admin.agg_pipeline_daily p
                WHERE p.dia >= (SELECT ini FROM rango)
                  AND p.dia < (SELECT fin FROM rango)),
            pipe_prev AS (
                SELECT coalesce(sum(p.tickets_entregados), 0) AS entregados
                FROM admin.agg_pipeline_daily p
                WHERE p.dia >= (SELECT ini_prev FROM rango)
                  AND p.dia < (SELECT fin_prev FROM rango))
            SELECT (SELECT ini FROM rango) AS ini,
                   (SELECT fin FROM rango) - 1 AS fin,
                   cli.activos, cli.nuevos, cli.perdidos, cli.mrr, cli.moneda,
                   por_plan.j AS por_plan,
                   cons.loc, cons.tokens, cons.coste, cons_prev.loc AS loc_prev,
                   pipe.entregados, pipe.e2e_p50, pipe.escalados, pipe.jobs,
                   pipe_prev.entregados AS entregados_prev
            FROM cli, por_plan, cons, cons_prev, pipe, pipe_prev
        """,
        )

    assert datos is not None

    def _var(actual: Any, previo: Any) -> float | None:
        # Sin base de comparación no se inventa una tendencia: se devuelve nulo.
        if not previo:
            return None
        return round(100.0 * (float(actual) - float(previo)) / float(previo), 1)

    escalado_pct = (
        round(100.0 * datos["escalados"] / datos["jobs"], 1) if datos["jobs"] else 0.0
    )
    return {
        "periodo": {"inicio": datos["ini"], "fin": datos["fin"]},
        "frescura": frescura,
        "clientes": {
            "activos": datos["activos"],
            "nuevos": datos["nuevos"],
            "perdidos": datos["perdidos"],
            "por_plan": datos["por_plan"] or {},
        },
        "ingresos": {
            "importe": float(datos["mrr"]),
            "moneda": datos["moneda"] or "EUR",
        },
        "ingreso_recurrente": {
            "importe": float(datos["mrr"]),
            "moneda": datos["moneda"] or "EUR",
        },
        "mrr_eur": float(datos["mrr"]),
        "consumo": {
            "loc": int(datos["loc"]),
            "tokens": int(datos["tokens"]),
            "coste_estimado": float(datos["coste"]),
        },
        "pipeline": {
            "tickets_entregados": int(datos["entregados"]),
            "tiempo_e2e_p50_h": (
                float(datos["e2e_p50"]) if datos["e2e_p50"] is not None else None
            ),
            "escalado_humano_pct": escalado_pct,
        },
        "tendencia": {
            "consumo": _var(datos["loc"], datos["loc_prev"]),
            "pipeline": _var(datos["entregados"], datos["entregados_prev"]),
        },
    }


# ------------------------------------------------------------------ §18.17
ALLOWLIST_CLIENTES: dict[str, str] = {
    "tenant_id": "c.tenant_id",
    "plan": "c.plan_codigo",
    "estado": "c.suscripcion_estado",
    "mrr_eur": "c.mrr_eur",
    "creado_en": "c.alta_el",
    "actualizado_en": "c.actualizado_en",
    "consumo": "u.loc_consumidas",
    "alta": "c.alta_el",
    "nombre": "c.razon_social",
}


@router.get("/customers", summary="Listar clientes")
async def customers(
    st: Annotated[Staff, Depends(exigir(*CLIENTES))],
    p: Annotated[Pagina, Depends(paginacion)],
    plan: Annotated[str | None, Query()] = None,
    estado: Annotated[
        str | None, Query(description="activa | periodo_gracia | suspendida | finalizada.")
    ] = None,
    q: Annotated[
        str | None,
        Query(description="Búsqueda por identificador. Por razón social exige concesión."),
    ] = None,
) -> dict[str, Any]:
    """Listado de organizaciones con plan, estado, consumo y actividad.

    La búsqueda por razón social exige concesión vigente: permitirla sin ella
    convertiría el listado en un directorio de clientes consultable por cualquier
    empleado.
    """
    estado_normalizado = _MAPEO_ESTADOS.get(estado) if estado is not None else None
    if estado is not None and estado_normalizado is None:
        raise validacion(
            "Estado no válido.", {"estado": estado, "permitidos": sorted(set(_MAPEO_ESTADOS))}
        )

    por_nombre = bool(q) and not (q or "").startswith("org_")
    if por_nombre and not st.grants:
        raise acceso_no_justificado(alcance="datos_negocio")

    orden = p.clausula_order(
        ALLOWLIST_CLIENTES,
        "u.loc_consumidas DESC NULLS LAST",
    )

    async with read_session() as db:
        filas, total, frescura = await consultar_listado_clientes(
            db,
            plan=plan,
            estado=estado_normalizado,
            q=q,
            por_nombre=por_nombre,
            orden_sql=orden,
            limit=p.page_size,
            offset=p.offset,
        )

    tenants = [f["tenant_id"] for f in filas]
    filas, alguna = enmascarar_filas(filas, _concesiones(st, tenants))
    await _registrar_lecturas(st, "GET /admin/v1/business/customers", set(tenants))

    salida = sobre(filas, total, p)
    salida["frescura"] = frescura.isoformat()
    salida["alguna_enmascarada"] = alguna
    return salida


# ------------------------------------------------------------------ §18.18
@router.get("/customers/{tenant_id}", summary="Ficha de cliente")
async def customer(
    st: Annotated[Staff, Depends(exigir(*CLIENTES))],
    tenant_id: Annotated[str, Path(description="Organización a consultar.")],
    incluir: Annotated[
        str | None, Query(description="usuarios, integraciones, historico, grafo.")
    ] = None,
) -> dict[str, Any]:
    """Reúne todo lo que hay que saber de un cliente en una sola respuesta.

    Los bloques de identificación, usuarios e integraciones exigen concesión de
    alcance `datos_negocio` o superior; sin ella se devuelven enmascarados y la
    petición no falla. El bloque de grafo no incluye rutas de fichero ni nombres de
    símbolo: eso pertenece al alcance `contenido_codigo` y no se sirve aquí.
    """
    permitidos = {"usuarios", "integraciones", "historico", "grafo"}
    bloques = {b.strip() for b in (incluir or ",".join(permitidos)).split(",") if b.strip()}
    if bloques - permitidos:
        raise validacion("Bloque desconocido.", {"bloques": sorted(bloques - permitidos)})

    async with read_session() as db:
        ficha, frescura = await consultar_ficha_cliente(db, tenant_id, bloques)

    ficha["frescura"] = frescura.isoformat()
    ficha, enmascarados = enmascarar(ficha, st.concedidos(tenant_id))
    ficha["enmascarado"] = enmascarados

    if tenant_id in st.grant_detalle:
        grant_id, alcance, motivo = st.grant_detalle[tenant_id]
        async with admin_session() as db:
            await registrar_lectura(
                db,
                staff_id=st.id,
                staff_role=st.role,
                endpoint=f"GET /admin/v1/business/customers/{tenant_id}",
                tenant_id=tenant_id,
                grant_id=grant_id,
                scope=alcance,
                reason=motivo,
                resource=tenant_id,
                ip=st.ip,
                user_agent=st.user_agent,
                request_id=st.request_id,
                revelado=sorted(bloques - set(enmascarados)) or None,
            )
    return ficha


# ------------------------------------------------------------------ §18.19
ALLOWLIST_SUSCRIPCIONES: dict[str, str] = {
    "renovacion": "c.renueva_el",
    "renueva_el": "c.renueva_el",
    "nombre": "c.razon_social",
    "razon_social": "c.razon_social",
    "importe": "c.importe_mes",
    "importe_mes": "c.importe_mes",
    "tenant_id": "c.tenant_id",
    "plan": "c.plan_codigo",
    "estado": "c.suscripcion_estado",
    "inicia_el": "c.inicia_el",
    "finaliza_el": "c.finaliza_el",
}


@router.get("/subscriptions", summary="Suscripciones y renovaciones")
async def subscriptions(
    st: Annotated[Staff, Depends(exigir(*NEGOCIO))],
    p: Annotated[Pagina, Depends(paginacion)],
    estado: Annotated[str | None, Query()] = None,
    renueva_en_dias: Annotated[int | None, Query(ge=1, le=90)] = None,
    plan: Annotated[str | None, Query()] = None,
) -> dict[str, Any]:
    """Suscripciones con su próxima renovación por aniversario de contratación.

    La consola es de solo lectura sobre este dominio: aprobar un cambio de plan o
    suspender una suscripción se hace desde el flujo comercial de §15.
    """
    if estado is not None and estado not in _ESTADOS_SUS:
        raise validacion(
            "Estado no válido.", {"estado": estado, "permitidos": list(_ESTADOS_SUS)}
        )

    where = """
        WHERE c.eliminado_en IS NULL
          AND (CAST(:est AS text) IS NULL OR c.suscripcion_estado = :est)
          AND (CAST(:plan AS text) IS NULL OR c.plan_codigo = :plan)
          AND (CAST(:dias AS integer) IS NULL OR (c.renueva_el IS NOT NULL
               AND c.renueva_el <= current_date + cast(:dias AS integer)
               AND c.renueva_el >= current_date))
    """
    params = {
        "est": estado,
        "plan": plan,
        "dias": renueva_en_dias,
        "lim": p.page_size,
        "off": p.offset,
    }
    orden = p.clausula_order(
        ALLOWLIST_SUSCRIPCIONES,
        "c.renueva_el ASC NULLS LAST",
    )

    async with read_session() as db:
        await _frescura(db, "customer_state", "usage_cycle")
        total = await uno(
            db, f"SELECT count(*) AS n FROM admin.agg_customer_state c {where}", params
        )
        filas = await todos(
            db,
            f"""
            SELECT c.tenant_id, c.razon_social, c.plan_codigo AS plan,
                   c.suscripcion_estado AS estado, c.suscripcion_estado,
                   c.inicia_el, c.renueva_el,
                   c.finaliza_el,
                   (c.renueva_el - current_date) AS dias_para_renovacion,
                   c.importe_mes, c.moneda,
                   (SELECT u.cuota_pct FROM admin.agg_usage_cycle u
                     WHERE u.tenant_id = c.tenant_id
                       AND u.ciclo = to_char(current_date, 'YYYY-MM'))
                   AS cuota_uso_pct
            FROM admin.agg_customer_state c
            {where}
            ORDER BY {orden} LIMIT :lim OFFSET :off
        """,
            params,
        )

    filas, alguna = enmascarar_filas(filas, _concesiones(st, [f["tenant_id"] for f in filas]))
    salida = sobre(filas, int(total["n"]) if total else 0, p)
    salida["alguna_enmascarada"] = alguna
    return salida


# ------------------------------------------------------------------ §18.20
@router.get("/upgrade-requests", summary="Solicitudes de cambio de plan")
async def upgrade_requests(
    st: Annotated[Staff, Depends(exigir(*NEGOCIO))],
    p: Annotated[Pagina, Depends(paginacion)],
    estado: Annotated[str | None, Query()] = "pendiente",
    plan_deseado: Annotated[str | None, Query()] = None,
) -> dict[str, Any]:
    """Cola de solicitudes de cambio de plan, ordenada por antigüedad.

    El orden por defecto es la solicitud más antigua primero: una solicitud
    olvidada es la peor de las respuestas posibles.
    """
    where = (
        "WHERE (CAST(:est AS text) IS NULL OR r.estado = :est) "
        "AND (CAST(:pd AS text) IS NULL OR r.plan_deseado = :pd)"
    )
    params = {"est": estado, "pd": plan_deseado, "lim": p.page_size, "off": p.offset}
    orden = p.clausula_order(
        {"antiguedad": "r.solicitado_el", "urgente": "r.urgente"}, "r.solicitado_el ASC"
    )

    async with read_session() as db:
        await _frescura(db, "upgrade_requests")
        total = await uno(
            db, f"SELECT count(*) AS n FROM admin.agg_upgrade_requests r {where}", params
        )
        filas = await todos(
            db,
            f"""
            SELECT r.solicitud_id, r.tenant_id, r.razon_social, r.plan_actual,
                   r.plan_deseado, r.urgente, r.estado, r.comentario,
                   r.solicitado_el, r.cuota_uso_pct,
                   (extract(epoch FROM now() - r.solicitado_el) / 3600)::int
                       AS antiguedad_h
            FROM admin.agg_upgrade_requests r
            {where}
            ORDER BY {orden} LIMIT :lim OFFSET :off
        """,
            params,
        )

    filas, alguna = enmascarar_filas(filas, _concesiones(st, [f["tenant_id"] for f in filas]))
    salida = sobre(filas, int(total["n"]) if total else 0, p)
    salida["alguna_enmascarada"] = alguna
    return salida


# ------------------------------------------------------------------ §18.21
@router.get("/usage/tokens", summary="Consumo de tokens por cliente, tier y periodo")
async def usage_tokens(
    st: Annotated[Staff, Depends(exigir(*NEGOCIO))],
    p: Annotated[Pagina, Depends(paginacion)],
    ciclo: Annotated[str | None, Query(description="AAAA-MM; defecto, ciclo en curso.")] = None,
    tenant_id: Annotated[str | None, Query()] = None,
    agrupar_por: Annotated[str, Query(description="cliente | tier | dia.")] = "cliente",
) -> dict[str, Any]:
    """Consumo con su coste estimado y el cuadre contra la facturación.

    El tier fable se reporta por separado y no agregado con pro: su coste no es
    comparable y agregarlos invalidaría el cálculo. Y el campo
    `cuadra_con_facturacion` no es decorativo: si es falso, la interfaz debe
    advertirlo de forma visible en lugar de mostrar la cifra como buena.
    """
    if agrupar_por not in ("cliente", "tier", "dia"):
        raise validacion("Agrupación no válida.", {"agrupar_por": agrupar_por})
    if ciclo is not None and len(ciclo) != 7:
        raise validacion("El ciclo debe tener el formato AAAA-MM.", {"ciclo": ciclo})

    params: dict[str, Any] = {
        "ciclo": ciclo,
        "t": tenant_id,
        "lim": p.page_size,
        "off": p.offset,
    }
    consultas = {
        "cliente": (
            """
            SELECT count(*) AS n FROM admin.agg_usage_cycle u
            WHERE u.ciclo = coalesce(CAST(:ciclo AS text), to_char(current_date, 'YYYY-MM'))
              AND (CAST(:t AS text) IS NULL OR u.tenant_id = :t)""",
            """
            SELECT u.tenant_id AS clave, u.tenant_id, u.tokens_in, u.tokens_out,
                   jsonb_build_object('flash', u.tokens_flash, 'pro', u.tokens_pro,
                                      'fable', u.tokens_fable) AS por_tier,
                   u.coste, u.loc_consumidas, u.cuota_pct,
                   (u.loc_consumidas = coalesce((
                        SELECT c.loc_consumidas FROM core.usage_cycles c
                         WHERE c.tenant_id = u.tenant_id AND c.ciclo = u.ciclo),
                        u.loc_consumidas)) AS cuadra_con_facturacion
            FROM admin.agg_usage_cycle u
            WHERE u.ciclo = coalesce(CAST(:ciclo AS text), to_char(current_date, 'YYYY-MM'))
              AND (CAST(:t AS text) IS NULL OR u.tenant_id = :t)
            ORDER BY u.coste DESC LIMIT :lim OFFSET :off""",
        ),
        "tier": (
            """
            SELECT count(DISTINCT d.tier) AS n FROM admin.agg_tokens_daily d
            WHERE to_char(d.dia, 'YYYY-MM')
                      = coalesce(CAST(:ciclo AS text), to_char(current_date, 'YYYY-MM'))""",
            """
            SELECT d.tier AS clave, NULL::text AS tenant_id,
                   sum(d.tokens_in) AS tokens_in, sum(d.tokens_out) AS tokens_out,
                   jsonb_build_object(d.tier,
                        sum(d.tokens_in + d.tokens_out)) AS por_tier,
                   sum(d.coste) AS coste, NULL::int AS loc_consumidas,
                   NULL::numeric AS cuota_pct, true AS cuadra_con_facturacion
            FROM admin.agg_tokens_daily d
            WHERE to_char(d.dia, 'YYYY-MM')
                      = coalesce(CAST(:ciclo AS text), to_char(current_date, 'YYYY-MM'))
              AND (CAST(:t AS text) IS NULL OR d.tenant_id = :t)
            GROUP BY d.tier ORDER BY sum(d.coste) DESC
            LIMIT :lim OFFSET :off""",
        ),
        "dia": (
            """
            SELECT count(DISTINCT d.dia) AS n FROM admin.agg_tokens_daily d
            WHERE to_char(d.dia, 'YYYY-MM')
                      = coalesce(CAST(:ciclo AS text), to_char(current_date, 'YYYY-MM'))""",
            """
            SELECT d.dia::text AS clave, NULL::text AS tenant_id,
                   sum(d.tokens_in) AS tokens_in, sum(d.tokens_out) AS tokens_out,
                   jsonb_object_agg(d.tier, d.tokens_in + d.tokens_out) AS por_tier,
                   sum(d.coste) AS coste, NULL::int AS loc_consumidas,
                   NULL::numeric AS cuota_pct, true AS cuadra_con_facturacion
            FROM admin.agg_tokens_daily d
            WHERE to_char(d.dia, 'YYYY-MM')
                      = coalesce(CAST(:ciclo AS text), to_char(current_date, 'YYYY-MM'))
              AND (CAST(:t AS text) IS NULL OR d.tenant_id = :t)
            GROUP BY d.dia ORDER BY d.dia DESC LIMIT :lim OFFSET :off""",
        ),
    }
    sql_total, sql = consultas[agrupar_por]

    async with read_session() as db:
        frescura = await _frescura(db, "usage_cycle", "tokens_daily")
        totales = await uno(
            db,
            """
            SELECT coalesce(sum(tokens_in + tokens_out), 0) AS tokens,
                   coalesce(sum(coste), 0) AS coste, max(moneda) AS moneda
            FROM admin.agg_usage_cycle
            WHERE ciclo = coalesce(CAST(:ciclo AS text), to_char(current_date, 'YYYY-MM'))
              AND (CAST(:t AS text) IS NULL OR tenant_id = :t)
        """,
            params,
        )
        total = await uno(db, sql_total, params)
        filas = await todos(db, sql, params)

    descuadres = [f["clave"] for f in filas if f.get("cuadra_con_facturacion") is False]
    if descuadres:
        # Una consola de negocio cuyo consumo no cuadra con la factura destruye
        # la confianza en todas sus demás cifras: es alerta, no aviso.
        log.critical("admin.usage.descuadre", claves=descuadres[:10], ciclo=ciclo or "actual")

    if agrupar_por == "cliente":
        filas, _ = enmascarar_filas(
            filas, _concesiones(st, [f["tenant_id"] for f in filas if f["tenant_id"]])
        )

    salida = sobre(filas, int(total["n"]) if total else 0, p)
    salida["ciclo"] = ciclo or datetime.now().strftime("%Y-%m")
    salida["frescura"] = frescura
    salida["totales"] = {
        "tokens": int(totales["tokens"]) if totales else 0,
        "coste": float(totales["coste"]) if totales else 0.0,
        "moneda": (totales or {}).get("moneda") or "EUR",
    }
    salida["descuadres"] = descuadres or None
    return salida


# ------------------------------------------------------------------ §18.22
@router.post(
    "/reports",
    response_model=ReporteOut,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Solicitar informe de negocio",
)
async def crear_informe(
    cuerpo: ReporteIn,
    st: Annotated[Staff, Depends(exigir(*NEGOCIO))],
) -> ReporteOut:
    """Encola un informe exportable.

    El informe hereda el enmascarado del solicitante: sin concesión vigente,
    `incluir_identificables` se rechaza con 403 en lugar de generar en silencio un
    fichero recortado. Ningún informe puede exportar más de lo que el empleado ve
    en pantalla.
    """
    s = get_admin_settings()
    if cuerpo.tipo not in ("consumo", "suscripciones", "clientes", "sla"):
        raise validacion("Tipo de informe desconocido.", {"tipo": cuerpo.tipo})
    if cuerpo.formato not in ("csv", "xlsx"):
        raise validacion("Formato no admitido.", {"formato": cuerpo.formato})
    if cuerpo.desde > cuerpo.hasta:
        raise validacion("El rango de fechas no es válido.")
    meses = (cuerpo.hasta - cuerpo.desde).days / 30.0
    if meses > s.report_max_months:
        raise validacion(
            f"El rango no puede superar {s.report_max_months} meses.",
            {"meses": round(meses, 1)},
        )

    if cuerpo.incluir_identificables:
        if cuerpo.tenant_id:
            await exigir_concesion(st, cuerpo.tenant_id, "datos_negocio")
        elif not st.grants:
            raise acceso_no_justificado(alcance="datos_negocio")

    report_id = nuevo("rp")
    async with admin_session() as db:
        await uno(
            db,
            """
            INSERT INTO admin.reports
                (id, kind, format, params, requested_by, includes_pii, status,
                 expires_at)
            VALUES (:id, :k, :f, CAST(:p AS jsonb), :by, :pii, 'en_cola',
                    now() + make_interval(days => :ret))
            RETURNING id
        """,
            {
                "id": report_id,
                "k": cuerpo.tipo,
                "f": cuerpo.formato,
                "p": cuerpo.model_dump_json(),
                "by": st.id,
                "pii": cuerpo.incluir_identificables,
                "ret": s.report_retention_days,
            },
        )
        await registrar_accion(
            db,
            staff_id=st.id,
            staff_role=st.role,
            action="report",
            endpoint="POST /admin/v1/business/reports",
            tenant_id=cuerpo.tenant_id,
            ip=st.ip,
            user_agent=st.user_agent,
            request_id=st.request_id,
            payload={
                "report_id": report_id,
                "tipo": cuerpo.tipo,
                "rango": [str(cuerpo.desde), str(cuerpo.hasta)],
                "identificables": cuerpo.incluir_identificables,
            },
        )

    log.info(
        "admin.report.solicitado",
        report_id=report_id,
        tipo=cuerpo.tipo,
        identificables=cuerpo.incluir_identificables,
        staff_id=st.id,
    )
    return ReporteOut(
        report_id=report_id, estado="en_cola", estimacion_s=max(10, int(meses * 3))
    )


# ------------------------------------------------------------------ §18.23
@router.get("/reports/{report_id}", summary="Estado y descarga de un informe")
async def informe(
    st: Annotated[Staff, Depends(limite_rl4)],
    report_id: Annotated[str, Path()],
) -> dict[str, Any]:
    """Estado del informe y, si está listo, URL firmada de vencimiento corto.

    No se sirve como descarga directa sin registro: toda salida de datos queda
    trazada. Un empleado solo accede a los informes que ha solicitado; el rol de
    administración accede a todos.
    """
    from ..servicios.blob import url_descarga

    async with admin_session() as db:
        r = await uno(
            db,
            """
            SELECT r.id, r.kind, r.format, r.status, r.blob_ref, r.sha256,
                   r.rows_total, r.error, r.expires_at, r.requested_by,
                   s.full_name AS solicitante
            FROM admin.reports r
            JOIN admin.staff s ON s.id = r.requested_by
            WHERE r.id = :i
        """,
            {"i": report_id},
        )
        if r is None or (r["requested_by"] != st.id and st.role != "staff_admin"):
            raise no_encontrado("El informe")

        url = None
        if r["status"] == "listo" and r["blob_ref"]:
            url = url_descarga(r["blob_ref"])
            await registrar_accion(
                db,
                staff_id=st.id,
                staff_role=st.role,
                action="report",
                endpoint=f"GET /admin/v1/business/reports/{report_id}",
                ip=st.ip,
                user_agent=st.user_agent,
                request_id=st.request_id,
                payload={"report_id": report_id, "evento": "descargado", "sha256": r["sha256"]},
            )
            log.info("admin.report.descargado", report_id=report_id, staff_id=st.id)

    return {
        "report_id": r["id"],
        "tipo": r["kind"],
        "formato": r["format"],
        "estado": r["status"],
        "solicitado_por": {"id": r["requested_by"], "nombre": r["solicitante"]},
        "download_url": url,
        "hash_sha256": r["sha256"],
        "filas": r["rows_total"],
        "caduca_el": r["expires_at"],
        "error": r["error"],
    }


__all__ = ["router"]
