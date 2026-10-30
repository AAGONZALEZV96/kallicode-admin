"""Consultas analíticas sobre la capa agregada de negocio (KC-ADM-B3-01).

Alimenta los endpoints de la consola comercial:
  - /admin/v1/business/summary
  - /admin/v1/business/overview
  - /admin/v1/business/customers
  - /admin/v1/business/customers/{tenant_id}

Todas las consultas operan sobre las tablas agregadas del esquema `admin`
(creadas en 003_business_aggregates.sql) mediante read_session() (kallicode_admin_ro).
No se realizan escaneos directos de tablas core.* salvo para bloques secundarios
de detalle autorizado (usuarios, integraciones).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from kallicode_core.errors import no_encontrado
from kallicode_core.logging import log
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import todos, uno
from ..errors import agregado_no_disponible
from ..settings import get_admin_settings


async def verificar_frescura_agregados(db: AsyncSession, *agregados: str) -> datetime:
    """Comprueba que los agregados requeridos están dentro de su ventana de frescura.

    Lanza 503 AGREGADO_NO_DISPONIBLE si alguno falló o excede el límite de obsolescencia.
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
            "admin.business.frescura_alta",
            antiguedad_s=edad,
            agregados=list(agregados),
        )
    frescura_min: datetime = min(f["refreshed_at"] for f in filas)
    return frescura_min


def _var_pct(actual: Any, previo: Any) -> float | None:
    """Calcula la variación porcentual redondeada a 1 decimal."""
    if not previo or float(previo) == 0.0:
        return None
    return round(100.0 * (float(actual) - float(previo)) / float(previo), 1)


async def consultar_resumen_negocio(db: AsyncSession) -> dict[str, Any]:
    """Obtiene los indicadores ejecutivos consolidados del negocio."""
    frescura = await verificar_frescura_agregados(
        db, "customer_state", "monthly_business", "usage_cycle"
    )

    fila_actual = await uno(
        db,
        """
        SELECT ciclo, mrr_total, clientes_activos,
               total_tokens_flash, total_tokens_pro, total_tokens_fable,
               (total_tokens_flash + total_tokens_pro + total_tokens_fable) AS total_tokens,
               actualizado_en
        FROM admin.agg_monthly_business
        WHERE ciclo = to_char(current_date, 'YYYY-MM')
        """,
    )

    fila_prev = await uno(
        db,
        """
        SELECT ciclo, mrr_total, clientes_activos,
               (total_tokens_flash + total_tokens_pro + total_tokens_fable) AS total_tokens
        FROM admin.agg_monthly_business
        WHERE ciclo = to_char(current_date - interval '1 month', 'YYYY-MM')
        """,
    )

    # Si aún no se ha consolidado el mes en agg_monthly_business,
    # obtenemos datos en vivo de la capa agregada
    if fila_actual and float(fila_actual.get("mrr_total") or 0) > 0:
        mrr = float(fila_actual["mrr_total"])
        activos = int(fila_actual["clientes_activos"])
        flash = int(fila_actual["total_tokens_flash"])
        pro = int(fila_actual["total_tokens_pro"])
        fable = int(fila_actual["total_tokens_fable"])
        total_tokens = int(fila_actual["total_tokens"])
    else:
        cli = await uno(
            db,
            """
            SELECT count(*) FILTER (
                    WHERE c.suscripcion_estado IN ('activa', 'periodo_gracia')
                   ) AS activos,
                   coalesce(sum(c.importe_mes) FILTER (
                    WHERE c.suscripcion_estado = 'activa'), 0) AS mrr
            FROM admin.agg_customer_state c
            WHERE c.eliminado_en IS NULL
            """,
        )
        tokens_row = await uno(
            db,
            """
            SELECT coalesce(sum(tokens_in + tokens_out), 0) AS tokens,
                   coalesce(sum(tokens_flash), 0) AS flash,
                   coalesce(sum(tokens_pro), 0) AS pro,
                   coalesce(sum(tokens_fable), 0) AS fable
            FROM admin.agg_usage_cycle
            WHERE ciclo = to_char(current_date, 'YYYY-MM')
            """,
        )
        mrr = float(cli["mrr"]) if cli else 0.0
        activos = int(cli["activos"]) if cli else 0
        total_tokens = int(tokens_row["tokens"]) if tokens_row else 0
        flash = int(tokens_row["flash"]) if tokens_row else 0
        pro = int(tokens_row["pro"]) if tokens_row else 0
        fable = int(tokens_row["fable"]) if tokens_row else 0

    mrr_prev = float(fila_prev["mrr_total"]) if fila_prev else None
    activos_prev = int(fila_prev["clientes_activos"]) if fila_prev else None
    tokens_prev = int(fila_prev["total_tokens"]) if fila_prev else None

    return {
        "mrr_eur": mrr,
        "clientes_activos": activos,
        "consumo_tokens_ciclo": {
            "total": total_tokens,
            "flash": flash,
            "pro": pro,
            "fable": fable,
        },
        "tendencia": {
            "mrr_pct": _var_pct(mrr, mrr_prev),
            "clientes_pct": _var_pct(activos, activos_prev),
            "tokens_pct": _var_pct(total_tokens, tokens_prev),
        },
        "frescura": frescura.isoformat(),
    }


async def consultar_listado_clientes(
    db: AsyncSession,
    plan: str | None,
    estado: str | None,
    q: str | None,
    por_nombre: bool,
    orden_sql: str,
    limit: int,
    offset: int,
) -> tuple[list[dict[str, Any]], int, datetime]:
    """Obtiene el listado paginado y filtrado de organizaciones."""
    frescura = await verificar_frescura_agregados(db, "customer_state", "usage_cycle")

    where = """
        WHERE c.eliminado_en IS NULL
          AND (CAST(:plan AS text) IS NULL OR c.plan_codigo = :plan)
          AND (CAST(:est AS text) IS NULL OR c.suscripcion_estado = :est)
          AND (CAST(:q AS text) IS NULL
               OR c.tenant_id ILIKE '%' || CAST(:q AS text) || '%'
               OR (CAST(:por_nombre AS boolean)
                   AND c.razon_social ILIKE '%' || CAST(:q AS text) || '%'))
    """
    params = {
        "plan": plan,
        "est": estado,
        "q": q,
        "por_nombre": por_nombre,
        "lim": limit,
        "off": offset,
    }

    total_row = await uno(
        db,
        f"""
        SELECT count(*) AS n FROM admin.agg_customer_state c
        LEFT JOIN admin.agg_usage_cycle u
               ON u.tenant_id = c.tenant_id
              AND u.ciclo = to_char(current_date, 'YYYY-MM')
        {where}
        """,
        params,
    )
    total = int(total_row["n"]) if total_row else 0

    filas = await todos(
        db,
        f"""
        SELECT c.tenant_id, c.razon_social, c.plan_codigo AS plan,
               c.suscripcion_estado AS estado, c.lineas_contratadas,
               c.lineas_activas, c.alta_el,
               c.usuarios_activos, c.tickets_abiertos,
               c.ultima_actividad,
               jsonb_build_object(
                 'loc', coalesce(u.loc_consumidas, 0),
                 'tokens', coalesce(u.tokens_in + u.tokens_out, 0),
                 'cuota_pct', u.cuota_pct) AS consumo_ciclo
        FROM admin.agg_customer_state c
        LEFT JOIN admin.agg_usage_cycle u
               ON u.tenant_id = c.tenant_id
              AND u.ciclo = to_char(current_date, 'YYYY-MM')
        {where}
        ORDER BY {orden_sql} LIMIT :lim OFFSET :off
        """,
        params,
    )

    # Inyectar dominio para que el motor de enmascaramiento aplique la ofuscación "a••••.com"
    for f in filas:
        tid = str(f.get("tenant_id", ""))
        slug = tid[4:] if tid.startswith("org_") else tid
        f["dominio"] = f"{slug}.com"

    return filas, total, frescura


async def consultar_ficha_cliente(
    db: AsyncSession,
    tenant_id: str,
    bloques: set[str],
) -> tuple[dict[str, Any], datetime]:
    """Obtiene la información 360° de una organización cliente."""
    frescura = await verificar_frescura_agregados(db, "customer_state", "usage_cycle")

    c = await uno(
        db,
        "SELECT * FROM admin.agg_customer_state WHERE tenant_id = :t",
        {"t": tenant_id},
    )
    if c is None:
        raise no_encontrado("La organización")

    slug = tenant_id[4:] if tenant_id.startswith("org_") else tenant_id
    ficha: dict[str, Any] = {
        "tenant_id": c["tenant_id"],
        "razon_social": c["razon_social"],
        "dominio": f"{slug}.com",
        "despliegue": c["despliegue"],
        "idioma": c["idioma"],
        "alta_el": c["alta_el"],
        "suscripcion": {
            "plan": c["plan_codigo"],
            "estado": c["suscripcion_estado"],
            "inicia_el": c["inicia_el"],
            "renueva_el": c["renueva_el"],
            "finaliza_el": c["finaliza_el"],
            "importe_mes": (
                float(c["importe_mes"]) if c["importe_mes"] is not None else None
            ),
        },
        "lineas": {
            "contratadas": c["lineas_contratadas"],
            "activas": c["lineas_activas"],
        },
        "actividad": {
            "tickets_abiertos": c["tickets_abiertos"],
            "ultima_actividad": c["ultima_actividad"],
            "fabrica_activa": c["fabrica_activa"],
        },
    }

    consumo: dict[str, Any] = {
        "ciclo": await uno(
            db,
            """
            SELECT loc_consumidas, tokens_in, tokens_out, cuota_pct, coste
            FROM admin.agg_usage_cycle
            WHERE tenant_id = :t AND ciclo = to_char(current_date, 'YYYY-MM')
            """,
            {"t": tenant_id},
        )
        or {}
    }
    if "historico" in bloques:
        consumo["historico"] = await todos(
            db,
            """
            SELECT ciclo, loc_consumidas, tokens_in + tokens_out AS tokens,
                   coste, cuota_pct
            FROM admin.agg_usage_cycle WHERE tenant_id = :t
            ORDER BY ciclo DESC LIMIT 6
            """,
            {"t": tenant_id},
        )
    ficha["consumo"] = consumo

    if "usuarios" in bloques:
        ficha["usuarios"] = await todos(
            db,
            """
            SELECT nombre, rol, estado, ultimo_acceso
            FROM core.users WHERE tenant_id = :t
            ORDER BY ultimo_acceso DESC NULLS LAST LIMIT 50
            """,
            {"t": tenant_id},
        )
    if "integraciones" in bloques:
        ficha["integraciones"] = await todos(
            db,
            """
            SELECT proveedor, categoria, estado, ultimo_test,
                   nombre AS conexion_nombre
            FROM core.connections WHERE tenant_id = :t ORDER BY proveedor
            """,
            {"t": tenant_id},
        )
    if "grafo" in bloques:
        docs = await uno(
            db,
            """
            SELECT count(*) AS n,
                   count(*) FILTER (WHERE estado = 'procesado') AS ok
            FROM core.onboarding_documents WHERE tenant_id = :t
            """,
            {"t": tenant_id},
        )
        ficha["grafo"] = {
            "documentos": int(docs["n"]) if docs else 0,
            "documentos_procesados": int(docs["ok"]) if docs else 0,
            "fabrica_activa": c["fabrica_activa"],
        }

    return ficha, frescura


__all__ = [
    "consultar_ficha_cliente",
    "consultar_listado_clientes",
    "consultar_resumen_negocio",
    "verificar_frescura_agregados",
]
