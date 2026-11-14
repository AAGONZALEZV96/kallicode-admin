"""Pruebas de integración del Informe Exportable de Cumplimiento de SLA (§18.22 / ADM-G07).

Ticket [KC-ADM-B5-11]:
  1. Determinismo criptográfico y reproducibilidad SHA-256 (CSV RFC 4180 y JSON).
  2. Regla de muestra mínima (< 5 casos evaluados -> "N/A").
  3. Validación de rango temporal máximo (24 meses) y fechas invertidas (422).
  4. Desglose completo de cabecera, resumen global, clientes e incidentes con pausas.
  5. Enmascaramiento por defecto y revelación controlada bajo concesión (ADM-G09).
  6. Integración E2E API (`/admin/v1/business/reports`, RBAC `staff_operaciones` para
     `tipo="sla"`) + worker `generar_informes` + descarga verificada + auditoría inmutable.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

import pytest
import pytest_asyncio
from admin_api.reports import generar_contenido_informe
from admin_api.sla_exporter import exportar_reporte_sla, validar_rango_sla
from admin_workers.main import generar_informes
from kallicode_core.errors import AppError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

pytestmark = pytest.mark.integracion

_PREFIJO = "b511"


def _async_dsn(dsn_url: str) -> str:
    if dsn_url.startswith("postgresql+asyncpg://"):
        return dsn_url
    return dsn_url.replace("postgresql://", "postgresql+asyncpg://", 1)


@pytest_asyncio.fixture
async def datos_sla_export(dsn: str, dos_clientes: list[str]) -> AsyncIterator[AsyncSession]:
    """Siembra casos y agregados SLA de un periodo cerrado y limpia al terminar."""
    engine = create_async_engine(_async_dsn(dsn), poolclass=NullPool)
    async with AsyncSession(engine) as session:
        await session.execute(
            text(
                "UPDATE admin.access_grants "
                "SET revoked_at = COALESCE(revoked_at, now()), "
                "    revoked_by = COALESCE(revoked_by, 'st_prueba'), "
                "    revoked_reason = COALESCE(revoked_reason, 'Aislamiento B5-11') "
                "WHERE staff_id = 'st_prueba' AND revoked_at IS NULL"
            )
        )
        await session.execute(
            text(
                "UPDATE core.organizations SET nombre = 'Acme Logística S.L.' "
                "WHERE id = 'org_acme'"
            )
        )
        await session.execute(
            text(
                "UPDATE core.organizations SET nombre = 'Globex Industrial S.A.' "
                "WHERE id = 'org_globex'"
            )
        )
        await session.execute(
            text(
                """
                INSERT INTO admin.agg_customer_state (
                    tenant_id, razon_social, plan_codigo, suscripcion_estado,
                    inicia_el, renueva_el, lineas_contratadas, lineas_activas,
                    usuarios_activos, tickets_abiertos, importe_mes, moneda,
                    alta_el, actualizado_en
                )
                VALUES
                    ('org_acme', 'Acme Logística S.L.', 'growth', 'activa',
                     DATE '2025-01-01', DATE '2026-06-01', 3, 2, 12, 1, 299.00, 'EUR',
                     TIMESTAMPTZ '2025-01-01T00:00:00Z', TIMESTAMPTZ '2025-12-31T23:00:00Z'),
                    ('org_globex', 'Globex Industrial S.A.', 'starter', 'activa',
                     DATE '2025-02-01', DATE '2026-06-01', 1, 1, 5, 0, 99.00, 'EUR',
                     TIMESTAMPTZ '2025-02-01T00:00:00Z', TIMESTAMPTZ '2025-12-31T23:00:00Z')
                ON CONFLICT (tenant_id) DO UPDATE
                    SET razon_social = EXCLUDED.razon_social,
                        plan_codigo = EXCLUDED.plan_codigo
                """
            )
        )
        await session.execute(
            text(
                """
                INSERT INTO admin.sla_targets
                    (plan_codigo, etapa, objetivo_h, riesgo_pct, vigente_desde, activo)
                VALUES
                    ('starter',    'total_e2e', 72.00, 80.00, DATE '2025-01-01', true),
                    ('growth',     'total_e2e', 24.00, 80.00, DATE '2025-01-01', true),
                    ('enterprise', 'total_e2e',  8.00, 80.00, DATE '2025-01-01', true)
                ON CONFLICT (plan_codigo, etapa) DO UPDATE
                    SET objetivo_h = EXCLUDED.objetivo_h, activo = true
                """
            )
        )
        # org_acme: 6 casos evaluados (>= 5): 5 dentro, 1 incumplido => 83.33%
        await session.execute(
            text(
                """
                INSERT INTO admin.agg_sla_compliance (
                    ciclo, tenant_id, plan_codigo, objetivo_h,
                    casos_totales, casos_evaluados, casos_dentro,
                    casos_incumplidos, casos_en_riesgo, casos_en_curso,
                    casos_sin_objetivo, cumplimiento_pct,
                    bruto_total_h, transcurrido_total_h, actualizado_en
                )
                VALUES
                    ('2025-11', 'org_acme', 'growth', 24.00,
                     4, 4, 4, 0, 0, 0, 0, 100.00,
                     60.00, 50.00, TIMESTAMPTZ '2025-12-01T01:00:00Z'),
                    ('2025-12', 'org_acme', 'growth', 24.00,
                     2, 2, 1, 1, 0, 0, 0, 50.00,
                     48.00, 39.00, TIMESTAMPTZ '2025-12-31T23:50:00Z'),
                    ('2025-12', 'org_globex', 'starter', 72.00,
                     3, 3, 2, 1, 0, 0, 0, 66.67,
                     202.50, 174.00, TIMESTAMPTZ '2025-12-31T23:50:00Z'),
                    ('2026-02', 'org_acme', 'growth', 24.00,
                     2, 2, 2, 0, 0, 0, 0, 100.00,
                     20.00, 18.00, TIMESTAMPTZ '2026-02-28T12:00:00Z')
                ON CONFLICT (ciclo, tenant_id) DO UPDATE
                    SET casos_totales = EXCLUDED.casos_totales,
                        casos_evaluados = EXCLUDED.casos_evaluados,
                        casos_dentro = EXCLUDED.casos_dentro,
                        casos_incumplidos = EXCLUDED.casos_incumplidos,
                        casos_en_riesgo = EXCLUDED.casos_en_riesgo,
                        cumplimiento_pct = EXCLUDED.cumplimiento_pct,
                        bruto_total_h = EXCLUDED.bruto_total_h,
                        transcurrido_total_h = EXCLUDED.transcurrido_total_h,
                        actualizado_en = EXCLUDED.actualizado_en
                """
            )
        )

        tramos_globex = json.dumps(
            [
                {
                    "inicio": "2025-12-10T08:00:00Z",
                    "fin": "2025-12-12T10:00:00Z",
                    "etapa": "build",
                    "computa": True,
                    "causa_pausa": None,
                    "horas": 50.0,
                },
                {
                    "inicio": "2025-12-12T10:00:00Z",
                    "fin": "2025-12-12T15:30:00Z",
                    "etapa": "pausa",
                    "computa": False,
                    "causa_pausa": "espera_firma_cliente",
                    "horas": 5.5,
                },
                {
                    "inicio": "2025-12-12T15:30:00Z",
                    "fin": "2025-12-12T18:30:00Z",
                    "etapa": "mantenimiento",
                    "computa": False,
                    "causa_pausa": "ventana_mantenimiento",
                    "horas": 3.0,
                },
                {
                    "inicio": "2025-12-12T18:30:00Z",
                    "fin": "2025-12-13T18:30:00Z",
                    "etapa": "qa",
                    "computa": True,
                    "causa_pausa": None,
                    "horas": 24.0,
                },
            ]
        )
        tramos_acme = json.dumps(
            [
                {
                    "inicio": "2025-12-20T09:00:00Z",
                    "fin": "2025-12-21T11:00:00Z",
                    "etapa": "design",
                    "computa": True,
                    "causa_pausa": None,
                    "horas": 26.0,
                },
                {
                    "inicio": "2025-12-21T11:00:00Z",
                    "fin": "2025-12-21T15:00:00Z",
                    "etapa": "escalado",
                    "computa": False,
                    "causa_pausa": "escalado_humano",
                    "horas": 4.0,
                },
            ]
        )

        await session.execute(
            text(
                """
                INSERT INTO admin.sla_cases (
                    job_id, tenant_id, ticket_id, ticket_numero, plan_codigo,
                    etapa_final, objetivo_h, bruto_h, transcurrido_h, resultado,
                    tramos, reglas, iniciado_en, terminado_en, calculado_en
                )
                VALUES
                    ('job_b511_acme_1', 'org_acme', 'tk_b511_1', 'KC-4010', 'growth',
                     'qa', 24.00, 30.00, 26.00, 'incumplido',
                     CAST(:tr_a AS jsonb), ARRAY['escalado_humano'],
                     TIMESTAMPTZ '2025-12-20T09:00:00Z',
                     TIMESTAMPTZ '2025-12-21T15:00:00Z',
                     TIMESTAMPTZ '2025-12-31T23:50:00Z'),
                    ('job_b511_globex_1', 'org_globex', 'tk_b511_2', 'KC-4011', 'starter',
                     'deploy', 72.00, 82.50, 74.00, 'incumplido',
                     CAST(:tr_g AS jsonb),
                     ARRAY['espera_firma_cliente', 'ventana_mantenimiento'],
                     TIMESTAMPTZ '2025-12-10T08:00:00Z',
                     TIMESTAMPTZ '2025-12-13T18:30:00Z',
                     TIMESTAMPTZ '2025-12-31T23:50:00Z'),
                    ('job_b511_acme_fuera', 'org_acme', 'tk_b511_3', 'KC-4099', 'growth',
                     'deploy', 24.00, 10.00, 10.00, 'dentro',
                     '[]'::jsonb, ARRAY[]::text[],
                     TIMESTAMPTZ '2026-02-10T08:00:00Z',
                     TIMESTAMPTZ '2026-02-10T18:00:00Z',
                     TIMESTAMPTZ '2026-02-28T12:00:00Z')
                ON CONFLICT (job_id) DO UPDATE
                    SET resultado = EXCLUDED.resultado,
                        bruto_h = EXCLUDED.bruto_h,
                        transcurrido_h = EXCLUDED.transcurrido_h,
                        tramos = EXCLUDED.tramos
                """
            ),
            {"tr_a": tramos_acme, "tr_g": tramos_globex},
        )
        await session.execute(
            text(
                """
                UPDATE admin.aggregate_state
                SET status = 'ok', refreshed_at = now(), error = NULL
                WHERE agregado IN ('sla_cases', 'agg_sla_compliance')
                """
            )
        )
        await session.commit()

        try:
            yield session
        finally:
            await session.rollback()
            await session.execute(
                text(
                    "UPDATE admin.access_grants SET revoked_at = COALESCE(revoked_at, now()), "
                    "revoked_by = COALESCE(revoked_by, 'st_prueba'), "
                    "revoked_reason = COALESCE(revoked_reason, 'Limpieza B5-11') "
                    f"WHERE id LIKE 'gr_{_PREFIJO}%'"
                )
            )
            await session.execute(
                text("DELETE FROM admin.sla_cases WHERE job_id LIKE 'job_b511_%'")
            )
            await session.execute(
                text(
                    "DELETE FROM admin.agg_sla_compliance "
                    "WHERE ciclo IN ('2025-11', '2025-12', '2026-02') "
                    "AND tenant_id IN ('org_acme', 'org_globex')"
                )
            )
            await session.commit()

    await engine.dispose()


async def test_validacion_rango_24_meses_y_fechas_invertidas(
    cliente: Any, como: Any, sin_limite: None
) -> None:
    """Valida el límite de 24 meses y el rechazo de fechas invertidas."""
    d_ini, d_fin = validar_rango_sla("2024-01-01", "2026-01-01")
    assert d_ini.isoformat() == "2024-01-01"
    assert d_fin.isoformat() == "2026-01-01"

    with pytest.raises(AppError) as exc_24:
        validar_rango_sla("2024-01-01", "2026-01-02")
    assert exc_24.value.http == 422

    with pytest.raises(AppError) as exc_inv:
        validar_rango_sla("2026-03-10", "2026-03-01")
    assert exc_inv.value.http == 422

    como("staff_operaciones", staff_id="st_prueba")
    resp = await cliente.post(
        "/admin/v1/business/reports",
        json={
            "tipo": "sla",
            "desde": "2024-01-01",
            "hasta": "2026-01-02",
            "formato": "csv",
        },
    )
    assert resp.status_code == 422


async def test_determinismo_criptografico_sha256_csv_y_json(
    datos_sla_export: AsyncSession,
) -> None:
    """Dos exportaciones sobre el mismo periodo cerrado generan idénticos bytes y SHA-256."""
    r1_csv = await exportar_reporte_sla(
        datos_sla_export,
        desde="2025-11-01",
        hasta="2025-12-31",
        formato="csv",
        solicitante_id="st_prueba",
        solicitante_rol="staff_operaciones",
        registrar_auditoria=False,
    )
    # Simular que un worker refresca globalmente en otro instante sin tocar el periodo cerrado
    await datos_sla_export.execute(
        text(
            "UPDATE admin.aggregate_state SET refreshed_at = now() + interval '2 minutes' "
            "WHERE agregado IN ('sla_cases', 'agg_sla_compliance')"
        )
    )
    await datos_sla_export.commit()

    r2_csv = await exportar_reporte_sla(
        datos_sla_export,
        desde="2025-11-01",
        hasta="2025-12-31",
        formato="csv",
        solicitante_id="st_prueba",
        solicitante_rol="staff_operaciones",
        registrar_auditoria=False,
    )
    assert r1_csv["contenido"] == r2_csv["contenido"]
    assert r1_csv["sha256"] == r2_csv["sha256"]
    assert r1_csv["sha256"] == hashlib.sha256(r1_csv["contenido"]).hexdigest()

    r1_json = await exportar_reporte_sla(
        datos_sla_export,
        desde="2025-11-01",
        hasta="2025-12-31",
        formato="json",
        tenant_id="org_acme",
        solicitante_id="st_prueba",
        solicitante_rol="staff_operaciones",
        registrar_auditoria=False,
    )
    r2_json = await exportar_reporte_sla(
        datos_sla_export,
        desde="2025-11-01",
        hasta="2025-12-31",
        formato="json",
        tenant_id="org_acme",
        solicitante_id="st_prueba",
        solicitante_rol="staff_operaciones",
        registrar_auditoria=False,
    )
    assert r1_json["contenido"] == r2_json["contenido"]
    assert r1_json["sha256"] == r2_json["sha256"]


async def test_estructura_completa_pausas_y_muestra_minima_na(
    datos_sla_export: AsyncSession,
) -> None:
    """Verifica cabecera, resumen global, desglose, muestra mínima < 5 ('N/A') y pausas."""
    res_json = await exportar_reporte_sla(
        datos_sla_export,
        desde="2025-11-01",
        hasta="2025-12-31",
        formato="json",
        solicitante_id="st_prueba",
        solicitante_rol="staff_operaciones",
        registrar_auditoria=False,
    )
    doc = json.loads(res_json["contenido"].decode("utf-8"))

    # Cabecera
    assert doc["cabecera"]["periodo"] == {"desde": "2025-11-01", "hasta": "2025-12-31"}
    assert doc["cabecera"]["fecha_emision"] == "2025-12-31T23:50:00Z"
    assert doc["cabecera"]["solicitante"] == {
        "staff_id": "st_prueba",
        "rol": "staff_operaciones",
    }
    assert doc["cabecera"]["frescura"]["estado"] == "ok"

    # Resumen global: 6 (acme) + 3 (globex) = 9 evaluados, 7 dentro, 2 incumplidos
    global_s = doc["resumen_global"]
    assert global_s["casos_evaluados"] == 9
    assert global_s["casos_dentro"] == 7
    assert global_s["casos_incumplidos"] == 2
    assert global_s["cumplimiento_global_pct"] == 77.78
    assert global_s["tiempo_medio_computable_h"] == pytest.approx(29.22, abs=0.01)

    # Desglose clientes: acme >= 5 muestra %, globex < 5 muestra "N/A"
    por_tid = {c["tenant_id"]: c for c in doc["desglose_clientes"]}
    assert por_tid["org_acme"]["plan_codigo"] == "growth"
    assert por_tid["org_acme"]["objetivo_h"] == 24.0
    assert por_tid["org_acme"]["casos_evaluados_muestra"] == 6
    assert por_tid["org_acme"]["cumplimiento_pct"] == 83.33

    assert por_tid["org_globex"]["plan_codigo"] == "starter"
    assert por_tid["org_globex"]["objetivo_h"] == 72.0
    assert por_tid["org_globex"]["casos_evaluados"] == 3
    assert por_tid["org_globex"]["casos_evaluados_muestra"] == "N/A"
    assert por_tid["org_globex"]["cumplimiento_pct"] == "N/A"

    # Incidentes y causas de pausa
    inc_por_job = {i["job_id"]: i for i in doc["casos_incidentes"]}
    assert "job_b511_acme_fuera" not in inc_por_job
    globex_inc = inc_por_job["job_b511_globex_1"]
    assert globex_inc["ticket_numero"] == "KC-4011"
    assert globex_inc["bruto_h"] == 82.5
    assert globex_inc["transcurrido_h"] == 74.0
    assert globex_inc["pausa_total_h"] == 8.5
    assert globex_inc["motivos_pausa"] == [
        "espera_firma_cliente",
        "ventana_mantenimiento",
    ]


async def test_enmascaramiento_y_concesion_adm_g09(
    datos_sla_export: AsyncSession, cliente: Any, como: Any, sin_limite: None
) -> None:
    """Por defecto enmascara razones sociales; sin concesión activa devuelve 403."""
    sin_pii = await exportar_reporte_sla(
        datos_sla_export,
        desde="2025-11-01",
        hasta="2025-12-31",
        formato="csv",
        incluir_identificables=False,
        solicitante_id="st_prueba",
        registrar_auditoria=False,
    )
    csv_txt = sin_pii["contenido"].decode("utf-8")
    assert "\r\n" in csv_txt
    assert "Acme Logística" not in csv_txt
    assert "Globex Industrial" not in csv_txt
    assert "A•••• S.L." in csv_txt
    assert "G•••• S.A." in csv_txt
    assert "@kallicode.com" not in csv_txt

    with pytest.raises(AppError) as exc_deny:
        await exportar_reporte_sla(
            datos_sla_export,
            desde="2025-11-01",
            hasta="2025-12-31",
            formato="json",
            tenant_id="org_acme",
            incluir_identificables=True,
            solicitante_id="st_prueba",
            registrar_auditoria=False,
        )
    assert exc_deny.value.http == 403
    assert exc_deny.value.codigo == "ACCESO_NO_JUSTIFICADO"

    # Con concesión vigente en admin.access_grants sí revela razón social
    await datos_sla_export.execute(
        text(
            """
            INSERT INTO admin.access_grants
                (id, staff_id, tenant_id, scope, reason, expires_at)
            VALUES (
                'gr_b511_1', 'st_prueba', 'org_acme', 'datos_negocio',
                'Revisión contractual trimestral de SLA autorizada.',
                now() + interval '2 hours'
            )
            """
        )
    )
    await datos_sla_export.commit()

    con_pii = await exportar_reporte_sla(
        datos_sla_export,
        desde="2025-11-01",
        hasta="2025-12-31",
        formato="json",
        tenant_id="org_acme",
        incluir_identificables=True,
        solicitante_id="st_prueba",
        registrar_auditoria=False,
    )
    doc_con_pii = json.loads(con_pii["contenido"].decode("utf-8"))
    assert doc_con_pii["desglose_clientes"][0]["razon_social"] == "Acme Logística S.L."

    # En API también rechaza 403 cuando otro tenant no tiene concesión
    como("staff_operaciones", staff_id="st_prueba")
    r_403 = await cliente.post(
        "/admin/v1/business/reports",
        json={
            "tipo": "sla",
            "desde": "2025-11-01",
            "hasta": "2025-12-31",
            "formato": "csv",
            "tenant_id": "org_globex",
            "incluir_identificables": True,
        },
    )
    assert r_403.status_code == 403
    assert r_403.json()["error"]["codigo"] == "ACCESO_NO_JUSTIFICADO"


async def test_rbac_operaciones_e2e_api_worker_descarga_y_auditoria(
    datos_sla_export: AsyncSession, cliente: Any, como: Any, sin_limite: None
) -> None:
    """Flujo E2E completo: RBAC Operaciones, worker asíncrono, descarga SHA-256 y auditoría."""
    como("staff_operaciones", staff_id="st_prueba")

    # staff_operaciones NO puede solicitar informes comerciales como 'consumo'
    r_consumo = await cliente.post(
        "/admin/v1/business/reports",
        json={
            "tipo": "consumo",
            "desde": "2025-11-01",
            "hasta": "2025-12-31",
            "formato": "csv",
        },
    )
    assert r_consumo.status_code == 403
    assert r_consumo.json()["error"]["codigo"] == "ROL_STAFF_INSUFICIENTE"

    # staff_operaciones SÍ puede solicitar informe exportable tipo='sla'
    r_post = await cliente.post(
        "/admin/v1/business/reports",
        json={
            "tipo": "sla",
            "desde": "2025-11-01",
            "hasta": "2025-12-31",
            "formato": "csv",
            "incluir_identificables": False,
        },
    )
    assert r_post.status_code == 202
    report_id = r_post.json()["report_id"]

    await generar_informes(datos_sla_export)

    r_meta = await cliente.get(f"/admin/v1/business/reports/{report_id}")
    assert r_meta.status_code == 200
    meta = r_meta.json()
    assert meta["estado"] == "listo"
    sha_esperado = meta["hash_sha256"]
    assert len(sha_esperado) == 64

    r_dl = await cliente.get(
        f"/admin/v1/business/reports/{report_id}",
        params={"descargar": "true"},
    )
    assert r_dl.status_code == 200
    assert "text/csv" in r_dl.headers["content-type"]
    assert hashlib.sha256(r_dl.content).hexdigest() == sha_esperado

    texto_csv = r_dl.content.decode("utf-8")
    assert "DESGLOSE_CLIENTES" in texto_csv
    assert "CASOS_INCIDENTES" in texto_csv
    assert "KC-4011" in texto_csv
    assert "espera_firma_cliente|ventana_mantenimiento" in texto_csv
    assert "A•••• S.L." in texto_csv
    assert "Acme Logística" not in texto_csv

    # Auditoría inmutable registrada en admin.staff_actions
    res_aud = await datos_sla_export.execute(
        text(
            """
            SELECT action, resource, endpoint, payload
            FROM admin.staff_actions
            WHERE staff_id = 'st_prueba'
              AND (payload->>'report_id') = :rid
            ORDER BY occurred_at ASC
            """
        ),
        {"rid": report_id},
    )
    acciones = res_aud.mappings().all()
    assert any(
        a["action"] == "informe"
        and a["resource"] == "sla"
        and a["endpoint"] == "POST /admin/v1/business/reports"
        for a in acciones
    )
    assert any(
        a["action"] == "report"
        and a["endpoint"] == f"GET /admin/v1/business/reports/{report_id}"
        for a in acciones
    )

    # Formatos XLSX y PDF coherentes a través de generar_contenido_informe
    xlsx_bytes, xlsx_ct, _ = await generar_contenido_informe(
        "sla",
        "xlsx",
        {"desde": "2025-11-01", "hasta": "2025-12-31"},
        False,
    )
    assert xlsx_bytes.startswith(b"PK\x03\x04")
    assert "spreadsheetml" in xlsx_ct

    pdf_bytes, pdf_ct, _ = await generar_contenido_informe(
        "sla",
        "pdf",
        {"desde": "2025-11-01", "hasta": "2025-12-31"},
        False,
    )
    assert pdf_bytes.startswith(b"%PDF-1.4")
    assert pdf_bytes.rstrip().endswith(b"%%EOF")
    assert pdf_ct == "application/pdf"


async def test_respaldo_sla_cases_sin_agregado_y_auditoria_directa(
    datos_sla_export: AsyncSession,
) -> None:
    """Deriva métricas desde sla_cases cuando agg_sla_compliance está vacío y audita."""
    from admin_api.deps import Staff

    # Limpiar agregado de octubre para validar cálculo directo sobre sla_cases
    await datos_sla_export.execute(
        text("DELETE FROM admin.agg_sla_compliance WHERE ciclo = '2025-10'")
    )
    await datos_sla_export.execute(
        text(
            """
            INSERT INTO admin.sla_cases (
                job_id, tenant_id, ticket_id, ticket_numero, plan_codigo,
                etapa_final, objetivo_h, bruto_h, transcurrido_h, resultado,
                tramos, reglas, iniciado_en, terminado_en, calculado_en
            )
            VALUES
                ('job_b511_oct_1', 'org_acme', 'tk_b511_o1', 'KC-4001', 'growth',
                 'qa', 24.00, 12.00, 10.00, 'dentro',
                 '[]'::jsonb, ARRAY[]::text[],
                 TIMESTAMPTZ '2025-10-05T10:00:00Z', TIMESTAMPTZ '2025-10-05T22:00:00Z',
                 TIMESTAMPTZ '2025-10-31T23:00:00Z'),
                ('job_b511_oct_2', 'org_acme', 'tk_b511_o2', 'KC-4002', 'growth',
                 'build', 24.00, 22.00, 20.00, 'en_riesgo',
                 CAST(:tr_r AS jsonb), ARRAY['indisponibilidad_proveedor_llm'],
                 TIMESTAMPTZ '2025-10-10T10:00:00Z', NULL,
                 TIMESTAMPTZ '2025-10-31T23:00:00Z')
            ON CONFLICT (job_id) DO NOTHING
            """
        ),
        {
            "tr_r": json.dumps(
                [
                    {
                        "inicio": "2025-10-10T10:00:00Z",
                        "fin": "2025-10-10T12:00:00Z",
                        "etapa": "pausa",
                        "computa": False,
                        "causa_pausa": "indisponibilidad_proveedor_llm",
                        "horas": 2.0,
                    }
                ]
            )
        },
    )
    await datos_sla_export.commit()

    staff_ops = Staff(
        id="st_prueba",
        role="staff_operaciones",
        full_name="Empleado Prueba",
        email="st_prueba@kallicode.com",
        mfa_at=datetime.now(UTC),
        jti="jti_b511",
    )
    res = await exportar_reporte_sla(
        datos_sla_export,
        desde="2025-10-01",
        hasta="2025-10-31",
        formato="json",
        tenant_id="org_acme",
        solicitante=staff_ops,
        emitido_en="2025-10-31T23:59:59Z",
        registrar_auditoria=True,
    )
    await datos_sla_export.commit()

    doc = json.loads(res["contenido"].decode("utf-8"))
    assert doc["cabecera"]["fecha_emision"] == "2025-10-31T23:59:59Z"
    assert doc["resumen_global"]["casos_totales"] == 2
    assert doc["resumen_global"]["casos_en_riesgo"] == 1
    assert doc["resumen_global"]["cumplimiento_global_pct"] == "N/A"
    assert doc["casos_incidentes"][0]["job_id"] == "job_b511_oct_2"
    assert doc["casos_incidentes"][0]["motivos_pausa"] == ["indisponibilidad_proveedor_llm"]

    with pytest.raises(AppError) as exc_fmt:
        await exportar_reporte_sla(
            datos_sla_export,
            desde="2025-10-01",
            hasta="2025-10-31",
            formato="xml",
            registrar_auditoria=False,
        )
    assert exc_fmt.value.http == 422
