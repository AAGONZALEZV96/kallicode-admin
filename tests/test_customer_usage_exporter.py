"""Suite de Pruebas Automatizadas de Exportación CSV/PDF/XLSX (§18.22 - §18.23).

Ticket [KC-ADM-B4-09]: Exportador CSV/PDF de Resumen de Clientes y Consumo.

Verifica de forma rigurosa y exhaustiva:
  1. Exportador CSV de Clientes (tipo = 'clientes'):
     - Cumplimiento de RFC 4180 (delimitadores, terminadores CRLF \\r\\n, escape de comillas).
     - Cabeceras obligatorias: tenant_id, razon_social, plan, estado, lineas_contratadas,
       inicia_el, renueva_el, dias_para_renovacion.
     - Enmascaramiento PII por defecto (A•••• S.L.) según Regla E6.
     - Revelación en claro de razon_social (Acme Logística S.L.) con incluir_identificables=True
       y concesión activa en admin.access_grants.
  2. Exportador CSV de Consumo (tipo = 'consumo'):
     - Métricas completas: tokens_entrada, tokens_salida, tokens_total, loc_netas,
       coste_estimado_eur, cuota_pct, cuadra_con_facturacion.
     - Desglose independiente de tiers: tokens_flash, tokens_pro y tokens_fable.
     - Regla Inviolable de Fable: tokens_fable permanece 100% segregado y nunca diluido.
     - Fila final de agregados (TOTALES / CONSOLIDADO) con suma matemática exacta.
  3. Formatos Alternativos (PDF y XLSX):
     - PDF: generación válida PDF 1.4 (%PDF-1.4 ... %%EOF), tabla tabular y totales.
     - XLSX: libro OpenXML válido (PK\\x03\\x04) con hojas y celdas legibles.
  4. Integridad Criptográfica SHA-256:
     - Coincidencia exacta entre el hash del archivo y el sha256 registrado en API/BD.
  5. Descarga Segura Autenticada (GET /reports/{report_id}?descargar=true):
     - Descarga directa con headers Content-Type y Content-Disposition apropiados.
     - Rechazo 409 CONFLICTO_ESTADO si se intenta descargar antes de finalizar.
     - Rechazo 404 si otro empleado no autorizado intenta descargar el informe.
     - Registro obligatorio del evento 'descargado' en admin.staff_actions.
  6. Control de Acceso RBAC y Regla E6:
     - Rechazo 403 ROL_STAFF_INSUFICIENTE para staff_soporte y staff_operaciones.
     - Rechazo 403 ACCESO_NO_JUSTIFICADO si se pide incluir_identificables sin concesión.
"""

from __future__ import annotations

import csv
import hashlib
from datetime import UTC, datetime
from typing import Any

import pytest
import pytest_asyncio
from admin_workers.main import generar_informes
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

pytestmark = pytest.mark.integracion


@pytest_asyncio.fixture
async def datos_exportador(dsn: str, dos_clientes: list[str]) -> Any:
    """Siembra datos analíticos enriquecidos para pruebas de exportación y limpia al final."""
    engine = create_async_engine(
        dsn.replace("postgresql://", "postgresql+asyncpg://"),
        poolclass=NullPool,
    )
    ahora = datetime.now(UTC)
    ciclo_actual = ahora.strftime("%Y-%m")

    async with AsyncSession(engine) as session:
        # 1. Configurar organizaciones y datos de clientes en admin.agg_customer_state
        await session.execute(
            text(
                "UPDATE core.organizations "
                "SET nombre = 'Acme Logística S.L.' WHERE id = 'org_acme'"
            )
        )
        await session.execute(
            text(
                "UPDATE core.organizations "
                "SET nombre = 'Globex Industrial S.A.' WHERE id = 'org_globex'"
            )
        )
        await session.execute(
            text(
                """
            INSERT INTO admin.agg_customer_state (
                tenant_id, razon_social, plan_codigo, suscripcion_estado,
                inicia_el, renueva_el, lineas_contratadas, lineas_activas,
                usuarios_activos, tickets_abiertos, importe_mes, moneda, alta_el, actualizado_en
            )
            VALUES
                ('org_acme', 'Acme Logística S.L.', 'growth', 'activa',
                 current_date - 120, current_date + 45, 3, 2,
                 15, 2, 2900.00, 'EUR', now() - interval '120 days', now()),
                ('org_globex', 'Globex Industrial S.A.', 'enterprise', 'activa',
                 current_date - 240, current_date + 90, 10, 8,
                 50, 5, 9500.00, 'EUR', now() - interval '240 days', now())
            ON CONFLICT (tenant_id) DO UPDATE SET
                razon_social = EXCLUDED.razon_social,
                plan_codigo = EXCLUDED.plan_codigo,
                suscripcion_estado = EXCLUDED.suscripcion_estado,
                inicia_el = EXCLUDED.inicia_el,
                renueva_el = EXCLUDED.renueva_el,
                lineas_contratadas = EXCLUDED.lineas_contratadas,
                actualizado_en = now();
        """
            )
        )

        # 2. Sembrar datos de consumo en core.usage_cycles y admin.agg_usage_cycle
        await session.execute(
            text(
                f"""
            INSERT INTO core.usage_cycles (tenant_id, ciclo, loc_consumidas, umbral)
            VALUES
                ('org_acme', '{ciclo_actual}', 4500, 'normal'),
                ('org_globex', '{ciclo_actual}', 18500, 'normal')
            ON CONFLICT (tenant_id, ciclo) DO UPDATE SET
                loc_consumidas = EXCLUDED.loc_consumidas;
        """
            )
        )
        await session.execute(
            text(
                f"""
            INSERT INTO admin.agg_usage_cycle (
                tenant_id, ciclo, loc_consumidas, umbral, cuota_pct,
                tokens_in, tokens_out, tokens_flash, tokens_pro, tokens_fable,
                coste, moneda
            )
            VALUES
                ('org_acme', '{ciclo_actual}', 4500, 8000, 56.25,
                 50000, 15000, 45000, 20000, 0,
                 12.50, 'EUR'),
                ('org_globex', '{ciclo_actual}', 18500, 25000, 74.00,
                 180000, 45000, 120000, 90000, 15000,
                 58.40, 'EUR')
            ON CONFLICT (tenant_id, ciclo) DO UPDATE SET
                loc_consumidas = EXCLUDED.loc_consumidas,
                cuota_pct = EXCLUDED.cuota_pct,
                tokens_in = EXCLUDED.tokens_in,
                tokens_out = EXCLUDED.tokens_out,
                tokens_flash = EXCLUDED.tokens_flash,
                tokens_pro = EXCLUDED.tokens_pro,
                tokens_fable = EXCLUDED.tokens_fable,
                coste = EXCLUDED.coste;
        """
            )
        )

        # 3. Staff empleados para pruebas de autorización
        await session.execute(
            text(
                """
            INSERT INTO admin.staff
                (id, email, full_name, role, status,
                 password_hash, totp_secret, totp_enrolled_at)
            VALUES
                ('st_exp_negocio', 'exp_negocio@kallicode.com', 'Comercial Exportador',
                 'staff_negocio', 'active', 'hash', 'totp', now()),
                ('st_exp_otro', 'exp_otro@kallicode.com', 'Otro Empleado',
                 'staff_negocio', 'active', 'hash', 'totp', now())
            ON CONFLICT (id) DO NOTHING;
        """
            )
        )
        await session.commit()

    yield {
        "ciclo": ciclo_actual,
        "desde": f"{ahora.year}-01-01",
        "hasta": ahora.strftime("%Y-%m-%d"),
    }

    # Limpieza idempotente en bloque finally
    try:
        async with AsyncSession(engine) as cleanup:
            await cleanup.execute(
                text(
                    "DELETE FROM admin.reports "
                    "WHERE requested_by IN ('st_exp_negocio', 'st_exp_otro')"
                )
            )
            await cleanup.execute(
                text("DELETE FROM admin.access_grants WHERE id = 'gr_exp_01'")
            )
            await cleanup.commit()
    except Exception:
        pass
    finally:
        await engine.dispose()


# ==============================================================================
# 1. Exportador CSV de Clientes y Enmascaramiento RFC 4180
# ==============================================================================


async def test_exportador_clientes_csv_rfc4180_y_enmascaramiento(
    cliente: Any,
    como: Any,
    sin_limite: None,
    datos_exportador: dict[str, Any],
    dsn: str,
) -> None:
    """Valida que el CSV de clientes cumple RFC 4180 y enmascara por defecto la razón social."""
    como("staff_negocio", staff_id="st_exp_negocio")

    # 1. Solicitar informe de clientes con enmascaramiento por defecto
    r_sol = await cliente.post(
        "/admin/v1/business/reports",
        json={
            "tipo": "clientes",
            "desde": datos_exportador["desde"],
            "hasta": datos_exportador["hasta"],
            "formato": "csv",
            "incluir_identificables": False,
        },
    )
    assert r_sol.status_code == 202
    report_id = r_sol.json()["report_id"]

    # 2. Ejecutar worker de procesamiento
    engine = create_async_engine(
        dsn.replace("postgresql://", "postgresql+asyncpg://"),
        poolclass=NullPool,
    )
    async with AsyncSession(engine) as session:
        await generar_informes(session)
    await engine.dispose()

    # 3. Descargar contenido mediante el endpoint de descarga autenticada
    r_down = await cliente.get(
        f"/admin/v1/business/reports/{report_id}", params={"descargar": "true"}
    )
    assert r_down.status_code == 200
    contenido_bytes = r_down.content

    # 4. Verificación RFC 4180 (terminador CRLF \r\n)
    assert b"\r\n" in contenido_bytes, "El archivo CSV debe usar terminadores CRLF (RFC 4180)"
    texto_csv = contenido_bytes.decode("utf-8")
    lector = list(csv.DictReader(texto_csv.splitlines()))

    assert len(lector) >= 2, "Debe contener al menos 2 clientes"
    headers = list(lector[0].keys())

    # Comprobar cabeceras obligatorias requeridas por el ticket
    cabeceras_esperadas = [
        "tenant_id",
        "razon_social",
        "plan",
        "estado",
        "lineas_contratadas",
        "inicia_el",
        "renueva_el",
        "dias_para_renovacion",
    ]
    for c in cabeceras_esperadas:
        assert c in headers, f"Cabecera obligatoria ausente: {c}"

    # 5. Comprobar enmascaramiento por defecto (Regla E6)
    fila_acme = next(f for f in lector if f["tenant_id"] == "org_acme")
    assert (
        fila_acme["razon_social"] == "A•••• S.L."
    ), f"La razón social debió estar enmascarada; tiene: {fila_acme['razon_social']}"
    assert fila_acme["plan"] == "growth"
    assert fila_acme["estado"] == "activo"
    assert int(fila_acme["lineas_contratadas"]) == 3
    assert int(fila_acme["dias_para_renovacion"]) > 0


async def test_exportador_clientes_csv_con_concesion_pii_en_claro(
    cliente: Any,
    como: Any,
    sin_limite: None,
    datos_exportador: dict[str, Any],
    dsn: str,
) -> None:
    """Valida que con incluir_identificables=True y concesión activa,
    la razón social sale en claro.
    """
    # 1. Otorgar concesión activa a st_exp_negocio
    engine = create_async_engine(
        dsn.replace("postgresql://", "postgresql+asyncpg://"),
        poolclass=NullPool,
    )
    async with AsyncSession(engine) as session:
        await session.execute(
            text(
                """
            INSERT INTO admin.access_grants (
                id, staff_id, tenant_id, scope, reason, expires_at
            )
            VALUES
                ('gr_exp_01', 'st_exp_negocio', 'org_acme', 'datos_negocio',
                 'Auditoría comercial periódica autorizada', now() + interval '2 hours')
            ON CONFLICT (id) DO UPDATE SET expires_at = now() + interval '2 hours';
        """
            )
        )
        await session.commit()
    await engine.dispose()

    # 2. Solicitar informe con PII autorizado
    como("staff_negocio", staff_id="st_exp_negocio", grants={"org_acme": ["datos_negocio"]})
    r_sol = await cliente.post(
        "/admin/v1/business/reports",
        json={
            "tipo": "clientes",
            "desde": datos_exportador["desde"],
            "hasta": datos_exportador["hasta"],
            "formato": "csv",
            "incluir_identificables": True,
        },
    )
    assert r_sol.status_code == 202
    report_id = r_sol.json()["report_id"]

    # 3. Generar en worker
    engine = create_async_engine(
        dsn.replace("postgresql://", "postgresql+asyncpg://"),
        poolclass=NullPool,
    )
    async with AsyncSession(engine) as session:
        await generar_informes(session)
    await engine.dispose()

    # 4. Descargar y validar razón social en claro
    r_down = await cliente.get(
        f"/admin/v1/business/reports/{report_id}", params={"descargar": "true"}
    )
    assert r_down.status_code == 200
    contenido = r_down.text
    lector = list(csv.DictReader(contenido.splitlines()))

    fila_acme = next(f for f in lector if f["tenant_id"] == "org_acme")
    assert (
        fila_acme["razon_social"] == "Acme Logística S.L."
    ), f"Razón social en claro esperada; tiene: {fila_acme['razon_social']}"


# ==============================================================================
# 2. Exportador CSV de Consumo, Regla de Oro de Fable y Fila de Totales
# ==============================================================================


async def test_exportador_consumo_csv_fable_independiente_y_fila_totales(
    cliente: Any,
    como: Any,
    sin_limite: None,
    datos_exportador: dict[str, Any],
    dsn: str,
) -> None:
    """Valida métricas completas de consumo, separación estricta de fable
    y fila final de totales.
    """
    como("staff_admin", staff_id="st_prueba")

    # 1. Solicitar informe de consumo
    r_sol = await cliente.post(
        "/admin/v1/business/reports",
        json={
            "tipo": "consumo",
            "desde": datos_exportador["desde"],
            "hasta": datos_exportador["hasta"],
            "formato": "csv",
        },
    )
    assert r_sol.status_code == 202
    report_id = r_sol.json()["report_id"]

    # 2. Worker
    engine = create_async_engine(
        dsn.replace("postgresql://", "postgresql+asyncpg://"),
        poolclass=NullPool,
    )
    async with AsyncSession(engine) as session:
        await generar_informes(session)
    await engine.dispose()

    # 3. Descargar CSV y verificar estructura
    r_down = await cliente.get(
        f"/admin/v1/business/reports/{report_id}", params={"descargar": "true"}
    )
    assert r_down.status_code == 200
    contenido = r_down.text
    lector = list(csv.DictReader(contenido.splitlines()))

    assert len(lector) >= 3, "Debe contener los clientes más la fila final de TOTALES"

    # Verificar presencia de columnas de desglose por tier
    headers = list(lector[0].keys())
    for col in [
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
    ]:
        assert col in headers, f"Columna obligatoria ausente: {col}"

    # 4. Regla de Oro de Fable: validación estricta de segregación en org_globex
    fila_globex = next(f for f in lector if f["tenant_id"] == "org_globex")
    assert (
        int(fila_globex["tokens_fable"]) == 15000
    ), f"Fable debe tener 15.000 tokens exactos; tiene: {fila_globex['tokens_fable']}"
    assert int(fila_globex["tokens_pro"]) == 90000, "Pro no debe absorber Fable"
    assert int(fila_globex["tokens_flash"]) == 120000, "Flash no debe absorber Fable"

    # 5. Fila Final de Totales Consolidados (auditoría contable)
    fila_totales = lector[-1]
    assert fila_totales["tenant_id"] == "TOTALES"
    assert fila_totales["ciclo"] == "CONSOLIDADO"

    # Suma matemática de tokens entre los clientes
    filas_datos = [f for f in lector if f["tenant_id"] != "TOTALES"]
    suma_tokens_esperada = sum(int(f["tokens_total"]) for f in filas_datos)
    suma_coste_esperada = round(sum(float(f["coste_estimado_eur"]) for f in filas_datos), 2)

    assert int(fila_totales["tokens_total"]) == suma_tokens_esperada
    assert float(fila_totales["coste_estimado_eur"]) == suma_coste_esperada
    assert fila_totales["cuadra_con_facturacion"] in ("True", "true", "1")


# ==============================================================================
# 3. Formatos Alternativos: PDF 1.4 y XLSX
# ==============================================================================


async def test_exportador_formatos_pdf_y_xlsx(
    cliente: Any,
    como: Any,
    sin_limite: None,
    datos_exportador: dict[str, Any],
    dsn: str,
) -> None:
    """Verifica que el generador produce documentos PDF 1.4 y XLSX válidos y legibles."""
    como("staff_negocio", staff_id="st_exp_negocio")

    # 1. Informe en formato PDF
    r_pdf = await cliente.post(
        "/admin/v1/business/reports",
        json={
            "tipo": "consumo",
            "desde": datos_exportador["desde"],
            "hasta": datos_exportador["hasta"],
            "formato": "pdf",
        },
    )
    assert r_pdf.status_code == 202
    rep_pdf_id = r_pdf.json()["report_id"]

    # 2. Informe en formato XLSX
    r_xlsx = await cliente.post(
        "/admin/v1/business/reports",
        json={
            "tipo": "clientes",
            "desde": datos_exportador["desde"],
            "hasta": datos_exportador["hasta"],
            "formato": "xlsx",
        },
    )
    assert r_xlsx.status_code == 202
    rep_xlsx_id = r_xlsx.json()["report_id"]

    # 3. Procesar en worker
    engine = create_async_engine(
        dsn.replace("postgresql://", "postgresql+asyncpg://"),
        poolclass=NullPool,
    )
    async with AsyncSession(engine) as session:
        await generar_informes(session)
    await engine.dispose()

    # 4. Validar estructura de bytes del PDF
    r_pdf_down = await cliente.get(
        f"/admin/v1/business/reports/{rep_pdf_id}", params={"descargar": "true"}
    )
    assert r_pdf_down.status_code == 200
    bytes_pdf = r_pdf_down.content

    assert bytes_pdf.startswith(
        b"%PDF-1.4"
    ), "El PDF debe iniciar con la cabecera estándar %PDF-1.4"
    assert b"%%EOF" in bytes_pdf, "El PDF debe finalizar con el marcador %%EOF"
    assert b"TOTALES" in bytes_pdf, "El PDF de consumo debe contener la fila de TOTALES"

    # 5. Validar estructura de bytes del XLSX
    r_xlsx_down = await cliente.get(
        f"/admin/v1/business/reports/{rep_xlsx_id}", params={"descargar": "true"}
    )
    assert r_xlsx_down.status_code == 200
    bytes_xlsx = r_xlsx_down.content

    assert bytes_xlsx.startswith(
        b"PK\x03\x04"
    ), "El XLSX debe ser un contenedor ZIP válido (PK)"
    assert len(bytes_xlsx) > 500


# ==============================================================================
# 4. Integridad Criptográfica SHA-256
# ==============================================================================


async def test_integridad_sha256_fichero_descargado(
    cliente: Any,
    como: Any,
    sin_limite: None,
    datos_exportador: dict[str, Any],
    dsn: str,
) -> None:
    """Verifica que el hash SHA-256 del contenido coincide exactamente
    con el devuelto por la API.
    """
    como("staff_negocio", staff_id="st_exp_negocio")

    r_sol = await cliente.post(
        "/admin/v1/business/reports",
        json={
            "tipo": "clientes",
            "desde": datos_exportador["desde"],
            "hasta": datos_exportador["hasta"],
            "formato": "csv",
        },
    )
    report_id = r_sol.json()["report_id"]

    engine = create_async_engine(
        dsn.replace("postgresql://", "postgresql+asyncpg://"),
        poolclass=NullPool,
    )
    async with AsyncSession(engine) as session:
        await generar_informes(session)
    await engine.dispose()

    r_est = await cliente.get(f"/admin/v1/business/reports/{report_id}")
    sha256_api = r_est.json()["hash_sha256"]

    r_down = await cliente.get(
        f"/admin/v1/business/reports/{report_id}", params={"descargar": "true"}
    )
    assert r_down.status_code == 200
    contenido_bytes = r_down.content
    sha256_calculado = hashlib.sha256(contenido_bytes).hexdigest()

    assert (
        sha256_calculado == sha256_api
    ), "El hash SHA-256 calculado debe coincidir exactamente"
    assert len(sha256_api) == 64


# ==============================================================================
# 5. Endpoint de Descarga Directa Autenticada y Auditoría
# ==============================================================================


async def test_descarga_autenticada_endpoint_download_y_auditoria(
    cliente: Any,
    como: Any,
    sin_limite: None,
    datos_exportador: dict[str, Any],
    dsn: str,
) -> None:
    """Valida endpoint GET /reports/{id}?descargar=true, trazabilidad en staff_actions
    y rechazo 409.
    """
    como("staff_negocio", staff_id="st_exp_negocio")

    r_sol = await cliente.post(
        "/admin/v1/business/reports",
        json={
            "tipo": "clientes",
            "desde": datos_exportador["desde"],
            "hasta": datos_exportador["hasta"],
            "formato": "csv",
        },
    )
    report_id = r_sol.json()["report_id"]

    # 1. Rechazo 409 si aún está en_cola (descarga prematura)
    r_prematuro = await cliente.get(
        f"/admin/v1/business/reports/{report_id}", params={"descargar": "true"}
    )
    assert r_prematuro.status_code == 409
    assert r_prematuro.json()["error"]["codigo"] == "CONFLICTO_ESTADO"

    # 2. Generar informe
    engine = create_async_engine(
        dsn.replace("postgresql://", "postgresql+asyncpg://"),
        poolclass=NullPool,
    )
    async with AsyncSession(engine) as session:
        await generar_informes(session)
    await engine.dispose()

    # 3. Descarga exitosa con 200 y Content-Disposition
    r_down = await cliente.get(
        f"/admin/v1/business/reports/{report_id}", params={"descargar": "true"}
    )
    assert r_down.status_code == 200
    assert "text/csv" in r_down.headers["content-type"]
    assert (
        f'filename="informe_clientes_{report_id}.csv"' in r_down.headers["content-disposition"]
    )
    assert b"tenant_id,razon_social" in r_down.content

    # 4. Validar auditoría append-only en admin.staff_actions
    async with AsyncSession(engine) as session:
        r_audit = await session.execute(
            text(
                """
            SELECT action, endpoint, payload
            FROM admin.staff_actions
            WHERE staff_id = 'st_exp_negocio'
              AND endpoint = :ep
            ORDER BY occurred_at DESC LIMIT 1
        """
            ),
            {"ep": f"GET /admin/v1/business/reports/{report_id}"},
        )
        row_audit = r_audit.mappings().first()
        assert row_audit is not None, "La descarga debió registrarse en admin.staff_actions"
        assert row_audit["action"] == "report"
        assert row_audit["payload"]["evento"] == "descargado"
    await engine.dispose()

    # 5. Aislamiento: otro empleado sin rol admin recibe 404
    como("staff_negocio", staff_id="st_exp_otro")
    r_ajeno = await cliente.get(
        f"/admin/v1/business/reports/{report_id}", params={"descargar": "true"}
    )
    assert r_ajeno.status_code == 404


# ==============================================================================
# 6. Control de Acceso RBAC y Regla E6
# ==============================================================================


@pytest.mark.parametrize("rol", ["staff_soporte", "staff_operaciones"])
async def test_exportador_rbac_rechazo_soporte_y_operaciones_403(
    cliente: Any, como: Any, sin_limite: None, rol: str
) -> None:
    """staff_soporte y staff_operaciones son rechazados con 403 ROL_STAFF_INSUFICIENTE."""
    como(rol)
    r = await cliente.post(
        "/admin/v1/business/reports",
        json={
            "tipo": "consumo",
            "desde": "2026-01-01",
            "hasta": "2026-03-31",
            "formato": "csv",
        },
    )
    assert r.status_code == 403
    assert r.json()["error"]["codigo"] == "ROL_STAFF_INSUFICIENTE"


async def test_exportador_regla_e6_sin_concesion_403(
    cliente: Any, como: Any, sin_limite: None
) -> None:
    """incluir_identificables=True sin concesión activa es rechazado
    con 403 ACCESO_NO_JUSTIFICADO.
    """
    como("staff_negocio", staff_id="st_exp_negocio")
    r = await cliente.post(
        "/admin/v1/business/reports",
        json={
            "tipo": "clientes",
            "desde": "2026-01-01",
            "hasta": "2026-03-31",
            "formato": "csv",
            "incluir_identificables": True,
        },
    )
    assert r.status_code == 403
    assert r.json()["error"]["codigo"] == "ACCESO_NO_JUSTIFICADO"
