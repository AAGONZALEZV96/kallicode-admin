"""Generador determinista y reproducible de informes de cumplimiento SLA (§18.22 / ADM-G07).

Ticket [KC-ADM-B5-11]: Compila informes ejecutivos y contractuales de cumplimiento
de SLA por cliente y periodo a partir de `admin.agg_sla_compliance`, `admin.sla_cases`,
`admin.sla_targets` y `admin.aggregate_state`.

Garantías arquitectónicas E6:
  - Determinismo criptográfico: dos compilaciones sobre el mismo periodo cerrado
    (mismos filtros y datos) producen exactamente los mismos bytes y SHA-256.
  - Enmascaramiento por defecto (ADM-G09): razón social enmascarada (`A•••• S.L.`)
    y ausencia total de correos o datos personales salvo concesión vigente.
  - Muestra mínima estadística: clientes o resúmenes con < 5 casos evaluados
    muestran `"N/A"` en su porcentaje de cumplimiento.
  - Regla de oro del reloj SLA: diferencia claramente tiempo bruto, computable y
    causas de pausa tipificadas (espera_firma_cliente, ventana_mantenimiento, etc.).
"""

from __future__ import annotations

import calendar
import csv
import hashlib
import io
import json
from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from kallicode_core.errors import validacion
from sqlalchemy.ext.asyncio import AsyncSession

from .audit import registrar_accion
from .db import admin_session, read_session, todos
from .deps import Staff, exigir_concesion
from .errors import acceso_no_justificado
from .masking import alcance_suficiente, enmascarar_texto

FORMATOS_SLA: tuple[str, ...] = ("csv", "json")
MAX_MESES_SLA: int = 24
MUESTRA_MINIMA_SLA: int = 5
_Q2 = Decimal("0.01")


def _sumar_meses(fecha: date, meses: int) -> date:
    """Suma meses calendario preservando el fin de mes cuando aplica."""
    total_meses = (fecha.year * 12 + (fecha.month - 1)) + meses
    anio = total_meses // 12
    mes = (total_meses % 12) + 1
    ultimo_dia = calendar.monthrange(anio, mes)[1]
    return date(anio, mes, min(fecha.day, ultimo_dia))


def _parse_fecha(valor: date | str, campo: str) -> date:
    if isinstance(valor, datetime):
        return valor.date()
    if isinstance(valor, date):
        return valor
    texto = str(valor).strip()[:10]
    try:
        return date.fromisoformat(texto)
    except ValueError as exc:
        raise validacion(f"Fecha inválida en '{campo}'.", {campo: valor}) from exc


def validar_rango_sla(
    desde: date | str,
    hasta: date | str,
    max_meses: int = MAX_MESES_SLA,
) -> tuple[date, date]:
    """Valida que `desde <= hasta` y que el periodo no supere `max_meses` meses."""
    d_ini = _parse_fecha(desde, "desde")
    d_fin = _parse_fecha(hasta, "hasta")
    if d_ini > d_fin:
        raise validacion(
            "El rango de fechas no es válido (desde es posterior a hasta).",
            {"desde": d_ini.isoformat(), "hasta": d_fin.isoformat()},
        )
    limite = _sumar_meses(d_ini, max_meses)
    if d_fin > limite:
        raise validacion(
            f"El rango no puede superar {max_meses} meses.",
            {"desde": d_ini.isoformat(), "hasta": d_fin.isoformat(), "max_meses": max_meses},
        )
    return d_ini, d_fin


def _iso_utc(valor: datetime | str | None) -> str | None:
    if valor is None:
        return None
    if isinstance(valor, datetime):
        dt = valor if valor.tzinfo is not None else valor.replace(tzinfo=UTC)
        return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    texto = str(valor).strip()
    if not texto:
        return None
    if texto.endswith("Z") and len(texto) >= 20:
        return texto
    try:
        parsed = datetime.fromisoformat(texto)
        dt = parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)
        return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        return texto


def _round2(valor: Decimal | float | int | None) -> float:
    if valor is None:
        return 0.0
    dec = valor if isinstance(valor, Decimal) else Decimal(str(valor))
    return float(dec.quantize(_Q2, rounding=ROUND_HALF_UP))


def _pct_cumplimiento(dentro: int, evaluados: int) -> tuple[str | float, float | None]:
    """Devuelve ('N/A', None) si la muestra evaluada es inferior al umbral mínimo."""
    if evaluados < MUESTRA_MINIMA_SLA or evaluados <= 0:
        return "N/A", None
    pct = float(
        (Decimal(dentro) * Decimal("100") / Decimal(evaluados)).quantize(
            _Q2, rounding=ROUND_HALF_UP
        )
    )
    return pct, pct


def _extraer_tramos(raw_tramos: Any) -> list[dict[str, Any]]:
    if raw_tramos is None:
        return []
    if isinstance(raw_tramos, str):
        try:
            dec = json.loads(raw_tramos)
            return list(dec) if isinstance(dec, list) else []
        except ValueError:
            return []
    if isinstance(raw_tramos, list):
        return [t for t in raw_tramos if isinstance(t, dict)]
    return []


def _motivos_pausa_caso(tramos: list[dict[str, Any]]) -> list[str]:
    motivos: set[str] = set()
    for t in tramos:
        computa = t.get("computa")
        causa = t.get("causa_pausa")
        if computa is False and causa:
            motivos.add(str(causa).strip())
    return sorted(motivos)


async def _verificar_autorizacion_identificables(
    db: AsyncSession,
    *,
    tenant_id: str | None,
    solicitante: Staff | None,
    solicitante_id: str | None,
    concesion_validada: bool,
) -> dict[str, bool]:
    """Verifica permisos ADM-G09 y devuelve qué tenants tienen concesión vigente."""
    if concesion_validada:
        if tenant_id:
            return {tenant_id: True}
        return {"*": True}

    if solicitante is not None:
        if tenant_id:
            await exigir_concesion(solicitante, tenant_id, "datos_negocio")
            return {tenant_id: True}
        permitidos: dict[str, bool] = {}
        for tid_g, alcances in solicitante.grants.items():
            if alcance_suficiente(alcances, "datos_negocio"):
                permitidos[tid_g] = True
        if not permitidos:
            raise acceso_no_justificado(alcance="datos_negocio")
        return permitidos

    if not solicitante_id:
        raise acceso_no_justificado(tenant_id=tenant_id, alcance="datos_negocio")

    cond_tenant = "AND tenant_id = :tid" if tenant_id else ""
    q_params: dict[str, Any] = {"sid": solicitante_id}
    if tenant_id:
        q_params["tid"] = tenant_id

    filas = await todos(
        db,
        f"""
        SELECT tenant_id, scope
        FROM admin.access_grants
        WHERE staff_id = :sid
          AND revoked_at IS NULL
          AND expires_at > now()
          {cond_tenant}
        ORDER BY tenant_id ASC
        """,
        q_params,
    )
    permitidos_db: dict[str, bool] = {}
    for row in filas:
        sc = str(row.get("scope") or "")
        if sc in ("datos_negocio", "expediente", "contenido_codigo"):
            permitidos_db[str(row["tenant_id"])] = True
    if tenant_id and not permitidos_db.get(tenant_id):
        raise acceso_no_justificado(tenant_id=tenant_id, alcance="datos_negocio")
    if not permitidos_db:
        raise acceso_no_justificado(tenant_id=tenant_id, alcance="datos_negocio")
    return permitidos_db


async def _cargar_nombres_clientes(
    db: AsyncSession,
    tenant_ids: list[str],
    usa_sesion_externa: bool,
) -> dict[str, str]:
    """Resuelve razones sociales desde `admin.agg_customer_state` y RO."""
    if not tenant_ids:
        return {}
    nombres: dict[str, str] = {}
    filas_agg = await todos(
        db,
        """
        SELECT tenant_id, razon_social
        FROM admin.agg_customer_state
        WHERE tenant_id = ANY(:tids)
        ORDER BY tenant_id ASC
        """,
        {"tids": tenant_ids},
    )
    for row in filas_agg:
        if row.get("razon_social"):
            nombres[str(row["tenant_id"])] = str(row["razon_social"])

    faltantes = [tid for tid in tenant_ids if tid not in nombres]
    if not faltantes:
        return nombres

    sql_orgs = """
        SELECT id AS tenant_id, nombre AS razon_social
        FROM core.organizations
        WHERE id = ANY(:tids)
        ORDER BY id ASC
    """
    if usa_sesion_externa:
        try:
            filas_org = await todos(db, sql_orgs, {"tids": faltantes})
            for row in filas_org:
                if row.get("razon_social"):
                    nombres[str(row["tenant_id"])] = str(row["razon_social"])
        except Exception:
            pass
    faltantes = [tid for tid in tenant_ids if tid not in nombres]
    if faltantes:
        try:
            async with read_session() as ro_db:
                filas_ro = await todos(ro_db, sql_orgs, {"tids": faltantes})
                for row in filas_ro:
                    if row.get("razon_social"):
                        nombres[str(row["tenant_id"])] = str(row["razon_social"])
        except Exception:
            pass
    return nombres


async def _cargar_objetivos_plan(db: AsyncSession) -> dict[str, float]:
    filas = await todos(
        db,
        """
        SELECT plan_codigo, etapa, objetivo_h
        FROM admin.sla_targets
        WHERE activo = true AND etapa IN ('total_e2e', '*')
        ORDER BY plan_codigo ASC, (etapa = 'total_e2e') DESC, vigente_desde DESC
        """,
    )
    objetivos: dict[str, float] = {}
    for row in filas:
        plan = str(row["plan_codigo"])
        if plan not in objetivos and row.get("objetivo_h") is not None:
            objetivos[plan] = _round2(row["objetivo_h"])
    return objetivos


async def _cargar_frescura(db: AsyncSession) -> dict[str, Any]:
    filas = await todos(
        db,
        """
        SELECT agregado, status, refreshed_at, rows_total
        FROM admin.aggregate_state
        WHERE agregado IN ('sla_cases', 'agg_sla_compliance')
        ORDER BY agregado ASC
        """,
    )
    estado = "ok"
    ultimas: list[datetime] = []
    por_agregado: dict[str, Any] = {}
    for row in filas:
        agg = str(row["agregado"])
        st = str(row.get("status") or "pendiente")
        ref = row.get("refreshed_at")
        if st != "ok" and estado == "ok":
            estado = st
        if isinstance(ref, datetime):
            ultimas.append(ref)
        por_agregado[agg] = {
            "status": st,
            "refreshed_at": _iso_utc(ref),
            "rows_total": int(row["rows_total"]) if row.get("rows_total") is not None else 0,
        }
    ultima_dt = max(ultimas) if ultimas else None
    return {
        "estado": estado,
        "actualizado_en": _iso_utc(ultima_dt),
        "agregados": por_agregado,
    }


def _resolver_razon_social(
    tenant_id: str,
    nombre_real: str | None,
    *,
    incluir_identificables: bool,
    tenants_autorizados: dict[str, bool],
) -> str:
    base = nombre_real or tenant_id
    revelar = incluir_identificables and (
        tenants_autorizados.get("*") or tenants_autorizados.get(tenant_id, False)
    )
    if revelar:
        return base
    if nombre_real:
        return enmascarar_texto(nombre_real) or "••••"
    return enmascarar_texto(tenant_id) or "••••"


async def _compilar_en_sesion(
    db: AsyncSession,
    *,
    d_ini: date,
    d_fin: date,
    tenant_id: str | None,
    incluir_identificables: bool,
    solicitante: Staff | None,
    solicitante_id: str | None,
    solicitante_rol: str | None,
    report_id: str | None,
    emitido_en: datetime | str | None,
    concesion_validada: bool,
    usa_sesion_externa: bool,
) -> dict[str, Any]:
    tenants_autorizados: dict[str, bool] = {}
    if incluir_identificables:
        tenants_autorizados = await _verificar_autorizacion_identificables(
            db,
            tenant_id=tenant_id,
            solicitante=solicitante,
            solicitante_id=solicitante_id,
            concesion_validada=concesion_validada,
        )

    ciclo_desde = d_ini.strftime("%Y-%m")
    ciclo_hasta = d_fin.strftime("%Y-%m")
    dt_desde = datetime(d_ini.year, d_ini.month, d_ini.day, tzinfo=UTC)
    dt_hasta_excl = datetime(d_fin.year, d_fin.month, d_fin.day, tzinfo=UTC) + timedelta(days=1)

    cond_t_agg = "AND tenant_id = :tid" if tenant_id else ""
    params_agg: dict[str, Any] = {"c_ini": ciclo_desde, "c_fin": ciclo_hasta}
    if tenant_id:
        params_agg["tid"] = tenant_id

    filas_agg = await todos(
        db,
        f"""
        SELECT ciclo, tenant_id, plan_codigo, objetivo_h,
               casos_totales, casos_evaluados, casos_dentro,
               casos_incumplidos, casos_en_riesgo, casos_en_curso,
               casos_sin_objetivo, cumplimiento_pct,
               bruto_total_h, transcurrido_total_h, actualizado_en
        FROM admin.agg_sla_compliance
        WHERE ciclo >= :c_ini AND ciclo <= :c_fin
          {cond_t_agg}
        ORDER BY tenant_id ASC, ciclo ASC
        """,
        params_agg,
    )

    params_cases: dict[str, Any] = {"dt_ini": dt_desde, "dt_fin": dt_hasta_excl}
    if tenant_id:
        params_cases["tid"] = tenant_id

    filas_cases = await todos(
        db,
        f"""
        SELECT job_id, tenant_id, ticket_id, ticket_numero, plan_codigo,
               etapa_final, objetivo_h, bruto_h, transcurrido_h, resultado,
               tramos, reglas, iniciado_en, terminado_en, calculado_en
        FROM admin.sla_cases
        WHERE iniciado_en >= :dt_ini AND iniciado_en < :dt_fin
          {cond_t_agg}
        ORDER BY iniciado_en ASC, job_id ASC
        """,
        params_cases,
    )

    objetivos_plan = await _cargar_objetivos_plan(db)
    frescura = await _cargar_frescura(db)

    # Agrupación determinista por cliente usando agregados y respaldo en casos individuales
    por_cliente: dict[str, dict[str, Any]] = {}
    timestamps_cierre: list[datetime] = []

    for row in filas_agg:
        tid = str(row["tenant_id"])
        act = row.get("actualizado_en")
        if isinstance(act, datetime):
            timestamps_cierre.append(act)
        acc = por_cliente.setdefault(
            tid,
            {
                "tenant_id": tid,
                "plan_codigo": row.get("plan_codigo"),
                "objetivo_h": (
                    _round2(row["objetivo_h"]) if row.get("objetivo_h") is not None else None
                ),
                "casos_totales": 0,
                "casos_evaluados": 0,
                "casos_dentro": 0,
                "casos_incumplidos": 0,
                "casos_en_riesgo": 0,
                "casos_en_curso": 0,
                "casos_sin_objetivo": 0,
                "bruto_total_h": Decimal("0"),
                "transcurrido_total_h": Decimal("0"),
                "_desde_agg": True,
            },
        )
        if not acc.get("plan_codigo") and row.get("plan_codigo"):
            acc["plan_codigo"] = row["plan_codigo"]
        if acc.get("objetivo_h") is None and row.get("objetivo_h") is not None:
            acc["objetivo_h"] = _round2(row["objetivo_h"])
        acc["casos_totales"] += int(row.get("casos_totales") or 0)
        acc["casos_evaluados"] += int(row.get("casos_evaluados") or 0)
        acc["casos_dentro"] += int(row.get("casos_dentro") or 0)
        acc["casos_incumplidos"] += int(row.get("casos_incumplidos") or 0)
        acc["casos_en_riesgo"] += int(row.get("casos_en_riesgo") or 0)
        acc["casos_en_curso"] += int(row.get("casos_en_curso") or 0)
        acc["casos_sin_objetivo"] += int(row.get("casos_sin_objetivo") or 0)
        acc["bruto_total_h"] += Decimal(str(row.get("bruto_total_h") or 0))
        acc["transcurrido_total_h"] += Decimal(str(row.get("transcurrido_total_h") or 0))

    incidentes: list[dict[str, Any]] = []
    # Casos de clientes sin filas previas en `agg_sla_compliance` en el rango
    tenants_con_agg = set(por_cliente.keys())

    for c in filas_cases:
        tid = str(c["tenant_id"])
        calc = c.get("calculado_en")
        if isinstance(calc, datetime):
            timestamps_cierre.append(calc)

        if tid not in tenants_con_agg:
            acc = por_cliente.setdefault(
                tid,
                {
                    "tenant_id": tid,
                    "plan_codigo": c.get("plan_codigo"),
                    "objetivo_h": (
                        _round2(c["objetivo_h"]) if c.get("objetivo_h") is not None else None
                    ),
                    "casos_totales": 0,
                    "casos_evaluados": 0,
                    "casos_dentro": 0,
                    "casos_incumplidos": 0,
                    "casos_en_riesgo": 0,
                    "casos_en_curso": 0,
                    "casos_sin_objetivo": 0,
                    "bruto_total_h": Decimal("0"),
                    "transcurrido_total_h": Decimal("0"),
                    "_desde_agg": False,
                },
            )
            if not acc.get("plan_codigo") and c.get("plan_codigo"):
                acc["plan_codigo"] = c["plan_codigo"]
            if acc.get("objetivo_h") is None and c.get("objetivo_h") is not None:
                acc["objetivo_h"] = _round2(c["objetivo_h"])
            res = str(c.get("resultado") or "")
            acc["casos_totales"] += 1
            if res in ("dentro", "incumplido"):
                acc["casos_evaluados"] += 1
            if res == "dentro":
                acc["casos_dentro"] += 1
            elif res == "incumplido":
                acc["casos_incumplidos"] += 1
            elif res == "en_riesgo":
                acc["casos_en_riesgo"] += 1
            elif res == "en_curso":
                acc["casos_en_curso"] += 1
            elif res == "sin_objetivo":
                acc["casos_sin_objetivo"] += 1
            acc["bruto_total_h"] += Decimal(str(c.get("bruto_h") or 0))
            acc["transcurrido_total_h"] += Decimal(str(c.get("transcurrido_h") or 0))

        resultado = str(c.get("resultado") or "")
        if resultado in ("incumplido", "en_riesgo"):
            bruto = Decimal(str(c.get("bruto_h") or 0))
            trans = Decimal(str(c.get("transcurrido_h") or 0))
            pausa = max(Decimal("0"), bruto - trans)
            tramos = _extraer_tramos(c.get("tramos"))
            motivos = _motivos_pausa_caso(tramos)
            incidentes.append(
                {
                    "job_id": str(c["job_id"]),
                    "ticket_numero": str(c.get("ticket_numero") or c.get("ticket_id") or ""),
                    "tenant_id": tid,
                    "etapa_final": str(c.get("etapa_final") or ""),
                    "resultado": resultado,
                    "iniciado_en": _iso_utc(c.get("iniciado_en")),
                    "terminado_en": _iso_utc(c.get("terminado_en")),
                    "objetivo_h": (
                        _round2(c["objetivo_h"]) if c.get("objetivo_h") is not None else None
                    ),
                    "bruto_h": _round2(bruto),
                    "transcurrido_h": _round2(trans),
                    "pausa_total_h": _round2(pausa),
                    "motivos_pausa": motivos,
                }
            )

    tenant_ids_ordenados = sorted(por_cliente.keys())
    nombres_reales = await _cargar_nombres_clientes(
        db, tenant_ids_ordenados, usa_sesion_externa=usa_sesion_externa
    )

    desglose_clientes: list[dict[str, Any]] = []
    tot_casos = 0
    tot_evaluados = 0
    tot_dentro = 0
    tot_incumplidos = 0
    tot_en_riesgo = 0
    tot_en_curso = 0
    tot_sin_obj = 0
    tot_bruto_h = Decimal("0")
    tot_trans_h = Decimal("0")

    for tid in tenant_ids_ordenados:
        item = por_cliente[tid]
        plan = str(item.get("plan_codigo") or "starter")
        objetivo_h = item.get("objetivo_h")
        if objetivo_h is None:
            objetivo_h = objetivos_plan.get(plan)

        evaluados = int(item["casos_evaluados"])
        dentro = int(item["casos_dentro"])
        incumplidos = int(item["casos_incumplidos"])
        en_riesgo = int(item["casos_en_riesgo"])
        pct_str_o_num, _ = _pct_cumplimiento(dentro, evaluados)
        evaluados_visibles: int | str = evaluados if evaluados >= MUESTRA_MINIMA_SLA else "N/A"

        razon = _resolver_razon_social(
            tid,
            nombres_reales.get(tid),
            incluir_identificables=incluir_identificables,
            tenants_autorizados=tenants_autorizados,
        )

        desglose_clientes.append(
            {
                "tenant_id": tid,
                "razon_social": razon,
                "plan_codigo": plan,
                "objetivo_h": objetivo_h,
                "casos_totales": int(item["casos_totales"]),
                "casos_evaluados": evaluados,
                "casos_evaluados_muestra": evaluados_visibles,
                "casos_dentro": dentro,
                "casos_incumplidos": incumplidos,
                "casos_en_riesgo": en_riesgo,
                "cumplimiento_pct": pct_str_o_num,
                "bruto_total_h": _round2(item["bruto_total_h"]),
                "transcurrido_total_h": _round2(item["transcurrido_total_h"]),
            }
        )

        tot_casos += int(item["casos_totales"])
        tot_evaluados += evaluados
        tot_dentro += dentro
        tot_incumplidos += incumplidos
        tot_en_riesgo += en_riesgo
        tot_en_curso += int(item["casos_en_curso"])
        tot_sin_obj += int(item["casos_sin_objetivo"])
        tot_bruto_h += item["bruto_total_h"]
        tot_trans_h += item["transcurrido_total_h"]

    # Añadir razones sociales en incidentes también estrictamente enmascaradas o reveladas
    razones_por_tid = {c["tenant_id"]: c["razon_social"] for c in desglose_clientes}
    for inc in incidentes:
        inc["razon_social"] = razones_por_tid.get(inc["tenant_id"], "••••")

    global_pct, _ = _pct_cumplimiento(tot_dentro, tot_evaluados)
    tiempo_medio_computable_h: float | None = None
    if tot_casos > 0:
        tiempo_medio_computable_h = float(
            (tot_trans_h / Decimal(tot_casos)).quantize(_Q2, rounding=ROUND_HALF_UP)
        )

    # Fecha de emisión determinista (C1)
    if emitido_en is not None:
        fecha_emision = _iso_utc(emitido_en)
    elif timestamps_cierre:
        fecha_emision = _iso_utc(max(timestamps_cierre))
    else:
        fecha_emision = f"{d_fin.isoformat()}T23:59:59Z"

    sol_id = solicitante.id if solicitante is not None else (solicitante_id or "sistema")
    sol_rol = solicitante.role if solicitante is not None else (solicitante_rol or "sistema")

    cabecera = {
        "report_id": report_id or f"sla-{d_ini.isoformat()}-{d_fin.isoformat()}",
        "periodo": {"desde": d_ini.isoformat(), "hasta": d_fin.isoformat()},
        "tenant_id_filtro": tenant_id,
        "incluir_identificables": incluir_identificables,
        "fecha_emision": fecha_emision,
        "solicitante": {"staff_id": sol_id, "rol": sol_rol},
        "frescura": {
            "estado": frescura["estado"],
            "actualizado_en": fecha_emision,
        },
    }

    evaluados_muestra: int | str = (
        tot_evaluados if tot_evaluados >= MUESTRA_MINIMA_SLA else "N/A"
    )
    resumen_global = {
        "casos_totales": tot_casos,
        "casos_evaluados": tot_evaluados,
        "casos_evaluados_muestra": evaluados_muestra,
        "casos_dentro": tot_dentro,
        "casos_incumplidos": tot_incumplidos,
        "casos_en_riesgo": tot_en_riesgo,
        "casos_en_curso": tot_en_curso,
        "casos_sin_objetivo": tot_sin_obj,
        "cumplimiento_global_pct": global_pct,
        "tiempo_medio_computable_h": tiempo_medio_computable_h,
        "bruto_total_h": _round2(tot_bruto_h),
        "transcurrido_total_h": _round2(tot_trans_h),
    }

    return {
        "cabecera": cabecera,
        "resumen_global": resumen_global,
        "desglose_clientes": desglose_clientes,
        "casos_incidentes": incidentes,
    }


async def compilar_reporte_sla(
    db: AsyncSession | None = None,
    *,
    desde: date | str,
    hasta: date | str,
    tenant_id: str | None = None,
    incluir_identificables: bool = False,
    solicitante: Staff | None = None,
    solicitante_id: str | None = None,
    solicitante_rol: str | None = None,
    report_id: str | None = None,
    emitido_en: datetime | str | None = None,
    concesion_validada: bool = False,
) -> dict[str, Any]:
    """Compila el informe estructurado y determinista de cumplimiento de SLA."""
    d_ini, d_fin = validar_rango_sla(desde, hasta)
    if db is not None:
        return await _compilar_en_sesion(
            db,
            d_ini=d_ini,
            d_fin=d_fin,
            tenant_id=tenant_id,
            incluir_identificables=incluir_identificables,
            solicitante=solicitante,
            solicitante_id=solicitante_id,
            solicitante_rol=solicitante_rol,
            report_id=report_id,
            emitido_en=emitido_en,
            concesion_validada=concesion_validada,
            usa_sesion_externa=True,
        )

    async with read_session() as ro_db:
        return await _compilar_en_sesion(
            ro_db,
            d_ini=d_ini,
            d_fin=d_fin,
            tenant_id=tenant_id,
            incluir_identificables=incluir_identificables,
            solicitante=solicitante,
            solicitante_id=solicitante_id,
            solicitante_rol=solicitante_rol,
            report_id=report_id,
            emitido_en=emitido_en,
            concesion_validada=concesion_validada,
            usa_sesion_externa=False,
        )


def render_sla_json(reporte: dict[str, Any]) -> bytes:
    """Serializa el informe SLA en JSON canónico determinista UTF-8."""
    return json.dumps(reporte, sort_keys=True, ensure_ascii=False, indent=2).encode("utf-8")


def render_sla_csv(reporte: dict[str, Any]) -> bytes:
    """Serializa el informe SLA en CSV RFC 4180 determinista con CRLF."""
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\r\n", quoting=csv.QUOTE_MINIMAL)

    cab = reporte["cabecera"]
    res = reporte["resumen_global"]
    clientes = reporte["desglose_clientes"]
    incidentes = reporte["casos_incidentes"]

    # 1. Cabecera del documento
    writer.writerow(["SECCION", "CABECERA"])
    writer.writerow(
        [
            "report_id",
            "periodo_desde",
            "periodo_hasta",
            "fecha_emision",
            "solicitante_id",
            "solicitante_rol",
            "tenant_id_filtro",
            "incluir_identificables",
            "frescura_estado",
            "frescura_actualizado_en",
        ]
    )
    writer.writerow(
        [
            cab["report_id"],
            cab["periodo"]["desde"],
            cab["periodo"]["hasta"],
            cab["fecha_emision"] or "",
            cab["solicitante"]["staff_id"],
            cab["solicitante"]["rol"],
            cab["tenant_id_filtro"] or "TODOS",
            "true" if cab["incluir_identificables"] else "false",
            cab["frescura"]["estado"],
            cab["frescura"]["actualizado_en"] or "",
        ]
    )

    # 2. Resumen global
    writer.writerow([])
    writer.writerow(["SECCION", "RESUMEN_GLOBAL"])
    writer.writerow(
        [
            "casos_totales",
            "casos_evaluados",
            "cumplimiento_global_pct",
            "casos_dentro",
            "casos_incumplidos",
            "casos_en_riesgo",
            "tiempo_medio_computable_h",
            "bruto_total_h",
            "transcurrido_total_h",
        ]
    )
    writer.writerow(
        [
            res["casos_totales"],
            res["casos_evaluados"],
            res["cumplimiento_global_pct"],
            res["casos_dentro"],
            res["casos_incumplidos"],
            res["casos_en_riesgo"],
            (
                res["tiempo_medio_computable_h"]
                if res["tiempo_medio_computable_h"] is not None
                else "N/A"
            ),
            res["bruto_total_h"],
            res["transcurrido_total_h"],
        ]
    )

    # 3. Desglose por cliente
    writer.writerow([])
    writer.writerow(["SECCION", "DESGLOSE_CLIENTES"])
    writer.writerow(
        [
            "tenant_id",
            "razon_social",
            "plan_codigo",
            "objetivo_h",
            "casos_evaluados",
            "casos_evaluados_muestra",
            "cumplimiento_pct",
            "casos_dentro",
            "casos_incumplidos",
            "casos_en_riesgo",
        ]
    )
    for cli in clientes:
        writer.writerow(
            [
                cli["tenant_id"],
                cli["razon_social"],
                cli["plan_codigo"],
                cli["objetivo_h"] if cli["objetivo_h"] is not None else "",
                cli["casos_evaluados"],
                cli["casos_evaluados_muestra"],
                cli["cumplimiento_pct"],
                cli["casos_dentro"],
                cli["casos_incumplidos"],
                cli["casos_en_riesgo"],
            ]
        )

    # 4. Listado de casos incumplidos / incidentes
    writer.writerow([])
    writer.writerow(["SECCION", "CASOS_INCIDENTES"])
    writer.writerow(
        [
            "job_id",
            "ticket_numero",
            "tenant_id",
            "razon_social",
            "resultado",
            "inicio",
            "fin",
            "bruto_h",
            "transcurrido_h",
            "pausa_total_h",
            "motivos_pausa",
        ]
    )
    for inc in incidentes:
        writer.writerow(
            [
                inc["job_id"],
                inc["ticket_numero"],
                inc["tenant_id"],
                inc["razon_social"],
                inc["resultado"],
                inc["iniciado_en"] or "",
                inc["terminado_en"] or "",
                inc["bruto_h"],
                inc["transcurrido_h"],
                inc["pausa_total_h"],
                "|".join(inc["motivos_pausa"]),
            ]
        )

    return buf.getvalue().encode("utf-8")


def reporte_sla_a_tabla(reporte: dict[str, Any]) -> tuple[list[str], list[dict[str, Any]]]:
    """Proyecta el informe SLA compilado a formato tabular unificado para XLSX y PDF."""
    columnas = [
        "tenant_id",
        "razon_social",
        "plan_codigo",
        "objetivo_h",
        "casos_evaluados",
        "cumplimiento_pct",
        "casos_dentro",
        "casos_incumplidos",
        "casos_en_riesgo",
        "job_id",
        "ticket_numero",
        "bruto_h",
        "transcurrido_h",
        "pausa_total_h",
        "motivos_pausa",
    ]
    filas: list[dict[str, Any]] = []
    for cli in reporte["desglose_clientes"]:
        filas.append(
            {
                "tenant_id": cli["tenant_id"],
                "razon_social": cli["razon_social"],
                "plan_codigo": cli["plan_codigo"],
                "objetivo_h": cli["objetivo_h"],
                "casos_evaluados": cli["casos_evaluados_muestra"],
                "cumplimiento_pct": cli["cumplimiento_pct"],
                "casos_dentro": cli["casos_dentro"],
                "casos_incumplidos": cli["casos_incumplidos"],
                "casos_en_riesgo": cli["casos_en_riesgo"],
                "job_id": "",
                "ticket_numero": "",
                "bruto_h": cli["bruto_total_h"],
                "transcurrido_h": cli["transcurrido_total_h"],
                "pausa_total_h": _round2(cli["bruto_total_h"] - cli["transcurrido_total_h"]),
                "motivos_pausa": "",
            }
        )
    for inc in reporte["casos_incidentes"]:
        filas.append(
            {
                "tenant_id": inc["tenant_id"],
                "razon_social": inc["razon_social"],
                "plan_codigo": "",
                "objetivo_h": inc["objetivo_h"],
                "casos_evaluados": inc["resultado"],
                "cumplimiento_pct": "",
                "casos_dentro": 0,
                "casos_incumplidos": 1 if inc["resultado"] == "incumplido" else 0,
                "casos_en_riesgo": 1 if inc["resultado"] == "en_riesgo" else 0,
                "job_id": inc["job_id"],
                "ticket_numero": inc["ticket_numero"],
                "bruto_h": inc["bruto_h"],
                "transcurrido_h": inc["transcurrido_h"],
                "pausa_total_h": inc["pausa_total_h"],
                "motivos_pausa": ", ".join(inc["motivos_pausa"]),
            }
        )
    res = reporte["resumen_global"]
    filas.append(
        {
            "tenant_id": "TOTALES",
            "razon_social": "CONSOLIDADO",
            "plan_codigo": "TODOS",
            "objetivo_h": "",
            "casos_evaluados": res["casos_evaluados_muestra"],
            "cumplimiento_pct": res["cumplimiento_global_pct"],
            "casos_dentro": res["casos_dentro"],
            "casos_incumplidos": res["casos_incumplidos"],
            "casos_en_riesgo": res["casos_en_riesgo"],
            "job_id": f"{len(reporte['casos_incidentes'])} incidentes",
            "ticket_numero": "",
            "bruto_h": res["bruto_total_h"],
            "transcurrido_h": res["transcurrido_total_h"],
            "pausa_total_h": _round2(res["bruto_total_h"] - res["transcurrido_total_h"]),
            "motivos_pausa": "",
        }
    )
    return columnas, filas


async def exportar_reporte_sla(
    db: AsyncSession | None = None,
    *,
    desde: date | str,
    hasta: date | str,
    formato: str = "csv",
    tenant_id: str | None = None,
    incluir_identificables: bool = False,
    solicitante: Staff | None = None,
    solicitante_id: str | None = None,
    solicitante_rol: str | None = None,
    report_id: str | None = None,
    emitido_en: datetime | str | None = None,
    concesion_validada: bool = False,
    registrar_auditoria: bool = True,
    audit_db: AsyncSession | None = None,
    endpoint: str = "sla_exporter.exportar_reporte_sla",
) -> dict[str, Any]:
    """Compila, renderiza y firma con SHA-256 un informe exportable de SLA."""
    fmt = formato.lower().strip()
    if fmt not in FORMATOS_SLA:
        raise validacion(
            "Formato no admitido para exportación directa de SLA.",
            {"formato": formato, "admitidos": list(FORMATOS_SLA)},
        )

    reporte = await compilar_reporte_sla(
        db,
        desde=desde,
        hasta=hasta,
        tenant_id=tenant_id,
        incluir_identificables=incluir_identificables,
        solicitante=solicitante,
        solicitante_id=solicitante_id,
        solicitante_rol=solicitante_rol,
        report_id=report_id,
        emitido_en=emitido_en,
        concesion_validada=concesion_validada,
    )

    if fmt == "json":
        contenido = render_sla_json(reporte)
        content_type = "application/json; charset=utf-8"
    else:
        contenido = render_sla_csv(reporte)
        content_type = "text/csv; charset=utf-8"

    sha256 = hashlib.sha256(contenido).hexdigest()
    filas_total = len(reporte["desglose_clientes"]) + len(reporte["casos_incidentes"])

    sid = solicitante.id if solicitante is not None else solicitante_id
    rol_defecto = solicitante_rol or "staff_operaciones"
    srol = solicitante.role if solicitante is not None else rol_defecto
    if registrar_auditoria and sid:
        pl = {
            "report_id": reporte["cabecera"]["report_id"],
            "tipo": "sla",
            "formato": fmt,
            "rango": [
                reporte["cabecera"]["periodo"]["desde"],
                reporte["cabecera"]["periodo"]["hasta"],
            ],
            "identificables": incluir_identificables,
            "sha256": sha256,
            "filas": filas_total,
        }
        target_db = audit_db if audit_db is not None else db
        if target_db is not None:
            await registrar_accion(
                target_db,
                staff_id=sid,
                staff_role=srol,
                action="informe",
                resource="sla",
                endpoint=endpoint,
                tenant_id=tenant_id,
                ip=solicitante.ip if solicitante is not None else None,
                user_agent=solicitante.user_agent if solicitante is not None else None,
                request_id=solicitante.request_id if solicitante is not None else None,
                payload=pl,
            )
        else:
            async with admin_session() as adm_db:
                await registrar_accion(
                    adm_db,
                    staff_id=sid,
                    staff_role=srol,
                    action="informe",
                    resource="sla",
                    endpoint=endpoint,
                    tenant_id=tenant_id,
                    ip=solicitante.ip if solicitante is not None else None,
                    user_agent=solicitante.user_agent if solicitante is not None else None,
                    request_id=solicitante.request_id if solicitante is not None else None,
                    payload=pl,
                )

    return {
        "formato": fmt,
        "content_type": content_type,
        "contenido": contenido,
        "sha256": sha256,
        "filas_total": filas_total,
        "reporte": reporte,
    }
