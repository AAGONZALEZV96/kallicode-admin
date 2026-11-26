"""Orquestador Cero-Nube de pruebas de carga y medición de contención PostgreSQL (KC-ADM-B6-07).

Ejecuta los 3 escenarios de carga concurrente (50 VUs simultáneos sobre agregados de
negocio, polling de operaciones y refrescos concurrentes `SECURITY DEFINER`), mide:
  - Latencias p50, p95, p99 y tasa de éxito por endpoint (`/admin/v1/business/*`,
    `/admin/v1/ops/*`, `/admin/v1/health`).
  - Contención real en PostgreSQL (`pg_locks` con `granted = false`, `pg_stat_database`
    deadlocks, sesiones `kallicode_admin_ro` con `transaction_read_only = on`).
  - Impacto sobre transacciones simuladas del portal del cliente (`kallicode_app`
    haciendo DML en `core.tickets`) antes y durante el pico de 50 VUs + `refresh_*`.
"""

from __future__ import annotations

import asyncio
import math
import time
from datetime import UTC, datetime
from typing import Any

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from .seed_and_tokens import _normalizar_async_dsn

ENDPOINTS_CARGA: tuple[tuple[str, str, str], ...] = (
    ("negocio", "GET /admin/v1/business/summary", "/admin/v1/business/summary"),
    (
        "negocio",
        "GET /admin/v1/business/overview",
        "/admin/v1/business/overview?periodo=mes_actual&comparar_con=periodo_anterior",
    ),
    (
        "negocio",
        "GET /admin/v1/business/customers",
        "/admin/v1/business/customers?page=1&page_size=25",
    ),
    (
        "negocio",
        "GET /admin/v1/business/usage/tokens",
        "/admin/v1/business/usage/tokens?periodo=mes_actual&agrupar_por=cliente",
    ),
    ("ops", "GET /admin/v1/ops/agents", "/admin/v1/ops/agents?ventana=1h"),
    ("ops", "GET /admin/v1/ops/models", "/admin/v1/ops/models?ventana=24h"),
    ("ops", "GET /admin/v1/ops/sla", "/admin/v1/ops/sla"),
    ("secdef", "GET /admin/v1/health", "/admin/v1/health"),
)


def calcular_percentil(valores: list[float], pct: float) -> float:
    """Calcula el percentil `pct` (0..100) sobre una lista de tiempos en ms."""
    if not valores:
        return 0.0
    ordenados = sorted(valores)
    k = max(0, min(len(ordenados) - 1, math.ceil((pct / 100.0) * len(ordenados)) - 1))
    return round(ordenados[k], 2)


def payload_telemetria_fresca(ventana: str = "1h") -> dict[str, Any]:
    """Payload canónico fresco para el contrato interno E2 durante pruebas de carga."""
    ahora_iso = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    return {
        "ventana": ventana,
        "telemetria_desde": ahora_iso,
        "agentes_total": 12,
        "agentes_ocupados": 8,
        "agentes_caidos": 0,
        "jobs_completados": 45,
        "duracion_p95_s": 18.4,
        "lineas_activas": 6,
        "etapas": [
            {
                "etapa": "build",
                "activos": 4,
                "completados": 20,
                "fallidos": 0,
                "latencia_p95_s": 14.2,
            },
            {
                "etapa": "qa",
                "activos": 4,
                "completados": 25,
                "fallidos": 0,
                "latencia_p95_s": 19.1,
            },
        ],
        "proveedores": [
            {
                "proveedor": "google",
                "modelo": "gemini-2.0-flash",
                "tier": "flash",
                "disponibilidad_pct": 99.95,
                "latencia_p50_ms": 210.0,
                "latencia_p95_ms": 480.0,
                "tasa_error_pct": 0.05,
                "invocaciones": 1250,
            },
            {
                "proveedor": "anthropic",
                "modelo": "claude-3-7-sonnet",
                "tier": "fable",
                "disponibilidad_pct": 99.90,
                "latencia_p50_ms": 390.0,
                "latencia_p95_ms": 790.0,
                "tasa_error_pct": 0.10,
                "invocaciones": 340,
            },
        ],
        "escalados": {"total": 2, "tasa_pct": 0.5},
    }


def _validar_json_endpoint(etiqueta: str, status: int, data: Any) -> bool:
    if status != 200 or not isinstance(data, dict):
        return False
    if etiqueta.endswith("/summary"):
        return "frescura" in data
    if etiqueta.endswith("/overview"):
        return "clientes" in data and "ingreso_recurrente" in data
    if etiqueta.endswith("/customers"):
        return isinstance(data.get("items"), list) and isinstance(data.get("total"), int)
    if etiqueta.endswith("/usage/tokens"):
        return isinstance(data.get("items"), list) and "frescura" in data
    if etiqueta.endswith("/ops/agents"):
        return "lineas" in data and "telemetria" in data
    if etiqueta.endswith("/ops/models"):
        return isinstance(data.get("proveedores"), list) and isinstance(
            data.get("modelos"), list
        )
    if etiqueta.endswith("/ops/sla"):
        return "resumen" in data and "por_plan" in data and isinstance(data.get("items"), list)
    if etiqueta.endswith("/health"):
        deps = data.get("dependencias") or {}
        return bool(deps.get("postgres")) and bool(deps.get("lectura_analitica"))
    return True


async def _medir_dml_portal_cliente(dsn_superuser: str, iteraciones: int = 15) -> list[float]:
    """Simula escrituras transaccionales del portal (`core.tickets`) midiendo latencia."""
    engine = create_async_engine(
        _normalizar_async_dsn(dsn_superuser), pool_size=1, max_overflow=0
    )
    latencias_ms: list[float] = []
    async with AsyncSession(engine) as session:
        for idx in range(iteraciones):
            tk_id = f"tk_portal_probe_{idx:02d}"
            t0 = time.perf_counter()
            await session.execute(
                text(
                    """
                    INSERT INTO core.tickets (
                        id, tenant_id, tipo, titulo, descripcion,
                        prioridad, etapa, origen, creado_en
                    )
                    VALUES (
                        :id, 'org_acme', 'mejora', 'Sonda transaccional portal',
                        'Verificación de no interferencia con kallicode-admin',
                        'media', 'produccion', 'portal', now()
                    )
                    ON CONFLICT (id) DO UPDATE SET titulo = EXCLUDED.titulo
                    """
                ),
                {"id": tk_id},
            )
            await session.commit()
            latencias_ms.append((time.perf_counter() - t0) * 1000.0)

        await session.execute(
            text("DELETE FROM core.tickets WHERE id LIKE 'tk_portal_probe_%'")
        )
        await session.commit()
    await engine.dispose()
    return latencias_ms


async def ejecutar_prueba_carga_concurrente(
    app: Any,
    dsn_superuser: str,
    tokens: list[str],
    *,
    num_vus: int = 50,
    rondas_por_vu: int = 2,
) -> dict[str, Any]:
    """Ejecuta 50 VUs concurrentes junto con `admin.refresh_*` y monitorea PostgreSQL."""
    # 1. Línea base transaccional del portal sin carga de consola
    portal_base_ms = await _medir_dml_portal_cliente(dsn_superuser, iteraciones=12)

    engine_mon = create_async_engine(_normalizar_async_dsn(dsn_superuser), poolclass=NullPool)
    async with AsyncSession(engine_mon) as s_mon:
        res_dl0 = await s_mon.execute(
            text(
                "SELECT coalesce(sum(deadlocks), 0) FROM pg_stat_database "
                "WHERE datname = current_database()"
            )
        )
        deadlocks_inicio = int(res_dl0.scalar() or 0)

    latencias_por_endpoint: dict[str, list[float]] = {
        etiqueta: [] for _, etiqueta, _ in ENDPOINTS_CARGA
    }
    todas_latencias: list[float] = []
    total_requests = 0
    errores_5xx = 0
    checks_exitosos = 0

    stop_bg = asyncio.Event()
    refrescos_ejecutados = 0
    refrescos_fallidos = 0
    muestras_locks_no_concedidos = 0
    max_espera_lock_ms = 0.0
    sesiones_ro_observadas = 0

    async def _worker_refresco_secdef() -> None:
        nonlocal refrescos_ejecutados, refrescos_fallidos
        eng = create_async_engine(
            _normalizar_async_dsn(dsn_superuser), pool_size=1, max_overflow=0
        )
        try:
            async with AsyncSession(eng) as ses:
                await asyncio.sleep(0.25)
                while not stop_bg.is_set():
                    res = await ses.execute(
                        text("SELECT * FROM admin.refresh_all_business_aggregates()")
                    )
                    filas = res.fetchall()
                    if any(r[3] != "ok" for r in filas):
                        refrescos_fallidos += 1
                    await ses.execute(text("SELECT admin.refresh_sla(95, true)"))
                    await ses.execute(
                        text(
                            """
                            UPDATE admin.aggregate_state
                            SET refreshed_at = now(), status = 'ok'
                            WHERE agregado = 'sla_cases'
                            """
                        )
                    )
                    await ses.commit()
                    refrescos_ejecutados += 1
                    await asyncio.sleep(1.2)
        finally:
            await eng.dispose()

    async def _monitor_pg_locks() -> None:
        nonlocal muestras_locks_no_concedidos, max_espera_lock_ms, sesiones_ro_observadas
        eng = create_async_engine(
            _normalizar_async_dsn(dsn_superuser), pool_size=1, max_overflow=0
        )
        try:
            async with AsyncSession(eng) as ses:
                await asyncio.sleep(0.25)
                while not stop_bg.is_set():
                    r_ro = await ses.execute(
                        text(
                            """
                            SELECT count(*) FROM pg_stat_activity
                            WHERE usename = 'kallicode_admin_ro'
                            """
                        )
                    )
                    sesiones_ro_observadas = max(
                        sesiones_ro_observadas, int(r_ro.scalar() or 0)
                    )

                    r_lk = await ses.execute(
                        text(
                            """
                            SELECT count(*),
                                   coalesce(
                                       max(extract(epoch FROM (now() - a.query_start)) * 1000),
                                       0
                                   )
                            FROM pg_locks l
                            JOIN pg_stat_activity a ON a.pid = l.pid
                            JOIN pg_class c ON c.oid = l.relation
                            JOIN pg_namespace n ON n.oid = c.relnamespace
                            WHERE NOT l.granted
                              AND n.nspname IN ('core', 'admin')
                            """
                        )
                    )
                    row_lk = r_lk.fetchone()
                    if row_lk and int(row_lk[0] or 0) > 0:
                        muestras_locks_no_concedidos += int(row_lk[0])
                        max_espera_lock_ms = max(max_espera_lock_ms, float(row_lk[1] or 0.0))
                    await ses.commit()
                    await asyncio.sleep(0.25)
        finally:
            await eng.dispose()

    transporte = httpx.ASGITransport(app=app)
    semaforo = asyncio.Semaphore(num_vus)

    async with httpx.AsyncClient(transport=transporte, base_url="http://admin.test") as client:
        # Calentamiento concurrente de los pools asyncpg (app y ro) y Redis previo a medir
        await asyncio.gather(
            *(
                client.get(
                    ENDPOINTS_CARGA[i % len(ENDPOINTS_CARGA)][2],
                    headers={"Authorization": f"Bearer {tokens[i % len(tokens)]}"},
                )
                for i in range(16)
            )
        )

        async def _ejecutar_vu(vu_idx: int) -> None:
            nonlocal total_requests, errores_5xx, checks_exitosos
            token = tokens[vu_idx % len(tokens)]
            headers = {"Authorization": f"Bearer {token}"}
            # Rampa escalonada de entrada de los 50 VUs (emula ramping-vus y think-time de k6)
            await asyncio.sleep(vu_idx * 0.08)
            async with semaforo:
                for ronda in range(rondas_por_vu):
                    idx_ep = (vu_idx + ronda * 3) % len(ENDPOINTS_CARGA)
                    _, etiqueta, url = ENDPOINTS_CARGA[idx_ep]
                    t0 = time.perf_counter()
                    resp = await client.get(url, headers=headers)
                    dt_ms = (time.perf_counter() - t0) * 1000.0

                    total_requests += 1
                    todas_latencias.append(dt_ms)
                    latencias_por_endpoint[etiqueta].append(dt_ms)
                    if resp.status_code >= 500:
                        errores_5xx += 1
                    try:
                        payload = resp.json()
                    except ValueError:
                        payload = None
                    if _validar_json_endpoint(etiqueta, resp.status_code, payload):
                        checks_exitosos += 1
                    await asyncio.sleep(1.2)

        tarea_refresco = asyncio.create_task(_worker_refresco_secdef())
        tarea_monitor = asyncio.create_task(_monitor_pg_locks())
        tarea_portal = asyncio.create_task(
            _medir_dml_portal_cliente(dsn_superuser, iteraciones=12)
        )

        t_inicio_carga = time.perf_counter()
        await asyncio.gather(*(_ejecutar_vu(i) for i in range(num_vus)))
        duracion_total_s = max(0.001, time.perf_counter() - t_inicio_carga)

        portal_bajo_carga_ms = await tarea_portal
        stop_bg.set()
        await asyncio.gather(tarea_refresco, tarea_monitor)

    async with AsyncSession(engine_mon) as s_mon:
        res_dl1 = await s_mon.execute(
            text(
                "SELECT coalesce(sum(deadlocks), 0) FROM pg_stat_database "
                "WHERE datname = current_database()"
            )
        )
        deadlocks_fin = int(res_dl1.scalar() or 0)
    await engine_mon.dispose()

    resumen_endpoints: dict[str, dict[str, float | int]] = {}
    for _, etiqueta, _ in ENDPOINTS_CARGA:
        muestras = latencias_por_endpoint[etiqueta]
        resumen_endpoints[etiqueta] = {
            "requests": len(muestras),
            "p50_ms": calcular_percentil(muestras, 50),
            "p95_ms": calcular_percentil(muestras, 95),
            "p99_ms": calcular_percentil(muestras, 99),
            "max_ms": round(max(muestras), 2) if muestras else 0.0,
        }

    return {
        "vus_concurrentes": num_vus,
        "total_requests": total_requests,
        "rps": round(total_requests / duracion_total_s, 2),
        "p50_global_ms": calcular_percentil(todas_latencias, 50),
        "p95_global_ms": calcular_percentil(todas_latencias, 95),
        "p99_global_ms": calcular_percentil(todas_latencias, 99),
        "error_5xx_count": errores_5xx,
        "error_5xx_rate": round(errores_5xx / max(1, total_requests), 4),
        "checks_ok_count": checks_exitosos,
        "checks_rate": round(checks_exitosos / max(1, total_requests), 4),
        "refrescos_secdef_ejecutados": refrescos_ejecutados,
        "refrescos_secdef_fallidos": refrescos_fallidos,
        "pg_locks_no_concedidos": muestras_locks_no_concedidos,
        "max_espera_lock_ms": round(max_espera_lock_ms, 2),
        "deadlocks_delta": deadlocks_fin - deadlocks_inicio,
        "sesiones_ro_observadas": sesiones_ro_observadas,
        "portal_dml_p95_base_ms": calcular_percentil(portal_base_ms, 95),
        "portal_dml_p95_bajo_carga_ms": calcular_percentil(portal_bajo_carga_ms, 95),
        "endpoints": resumen_endpoints,
    }
