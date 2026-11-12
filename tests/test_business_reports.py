"""Suite de Pruebas de Informes Asíncronos de Negocio en Blob Storage (§18.22 - §18.23).

Ticket [KC-ADM-B4-05]: Generador Asíncrono de Informes de Negocio en Blob Storage.

Verifica de forma rigurosa:
  1. POST /admin/v1/business/reports:
     - Autorización RBAC: staff_negocio y staff_admin -> 202 Accepted.
     - Denegación RBAC: staff_soporte y staff_operaciones -> 403 ROL_STAFF_INSUFICIENTE.
     - Petición anónima -> 401 NO_AUTENTICADO.
     - Validación de tipo y formato -> 422 VALIDACION_ENTRADA.
     - Validación de fechas invertidas (desde > hasta) -> 422 VALIDACION_ENTRADA.
     - Validación de rango temporal máximo (> 24 meses) -> 422 VALIDACION_ENTRADA.
     - Regla Innegociable de Privacidad E6: incluir_identificables=true sin concesión
       activa en admin.access_grants -> 403 ACCESO_NO_JUSTIFICADO.
     - Concesión activa autoriza incluir_identificables=true -> 202 Accepted.
     - Auditoría inmediata en admin.staff_actions.
  2. GET /admin/v1/business/reports/{report_id}:
     - Aislamiento: Empleado solicitante -> 200 OK.
     - Aislamiento: staff_admin -> 200 OK.
     - Aislamiento: Otro empleado distinto -> 404 NO_ENCONTRADO.
     - Estado 'en_cola' o 'generando': download_url=null.
     - Descarga prematura (?descargar=true) antes de finalizar -> 409 CONFLICTO_ESTADO.
  3. Worker Asíncrono (generar_informes):
     - Flujo completo: en_cola -> generando -> listo.
     - Generación y streaming CSV.
     - Generación y streaming XLSX.
     - Persistencia desacoplada en Azure Blob Storage (Azurite).
     - Cálculo y verificación de integridad mediante hash SHA256.
     - Manejo de fallos del worker: estado fallido, blob_ref=NULL, error registrado.
     - Auditoría append-only inmutable en admin.staff_actions.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from unittest.mock import patch

import pytest
import pytest_asyncio
from admin_api.servicios.blob import descargar_informe
from admin_workers.main import generar_informes
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

pytestmark = pytest.mark.integracion


@pytest_asyncio.fixture
async def datos_informes_base(dsn: str, dos_clientes: list[str]) -> None:
    """Siembra datos preagregados y empleados adicionales para pruebas de informes."""
    engine = create_async_engine(
        dsn.replace("postgresql://", "postgresql+asyncpg://"),
        poolclass=NullPool,
    )
    ahora = datetime.now(UTC)
    ciclo_actual = ahora.strftime("%Y-%m")

    async with AsyncSession(engine) as session:
        # 1. Asegurar empleados para pruebas de aislamiento
        await session.execute(
            text(
                """
            INSERT INTO admin.staff
                (id, email, full_name, role, status, password_hash,
                 totp_secret, totp_enrolled_at)
            VALUES
                ('st_negocio_1', 'negocio1@kallicode.com', 'Staff Negocio 1',
                 'staff_negocio', 'active', 'hash', 'totp', now()),
                ('st_negocio_2', 'negocio2@kallicode.com', 'Staff Negocio 2',
                 'staff_negocio', 'active', 'hash', 'totp', now()),
                ('st_admin_1', 'admin1@kallicode.com', 'Staff Admin 1',
                 'staff_admin', 'active', 'hash', 'totp', now())
            ON CONFLICT (id) DO UPDATE SET
                status = 'active', password_hash = 'hash',
                totp_secret = 'totp', totp_enrolled_at = now();
            """
            )
        )

        # 2. Agregar registros en agregados de negocio para reportes
        await session.execute(
            text(
                f"""
            INSERT INTO admin.agg_usage_cycle
                (tenant_id, ciclo, loc_consumidas, umbral, cuota_pct, tokens_in,
                 tokens_out, tokens_flash, tokens_pro, tokens_fable, coste)
            VALUES
                ('org_acme', '{ciclo_actual}', 15000, 20000, 75.0, 3000000, 1500000,
                 2500000, 1500000, 500000, 45.50),
                ('org_globex', '{ciclo_actual}', 85000, 100000, 85.0, 18000000, 10000000,
                 12000000, 12000000, 4000000, 280.00)
            ON CONFLICT (tenant_id, ciclo) DO UPDATE SET coste = EXCLUDED.coste;
            """
            )
        )

        await session.execute(
            text(
                """
            INSERT INTO admin.agg_customer_state
                (tenant_id, razon_social, plan_codigo, plan_nombre, suscripcion_estado,
                 alta_el, inicia_el, renueva_el, lineas_contratadas, lineas_activas,
                 usuarios_activos, tickets_abiertos, importe_mes, moneda)
            VALUES
                ('org_acme', 'Acme Logística S.L.', 'growth', 'Growth', 'activa',
                 now() - interval '60 days', (current_date - interval '60 days')::date,
                 (current_date + interval '30 days')::date, 10, 8, 25, 2, 1200.00, 'EUR'),
                ('org_globex', 'Globex Industrial S.A.', 'enterprise', 'Enterprise', 'activa',
                 now() - interval '180 days', (current_date - interval '180 days')::date,
                 (current_date + interval '15 days')::date, 30, 28, 110, 5, 4500.00, 'EUR')
            ON CONFLICT (tenant_id) DO UPDATE SET razon_social = EXCLUDED.razon_social;
            """
            )
        )
        await session.commit()
    await engine.dispose()


# ==============================================================================
# 1. Autorización RBAC en POST /reports
# ==============================================================================


@pytest.mark.parametrize("rol", ["staff_negocio", "staff_admin"])
async def test_crear_informe_roles_autorizados_202(
    cliente: Any, como: Any, sin_limite: None, datos_informes_base: None, rol: str
) -> None:
    """staff_negocio y staff_admin pueden solicitar informes de negocio (202 Accepted)."""
    como(rol, staff_id="st_prueba")
    payload = {
        "tipo": "consumo",
        "desde": "2026-01-01",
        "hasta": "2026-06-30",
        "formato": "csv",
        "incluir_identificables": False,
    }
    r = await cliente.post("/admin/v1/business/reports", json=payload)
    assert r.status_code == 202
    body = r.json()
    assert body["report_id"].startswith("rp_")
    assert body["estado"] == "en_cola"
    assert body["estimacion_s"] >= 10


@pytest.mark.parametrize("rol", ["staff_soporte", "staff_operaciones"])
async def test_crear_informe_roles_denegados_403(
    cliente: Any, como: Any, sin_limite: None, rol: str
) -> None:
    """staff_soporte y staff_operaciones reciben 403 ROL_STAFF_INSUFICIENTE."""
    como(rol)
    payload = {
        "tipo": "consumo",
        "desde": "2026-01-01",
        "hasta": "2026-06-30",
        "formato": "csv",
    }
    r = await cliente.post("/admin/v1/business/reports", json=payload)
    assert r.status_code == 403
    assert r.json()["error"]["codigo"] == "ROL_STAFF_INSUFICIENTE"


async def test_crear_informe_anonimo_401(cliente: Any) -> None:
    """Petición sin autenticación devuelve HTTP 401 NO_AUTENTICADO."""
    payload = {
        "tipo": "consumo",
        "desde": "2026-01-01",
        "hasta": "2026-06-30",
        "formato": "csv",
    }
    r = await cliente.post("/admin/v1/business/reports", json=payload)
    assert r.status_code == 401
    assert r.json()["error"]["codigo"] == "NO_AUTENTICADO"


# ==============================================================================
# 2. Validación de Parámetros de Entrada (422)
# ==============================================================================


async def test_crear_informe_validacion_tipo_invalido_422(
    cliente: Any, como: Any, sin_limite: None
) -> None:
    """Tipo de informe desconocido devuelve HTTP 422 VALIDACION_ENTRADA."""
    como("staff_negocio")
    payload = {
        "tipo": "tipo_inexistente",
        "desde": "2026-01-01",
        "hasta": "2026-06-30",
    }
    r = await cliente.post("/admin/v1/business/reports", json=payload)
    assert r.status_code == 422
    assert r.json()["error"]["codigo"] == "VALIDACION_ENTRADA"


async def test_crear_informe_validacion_formato_invalido_422(
    cliente: Any, como: Any, sin_limite: None
) -> None:
    """Formato no admitido (ej. xml o json) devuelve HTTP 422."""
    como("staff_negocio")
    payload = {
        "tipo": "consumo",
        "desde": "2026-01-01",
        "hasta": "2026-06-30",
        "formato": "xml",
    }
    r = await cliente.post("/admin/v1/business/reports", json=payload)
    assert r.status_code == 422
    assert r.json()["error"]["codigo"] == "VALIDACION_ENTRADA"


async def test_crear_informe_validacion_fechas_invertidas_422(
    cliente: Any, como: Any, sin_limite: None
) -> None:
    """Rango invertido (desde > hasta) devuelve HTTP 422."""
    como("staff_negocio")
    payload = {
        "tipo": "consumo",
        "desde": "2026-12-01",
        "hasta": "2026-01-01",
        "formato": "csv",
    }
    r = await cliente.post("/admin/v1/business/reports", json=payload)
    assert r.status_code == 422
    assert r.json()["error"]["codigo"] == "VALIDACION_ENTRADA"


async def test_crear_informe_validacion_rango_excesivo_422(
    cliente: Any, como: Any, sin_limite: None
) -> None:
    """Rango superior a 24 meses devuelve HTTP 422."""
    como("staff_negocio")
    payload = {
        "tipo": "consumo",
        "desde": "2023-01-01",
        "hasta": "2026-06-30",  # > 40 meses
        "formato": "csv",
    }
    r = await cliente.post("/admin/v1/business/reports", json=payload)
    assert r.status_code == 422
    assert r.json()["error"]["codigo"] == "VALIDACION_ENTRADA"


# ==============================================================================
# 3. Regla Innegociable de Privacidad E6 (incluir_identificables)
# ==============================================================================


async def test_crear_informe_regla_e6_sin_concesion_403(
    cliente: Any, como: Any, sin_limite: None
) -> None:
    """incluir_identificables=true sin concesión activa es rechazado con 403."""
    como("staff_negocio", staff_id="st_prueba")
    payload = {
        "tipo": "clientes",
        "desde": "2026-01-01",
        "hasta": "2026-06-30",
        "formato": "csv",
        "incluir_identificables": True,
        "tenant_id": "org_acme",
    }
    r = await cliente.post("/admin/v1/business/reports", json=payload)
    assert r.status_code == 403
    assert r.json()["error"]["codigo"] in ("ACCESO_NO_JUSTIFICADO", "CONCESION_CADUCADA")


async def test_crear_informe_regla_e6_con_concesion_202(
    cliente: Any, como: Any, sin_limite: None, datos_informes_base: None
) -> None:
    """incluir_identificables=true con concesión activa en admin.access_grants devuelve 202."""
    # Simulamos concesión activa para org_acme con alcance datos_negocio
    como(
        "staff_negocio",
        grants={"org_acme": ["datos_negocio"]},
        staff_id="st_negocio_1",
    )
    payload = {
        "tipo": "clientes",
        "desde": "2026-01-01",
        "hasta": "2026-06-30",
        "formato": "csv",
        "tenant_id": "org_acme",
        "incluir_identificables": True,
    }
    r = await cliente.post("/admin/v1/business/reports", json=payload)
    assert r.status_code == 202
    body = r.json()
    assert body["report_id"].startswith("rp_")
    assert body["estado"] == "en_cola"


# ==============================================================================
# 4. Estado y Aislamiento en GET /reports/{report_id}
# ==============================================================================


async def test_aislamiento_informes_otro_empleado_404(
    cliente: Any, como: Any, sin_limite: None, datos_informes_base: None
) -> None:
    """Un empleado no puede consultar informes solicitados por otro empleado (HTTP 404)."""
    # 1. st_negocio_1 solicita el informe
    como("staff_negocio", staff_id="st_negocio_1")
    r1 = await cliente.post(
        "/admin/v1/business/reports",
        json={
            "tipo": "consumo",
            "desde": "2026-01-01",
            "hasta": "2026-03-31",
            "formato": "csv",
        },
    )
    assert r1.status_code == 202
    rep_id = r1.json()["report_id"]

    # 2. st_negocio_1 lo consulta con éxito
    r_propio = await cliente.get(f"/admin/v1/business/reports/{rep_id}")
    assert r_propio.status_code == 200
    assert r_propio.json()["report_id"] == rep_id
    assert r_propio.json()["estado"] == "en_cola"
    assert r_propio.json()["download_url"] is None

    # 3. st_negocio_2 intenta consultarlo -> 404 NO_ENCONTRADO
    como("staff_negocio", staff_id="st_negocio_2")
    r_otro = await cliente.get(f"/admin/v1/business/reports/{rep_id}")
    assert r_otro.status_code == 404
    assert r_otro.json()["error"]["codigo"] in ("NO_ENCONTRADO", "RECURSO_NO_ENCONTRADO")

    # 4. staff_admin tiene visibilidad transversal -> 200 OK
    como("staff_admin", staff_id="st_admin_1")
    r_admin = await cliente.get(f"/admin/v1/business/reports/{rep_id}")
    assert r_admin.status_code == 200
    assert r_admin.json()["report_id"] == rep_id


async def test_descarga_prematura_409(
    cliente: Any, como: Any, sin_limite: None, datos_informes_base: None
) -> None:
    """Intentar descargar un informe antes de estar listo devuelve 409 CONFLICTO_ESTADO."""
    como("staff_negocio", staff_id="st_negocio_1")
    r1 = await cliente.post(
        "/admin/v1/business/reports",
        json={
            "tipo": "consumo",
            "desde": "2026-01-01",
            "hasta": "2026-03-31",
            "formato": "csv",
        },
    )
    assert r1.status_code == 202
    rep_id = r1.json()["report_id"]

    # Intento explícito de descarga prematura vía query parameter descargar=true
    r_descarga = await cliente.get(
        f"/admin/v1/business/reports/{rep_id}", params={"descargar": "true"}
    )
    assert r_descarga.status_code == 409
    assert r_descarga.json()["error"]["codigo"] == "CONFLICTO_ESTADO"


# ==============================================================================
# 5. Flujo Asíncrono Completo: Worker, Blob Storage (CSV y XLSX)
# ==============================================================================


async def test_flujo_completo_generacion_worker_csv(
    cliente: Any, como: Any, sin_limite: None, datos_informes_base: None, dsn: str
) -> None:
    """Valida el ciclo de vida completo de un informe CSV hasta quedar listo y descargable."""
    como("staff_negocio", staff_id="st_negocio_1")
    ahora = datetime.now(UTC)
    desde = f"{ahora.year}-01-01"
    hasta = ahora.strftime("%Y-%m-%d")

    # 1. Solicitar informe CSV
    r_post = await cliente.post(
        "/admin/v1/business/reports",
        json={
            "tipo": "consumo",
            "desde": desde,
            "hasta": hasta,
            "formato": "csv",
        },
    )
    assert r_post.status_code == 202
    rep_id = r_post.json()["report_id"]

    # 2. Ejecutar worker de procesamiento en segundo plano
    engine = create_async_engine(
        dsn.replace("postgresql://", "postgresql+asyncpg://"),
        poolclass=NullPool,
    )
    async with AsyncSession(engine) as session:
        await generar_informes(session)
    await engine.dispose()

    # 3. Consultar estado completado
    r_get = await cliente.get(f"/admin/v1/business/reports/{rep_id}")
    assert r_get.status_code == 200
    body = r_get.json()
    assert body["report_id"] == rep_id
    assert body["estado"] == "listo"
    assert body["formato"] == "csv"
    assert body["download_url"] is not None
    assert "token" in body["download_url"] or "?" in body["download_url"]
    assert body["hash_sha256"] is not None
    assert len(body["hash_sha256"]) == 64
    assert body["filas"] >= 1

    # 4. Validar contenido descargado directamente desde el almacenamiento
    hoy = ahora.strftime("%Y/%m")
    blob_ref = f"{hoy}/{rep_id}.csv"
    contenido = await descargar_informe(blob_ref)
    assert b"tenant_id,ciclo,loc_consumidas" in contenido
    assert b"org_acme" in contenido


async def test_flujo_completo_generacion_worker_xlsx(
    cliente: Any, como: Any, sin_limite: None, datos_informes_base: None, dsn: str
) -> None:
    """Valida el ciclo de vida completo de un informe en formato XLSX."""
    como("staff_negocio", staff_id="st_negocio_1")
    ahora = datetime.now(UTC)
    desde = f"{ahora.year}-01-01"
    hasta = ahora.strftime("%Y-%m-%d")

    # 1. Solicitar informe XLSX
    r_post = await cliente.post(
        "/admin/v1/business/reports",
        json={
            "tipo": "suscripciones",
            "desde": desde,
            "hasta": hasta,
            "formato": "xlsx",
        },
    )
    assert r_post.status_code == 202
    rep_id = r_post.json()["report_id"]

    # 2. Ejecutar worker
    engine = create_async_engine(
        dsn.replace("postgresql://", "postgresql+asyncpg://"),
        poolclass=NullPool,
    )
    async with AsyncSession(engine) as session:
        await generar_informes(session)
    await engine.dispose()

    # 3. Consultar estado
    r_get = await cliente.get(f"/admin/v1/business/reports/{rep_id}")
    assert r_get.status_code == 200
    body = r_get.json()
    assert body["estado"] == "listo"
    assert body["formato"] == "xlsx"
    assert body["hash_sha256"] is not None

    # 4. Verificar firma mágica de archivo ZIP / XLSX (PK\x03\x04)
    hoy = ahora.strftime("%Y/%m")
    blob_ref = f"{hoy}/{rep_id}.xlsx"
    contenido = await descargar_informe(blob_ref)
    assert contenido.startswith(b"PK\x03\x04")


# ==============================================================================
# 6. Manejo de Fallos en Worker
# ==============================================================================


async def test_worker_error_persiste_estado_fallido(
    cliente: Any, como: Any, sin_limite: None, datos_informes_base: None, dsn: str
) -> None:
    """Si ocurre un fallo en generación o subida, el estado queda como fallido sin blob."""
    como("staff_negocio", staff_id="st_negocio_1")
    r_post = await cliente.post(
        "/admin/v1/business/reports",
        json={
            "tipo": "consumo",
            "desde": "2026-01-01",
            "hasta": "2026-03-31",
            "formato": "csv",
        },
    )
    assert r_post.status_code == 202
    rep_id = r_post.json()["report_id"]

    # Simular excepción en la subida a Blob Storage
    engine = create_async_engine(
        dsn.replace("postgresql://", "postgresql+asyncpg://"),
        poolclass=NullPool,
    )
    with patch(
        "admin_workers.main.subir_informe",
        side_effect=RuntimeError("Fallo simulado en almacenamiento de objetos"),
    ):
        async with AsyncSession(engine) as session:
            await generar_informes(session)
    await engine.dispose()

    # Consultar estado: debe responder fallido y download_url=null
    r_get = await cliente.get(f"/admin/v1/business/reports/{rep_id}")
    assert r_get.status_code == 200
    body = r_get.json()
    assert body["estado"] == "fallido"
    assert body["download_url"] is None
    assert body["error"] is not None
    assert body["error"]["codigo"] == "GENERACION_FALLIDA"
    assert "Fallo simulado" in body["error"]["mensaje"]


# ==============================================================================
# 7. Auditoría Append-Only en admin.staff_actions
# ==============================================================================


async def test_auditoria_append_only_registrada(
    cliente: Any, como: Any, sin_limite: None, datos_informes_base: None, dsn: str
) -> None:
    """Toda solicitud y consulta de informe se registra inmutablemente en staff_actions."""
    como("staff_negocio", staff_id="st_negocio_1")
    r_post = await cliente.post(
        "/admin/v1/business/reports",
        json={
            "tipo": "consumo",
            "desde": "2026-01-01",
            "hasta": "2026-03-31",
            "formato": "csv",
        },
    )
    assert r_post.status_code == 202
    rep_id = r_post.json()["report_id"]

    await cliente.get(f"/admin/v1/business/reports/{rep_id}")

    # Verificar que existan las acciones en admin.staff_actions
    engine = create_async_engine(
        dsn.replace("postgresql://", "postgresql+asyncpg://"),
        poolclass=NullPool,
    )
    async with AsyncSession(engine) as session:
        res = await session.execute(
            text(
                """
            SELECT action, endpoint, payload
            FROM admin.staff_actions
            WHERE staff_id = 'st_negocio_1' AND action = 'report'
            ORDER BY occurred_at DESC;
            """
            )
        )
        filas = res.mappings().all()
    await engine.dispose()

    assert len(filas) >= 2
    endpoints = [f["endpoint"] for f in filas]
    assert "POST /admin/v1/business/reports" in endpoints
    assert f"GET /admin/v1/business/reports/{rep_id}" in endpoints
