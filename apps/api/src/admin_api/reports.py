"""Generador de Exportaciones e Informes de Negocio (§18.22 - §18.23).

Ticket [KC-ADM-B4-09]: Exportador CSV/PDF de Resumen de Clientes y Consumo.

Implementa:
  - Extracción y compilación de informes para tipos:
      * 'clientes': estado de organizaciones, plan, líneas contratadas, fechas,
        días para renovación y razón social (enmascarada por defecto).
      * 'consumo': métricas de inferencia por cliente y ciclo, segregación
        estricta del tier 'fable', información económica y fila final de totales consolidados.
      * 'suscripciones', 'sla', 'staff_actions': retrocompatibilidad completa.
  - Generación multi-formato sin dependencias externas pesadas:
      * CSV: cumplimiento estricto de RFC 4180 (terminador CRLF \\r\\n, escape y quoting).
      * XLSX: libro OpenXML estándar en memoria.
      * PDF: documento estructurado PDF 1.4 con cabeceras, tablas y totales auditables.
"""

from __future__ import annotations

import csv
import io
import xml.sax.saxutils as saxutils
import zipfile
from datetime import UTC, date, datetime, timedelta
from typing import Any

from kallicode_core.logging import log

from .db import read_session, todos
from .masking import enmascarar_texto

# Columnas identificables PII: se enmascaran por defecto si no se autoriza PII
_PII_COLUMNS = {"razon_social", "ticket_numero", "reason", "comentario"}


# ==============================================================================
# 1. Extracción y Compilación de Datos
# ==============================================================================


async def compilar_informe_clientes(
    params: dict[str, Any],
    includes_pii: bool,
    chunk_limit: int = 5000,
) -> tuple[list[str], list[dict[str, Any]]]:
    """Compila el informe de clientes con estado comercial y fechas de renovación."""
    d_raw = params.get("desde")
    h_raw = params.get("hasta")
    d_val: date | None = date.fromisoformat(str(d_raw)[:10]) if d_raw else None
    h_val: date | None = date.fromisoformat(str(h_raw)[:10]) if h_raw else None
    h_next = (h_val + timedelta(days=1)) if h_val else None

    filtro = "WHERE 1=1"
    query_params: dict[str, Any] = {"chunk": chunk_limit}

    if d_val and h_next:
        filtro += " AND c.alta_el >= :d AND c.alta_el < :h_next"
        query_params["d"] = d_val
        query_params["h_next"] = h_next

    if params.get("tenant_id"):
        filtro += " AND c.tenant_id = :t"
        query_params["t"] = params.get("tenant_id")

    sql = f"""
        SELECT
            c.tenant_id,
            c.razon_social,
            coalesce(c.plan_codigo, 'starter') AS plan,
            coalesce(c.plan_codigo, 'starter') AS plan_codigo,
            CASE
                WHEN c.suscripcion_estado = 'activa' THEN 'activo'
                WHEN c.suscripcion_estado = 'periodo_gracia' THEN 'moroso'
                WHEN c.suscripcion_estado = 'suspendida' THEN 'suspendido'
                WHEN c.suscripcion_estado = 'finalizada' THEN 'baja'
                ELSE coalesce(c.suscripcion_estado, 'activo')
            END AS estado,
            coalesce(c.suscripcion_estado, 'activa') AS suscripcion_estado,
            coalesce(c.lineas_contratadas, 1)::int AS lineas_contratadas,
            c.inicia_el::text AS inicia_el,
            c.renueva_el::text AS renueva_el,
            CASE
                WHEN c.renueva_el IS NOT NULL THEN (c.renueva_el - current_date)::int
                ELSE 0
            END AS dias_para_renovacion,
            c.alta_el::text AS alta_el,
            coalesce(c.lineas_activas, 0)::int AS lineas_activas,
            coalesce(c.usuarios_activos, 0)::int AS usuarios_activos,
            coalesce(c.tickets_abiertos, 0)::int AS tickets_abiertos
        FROM admin.agg_customer_state c
        {filtro}
        ORDER BY c.alta_el DESC, c.tenant_id ASC
        LIMIT :chunk
    """

    async with read_session() as db:
        filas = await todos(db, sql, query_params)

    # Aplicar enmascaramiento PII si no está explícitamente autorizado
    for f in filas:
        rs = f.get("razon_social") or f.get("tenant_id", "")
        if not includes_pii:
            f["razon_social"] = enmascarar_texto(rs)

    columnas = [
        "tenant_id",
        "razon_social",
        "plan",
        "estado",
        "lineas_contratadas",
        "inicia_el",
        "renueva_el",
        "dias_para_renovacion",
    ]
    return columnas, filas


async def compilar_informe_consumo(
    params: dict[str, Any],
    chunk_limit: int = 5000,
) -> tuple[list[str], list[dict[str, Any]]]:
    """Compila el informe de consumo de tokens con segregación de fable y fila de totales."""
    d_raw = params.get("desde")
    h_raw = params.get("hasta")
    d_val: date | None = date.fromisoformat(str(d_raw)[:10]) if d_raw else None
    h_val: date | None = date.fromisoformat(str(h_raw)[:10]) if h_raw else None
    h_next = (h_val + timedelta(days=1)) if h_val else None

    filtro = "WHERE 1=1"
    query_params: dict[str, Any] = {"chunk": chunk_limit}

    if d_val and h_next:
        filtro += (
            " AND to_date(u.ciclo || '-01', 'YYYY-MM-DD') >= :d "
            "AND to_date(u.ciclo || '-01', 'YYYY-MM-DD') < :h_next"
        )
        query_params["d"] = d_val
        query_params["h_next"] = h_next

    if params.get("tenant_id"):
        filtro += " AND u.tenant_id = :t"
        query_params["t"] = params.get("tenant_id")

    sql = f"""
        SELECT
            u.tenant_id,
            u.ciclo,
            u.loc_consumidas,
            coalesce(c.plan_codigo, 'starter') AS plan,
            u.tokens_in::bigint AS tokens_entrada,
            u.tokens_out::bigint AS tokens_salida,
            (u.tokens_in + u.tokens_out)::bigint AS tokens_total,
            u.tokens_flash::bigint AS tokens_flash,
            u.tokens_pro::bigint AS tokens_pro,
            u.tokens_fable::bigint AS tokens_fable,
            round(u.coste, 2)::float AS coste_estimado_eur,
            u.loc_consumidas AS loc_netas,
            coalesce(u.cuota_pct, 0.0)::float AS cuota_pct,
            bool_and(u.loc_consumidas = coalesce((
                SELECT uc.loc_consumidas FROM core.usage_cycles uc
                WHERE uc.tenant_id = u.tenant_id AND uc.ciclo = u.ciclo),
                u.loc_consumidas)) AS cuadra_con_facturacion
        FROM admin.agg_usage_cycle u
        LEFT JOIN admin.agg_customer_state c ON c.tenant_id = u.tenant_id
        {filtro}
        GROUP BY u.tenant_id, u.ciclo, u.loc_consumidas, c.plan_codigo,
                 u.tokens_in, u.tokens_out, u.tokens_flash, u.tokens_pro,
                 u.tokens_fable, u.coste, u.cuota_pct
        ORDER BY u.ciclo DESC, u.tenant_id ASC
        LIMIT :chunk
    """

    async with read_session() as db:
        filas = await todos(db, sql, query_params)

    # Columnas canónicas requeridas (§18.21 / §18.22 / B4-09)
    # Conserva loc_consumidas al inicio para compatibilidad con suites previas
    columnas = [
        "tenant_id",
        "ciclo",
        "loc_consumidas",
        "plan",
        "tokens_entrada",
        "tokens_salida",
        "tokens_total",
        "tokens_flash",
        "tokens_pro",
        "tokens_fable",
        "coste_estimado_eur",
        "loc_netas",
        "cuota_pct",
        "cuadra_con_facturacion",
    ]

    # Calcular y añadir la fila final de totales consolidados para auditoría contable
    if filas:
        total_in = sum(int(f.get("tokens_entrada") or 0) for f in filas)
        total_out = sum(int(f.get("tokens_salida") or 0) for f in filas)
        total_tok = sum(int(f.get("tokens_total") or 0) for f in filas)
        total_flash = sum(int(f.get("tokens_flash") or 0) for f in filas)
        total_pro = sum(int(f.get("tokens_pro") or 0) for f in filas)
        total_fable = sum(int(f.get("tokens_fable") or 0) for f in filas)
        total_coste = round(sum(float(f.get("coste_estimado_eur") or 0.0) for f in filas), 2)
        total_loc = sum(int(f.get("loc_netas") or 0) for f in filas)
        media_cuota = round(
            sum(float(f.get("cuota_pct") or 0.0) for f in filas) / len(filas), 2
        )
        todos_cuadran = all(bool(f.get("cuadra_con_facturacion")) for f in filas)

        fila_totales: dict[str, Any] = {
            "tenant_id": "TOTALES",
            "ciclo": "CONSOLIDADO",
            "loc_consumidas": total_loc,
            "plan": "TODOS",
            "tokens_entrada": total_in,
            "tokens_salida": total_out,
            "tokens_total": total_tok,
            "tokens_flash": total_flash,
            "tokens_pro": total_pro,
            "tokens_fable": total_fable,
            "coste_estimado_eur": total_coste,
            "loc_netas": total_loc,
            "cuota_pct": media_cuota,
            "cuadra_con_facturacion": todos_cuadran,
        }
        filas.append(fila_totales)

    return columnas, filas


async def compilar_informe_generico(
    kind: str,
    params: dict[str, Any],
    includes_pii: bool,
    chunk_limit: int = 5000,
) -> tuple[list[str], list[dict[str, Any]]]:
    """Compila informes complementarios (suscripciones, sla, staff_actions)."""
    tablas_cols = {
        "suscripciones": (
            "tenant_id, razon_social, plan_codigo, suscripcion_estado, inicia_el, "
            "renueva_el, finaliza_el, importe_mes, moneda",
            "admin.agg_customer_state",
            "coalesce(inicia_el, alta_el::date)",
        ),
        "sla": (
            "tenant_id, ticket_numero, plan_codigo, objetivo_h, transcurrido_h, "
            "bruto_h, resultado, iniciado_en, terminado_en",
            "admin.sla_cases",
            "iniciado_en",
        ),
        "staff_actions": (
            "occurred_at, staff_id, staff_role, action, tenant_id, "
            "scope, reason, resource, endpoint, seal",
            "admin.staff_actions",
            "occurred_at",
        ),
    }

    if kind not in tablas_cols:
        raise ValueError(f"Tipo de informe no soportado: {kind}")

    cols_str, tabla, campo_fecha = tablas_cols[kind]
    cols = [c.strip() for c in cols_str.split(",")]
    if not includes_pii:
        cols = [c for c in cols if c not in _PII_COLUMNS]

    d_raw = params.get("desde")
    h_raw = params.get("hasta")
    d_val: date | None = date.fromisoformat(str(d_raw)[:10]) if d_raw else None
    h_val: date | None = date.fromisoformat(str(h_raw)[:10]) if h_raw else None
    h_next = (h_val + timedelta(days=1)) if h_val else None

    filtro = f"WHERE {campo_fecha} >= :d AND {campo_fecha} < :h_next"
    query_params: dict[str, Any] = {"d": d_val, "h_next": h_next, "chunk": chunk_limit}

    if params.get("tenant_id"):
        filtro += " AND tenant_id = :t"
        query_params["t"] = params.get("tenant_id")

    sql = f"SELECT {', '.join(cols)} FROM {tabla} {filtro} ORDER BY 1 LIMIT :chunk"

    async with read_session() as db:
        filas = await todos(db, sql, query_params)

    return cols, filas


# ==============================================================================
# 2. Formateadores: CSV (RFC 4180), XLSX, PDF 1.4
# ==============================================================================


def exportar_csv(columnas: list[str], filas: list[dict[str, Any]]) -> bytes:
    """Genera un archivo CSV con estricto apego al estándar RFC 4180 (CRLF, quotes)."""
    buf = io.StringIO()
    writer = csv.DictWriter(
        buf,
        fieldnames=columnas,
        extrasaction="ignore",
        lineterminator="\r\n",
        quoting=csv.QUOTE_MINIMAL,
    )
    writer.writeheader()
    for f in filas:
        writer.writerow({k: f.get(k) for k in columnas})
    return buf.getvalue().encode("utf-8")


def exportar_xlsx(
    columnas: list[str], filas: list[dict[str, Any]], titulo: str = "Informe"
) -> bytes:
    """Construye un libro de cálculo XLSX estándar en memoria sin librerías externas."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        content_types = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">\n'
            '  <Default Extension="rels" '
            'ContentType="application/vnd.openxmlformats-package.relationships+xml"/>\n'
            '  <Default Extension="xml" ContentType="application/xml"/>\n'
            '  <Override PartName="/xl/workbook.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>\n'
            '  <Override PartName="/xl/worksheets/sheet1.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>\n'
            "</Types>"
        )
        z.writestr("[Content_Types].xml", content_types)
        rels = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">\n'
            '  <Relationship Id="rId1" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/'
            'relationships/officeDocument" '
            'Target="xl/workbook.xml"/>\n'
            "</Relationships>"
        )
        z.writestr("_rels/.rels", rels)
        z.writestr(
            "xl/workbook.xml",
            f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <sheets>
    <sheet name="{saxutils.escape(titulo[:31])}" sheetId="1" r:id="rId1"/>
  </sheets>
</workbook>""",
        )
        wb_rels = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">\n'
            '  <Relationship Id="rId1" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/'
            'relationships/worksheet" '
            'Target="worksheets/sheet1.xml"/>\n'
            "</Relationships>"
        )
        z.writestr("xl/_rels/workbook.xml.rels", wb_rels)

        sheet_rows: list[str] = []
        header_cells = "".join(
            f"""<c t="inlineStr"><is><t>{saxutils.escape(h)}</t></is></c>""" for h in columnas
        )
        sheet_rows.append(f"""<row r="1">{header_cells}</row>""")
        for r_idx, row in enumerate(filas, start=2):
            cells = []
            for col in columnas:
                raw_val = row.get(col)
                val_str = str(raw_val) if raw_val is not None else ""
                cells.append(
                    f"""<c t="inlineStr"><is><t>{saxutils.escape(val_str)}</t></is></c>"""
                )
            sheet_rows.append(f"""<row r="{r_idx}">{"".join(cells)}</row>""")

        sheet_xml = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <sheetData>
    {"".join(sheet_rows)}
  </sheetData>
</worksheet>"""
        z.writestr("xl/worksheets/sheet1.xml", sheet_xml)
    return buf.getvalue()


def exportar_pdf(
    columnas: list[str], filas: list[dict[str, Any]], titulo: str = "Informe de Negocio"
) -> bytes:
    """Construye un documento PDF 1.4 estructurado en memoria sin dependencias externas.

    Genera páginas en orientación apaisada (Landscape A4: 842x595 pt) con cabeceras,
    rejilla de datos y resaltado especial de la fila de totales.
    """

    def _sanear(texto: str) -> str:
        return (
            texto.replace("\\", "\\\\")
            .replace("(", "\\(")
            .replace(")", "\\)")
            .encode("latin-1", "replace")
            .decode("latin-1")
        )

    ahora_str = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S UTC")
    filas_por_pagina = 22
    chunks_filas = (
        [filas[i : i + filas_por_pagina] for i in range(0, len(filas), filas_por_pagina)]
        if filas
        else [[]]
    )
    num_pages = len(chunks_filas)

    margen_x = 40.0
    ancho_util = 842.0 - (margen_x * 2)
    num_cols = max(len(columnas), 1)
    ancho_col = ancho_util / num_cols

    catalog_obj = b"<< /Type /Catalog /Pages 2 0 R >>"
    f1_obj = b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"
    f2_obj = b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold >>"

    pages_kids_refs = []
    page_records = []
    for i in range(num_pages):
        page_id = 5 + (i * 2)
        content_id = page_id + 1
        pages_kids_refs.append(f"{page_id} 0 R")
        page_records.append((page_id, content_id))

    pages_str = f"<< /Type /Pages /Kids [{' '.join(pages_kids_refs)}] /Count {num_pages} >>"
    pages_obj = pages_str.encode("ascii")

    pdf_parts: list[bytes] = [catalog_obj, pages_obj, f1_obj, f2_obj]

    for i, (_p_id, c_id) in enumerate(page_records):
        page_obj_str = (
            f"<< /Type /Page /Parent 2 0 R "
            f"/Resources << /Font << /F1 3 0 R /F2 4 0 R >> >> "
            f"/MediaBox [0 0 842 595] /Contents {c_id} 0 R >>"
        )
        pdf_parts.append(page_obj_str.encode("ascii"))

        chunk_lines = chunks_filas[i]
        s_lines: list[str] = [
            f"BT /F2 16 Tf 40 560 Td ({_sanear(titulo)}) Tj",
            (
                f"/F1 8 Tf 0 -15 Td (Generado: {_sanear(ahora_str)} | "
                f"KalliCode Admin | Pagina {i + 1} de {num_pages}) Tj ET"
            ),
            "0.90 0.90 0.92 rg 40 507 762 18 re f 0 g",
            "0.70 0.70 0.75 RG 1 w 40 507 762 18 re S",
            "BT /F2 8 Tf",
        ]
        for idx, col in enumerate(columnas):
            x = margen_x + (idx * ancho_col) + 4
            txt_col = _sanear(col.replace("_", " ").title()[:18])
            s_lines.append(f"1 0 0 1 {x:.1f} 513.0 Tm ({txt_col}) Tj")
        s_lines.append("ET")

        y_c = 507.0
        for r in chunk_lines:
            es_tot = str(r.get("tenant_id")) == "TOTALES"
            y_c -= 18.0
            if es_tot:
                s_lines.append(f"0.98 0.96 0.88 rg 40 {y_c:.1f} 762 18.0 re f 0 g")
                s_lines.append(
                    f"0.20 0.20 0.20 RG 1.5 w 40 {y_c + 18.0:.1f} m 802 {y_c + 18.0:.1f} l S"
                )
                s_lines.append("BT /F2 8 Tf")
            else:
                s_lines.append(f"0.90 0.90 0.90 RG 0.5 w 40 {y_c:.1f} m 802 {y_c:.1f} l S")
                s_lines.append("BT /F1 7.5 Tf")

            for idx, col in enumerate(columnas):
                x = margen_x + (idx * ancho_col) + 4
                raw_val = r.get(col)
                val_str = str(raw_val) if raw_val is not None else ""
                val_fmt = _sanear(val_str[:22])
                s_lines.append(f"1 0 0 1 {x:.1f} {y_c + 5.0:.1f} Tm ({val_fmt}) Tj")
            s_lines.append("ET")

        pie_txt = _sanear("Documento auditable generado por Consola KalliCode")
        s_lines.append(f"BT /F1 7 Tf 40 20 Td ({pie_txt}) Tj ET")
        c_bytes = "\n".join(s_lines).encode("latin-1")
        stream_obj = (
            f"<< /Length {len(c_bytes)} >>\nstream\n".encode("ascii") + c_bytes + b"\nendstream"
        )
        pdf_parts.append(stream_obj)

    out = io.BytesIO()
    out.write(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")

    offsets = [0]
    for idx, part in enumerate(pdf_parts, start=1):
        offsets.append(out.tell())
        out.write(f"{idx} 0 obj\n".encode("ascii"))
        out.write(part)
        out.write(b"\nendobj\n")

    startxref = out.tell()
    total_objs = len(pdf_parts) + 1
    out.write(f"xref\n0 {total_objs}\n".encode("ascii"))
    out.write(b"0000000000 65535 f \n")
    for off in offsets[1:]:
        out.write(f"{off:010d} 00000 n \n".encode("ascii"))

    trailer_str = (
        f"trailer\n<< /Size {total_objs} /Root 1 0 R >>\n" f"startxref\n{startxref}\n%%EOF\n"
    )
    out.write(trailer_str.encode("ascii"))
    return out.getvalue()


# ==============================================================================
# 3. Orquestador Unificado de Generación
# ==============================================================================


async def generar_contenido_informe(
    kind: str,
    formato: str,
    params: dict[str, Any],
    includes_pii: bool,
) -> tuple[bytes, str, int]:
    """Orquesta la compilación y serialización del informe según tipo y formato.

    Devuelve (datos_binarios, content_type, numero_de_filas).
    """
    formato_norm = formato.lower().strip()
    if formato_norm not in ("csv", "xlsx", "pdf"):
        raise ValueError(f"Formato no soportado: {formato}")

    if kind == "sla":
        from .sla_exporter import (
            compilar_reporte_sla,
            render_sla_csv,
            reporte_sla_a_tabla,
        )

        hoy = date.today()
        d_param = params.get("desde") or hoy.replace(day=1).isoformat()
        h_param = params.get("hasta") or hoy.isoformat()
        reporte_sla = await compilar_reporte_sla(
            desde=str(d_param),
            hasta=str(h_param),
            tenant_id=params.get("tenant_id"),
            incluir_identificables=includes_pii,
            solicitante_id=params.get("solicitante_id"),
            solicitante_rol=params.get("solicitante_rol"),
            report_id=params.get("report_id"),
            emitido_en=params.get("emitido_en"),
            concesion_validada=True,
        )
        titulo = "Cumplimiento de SLA por Cliente y Periodo"
        if formato_norm == "csv":
            datos = render_sla_csv(reporte_sla)
            content_type = "text/csv; charset=utf-8"
        else:
            columnas, filas = reporte_sla_a_tabla(reporte_sla)
            if formato_norm == "xlsx":
                datos = exportar_xlsx(columnas, filas, titulo=titulo)
                content_type = (
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                )
            else:
                datos = exportar_pdf(columnas, filas, titulo=titulo)
                content_type = "application/pdf"
        num_filas_reales = len(reporte_sla["desglose_clientes"]) + len(
            reporte_sla["casos_incidentes"]
        )
        log.info(
            "admin.reports.generado",
            tipo=kind,
            formato=formato_norm,
            filas=num_filas_reales,
            bytes=len(datos),
        )
        return datos, content_type, num_filas_reales

    if kind == "clientes":
        columnas, filas = await compilar_informe_clientes(params, includes_pii)
        titulo = "Resumen de Clientes"
    elif kind == "consumo":
        columnas, filas = await compilar_informe_consumo(params)
        titulo = "Consumo de Tokens por Cliente"
    else:
        columnas, filas = await compilar_informe_generico(kind, params, includes_pii)
        titulo = f"Informe de {kind.replace('_', ' ').title()}"

    if formato_norm == "xlsx":
        datos = exportar_xlsx(columnas, filas, titulo=titulo)
        content_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    elif formato_norm == "pdf":
        datos = exportar_pdf(columnas, filas, titulo=titulo)
        content_type = "application/pdf"
    else:
        datos = exportar_csv(columnas, filas)
        content_type = "text/csv; charset=utf-8"

    # Si hay fila de totales en consumo, no inflar el conteo de filas de datos reales
    num_filas_reales = len(filas)
    if kind == "consumo" and filas and filas[-1].get("tenant_id") == "TOTALES":
        num_filas_reales = max(0, len(filas) - 1)

    log.info(
        "admin.reports.generado",
        tipo=kind,
        formato=formato_norm,
        filas=num_filas_reales,
        bytes=len(datos),
    )
    return datos, content_type, num_filas_reales
