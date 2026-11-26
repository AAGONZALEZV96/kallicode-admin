"""Pruebas automatizadas de carga, umbrales k6 y no-contención PostgreSQL (KC-ADM-B6-07).

1. Pruebas unitarias rápidas (sin BD):
   - Validación estática del script `tests/load/k6_admin_load.js`: verifica los 3
     escenarios obligatorios, meseta de 50 VUs, rotación de tokens por `__VU`,
     cobertura de los 8 endpoints de negocio/operaciones/salud y umbrales SLO
     (`p(95)<500`, `rate<0.01`, `rate>=0.99`).
2. Pruebas de integración (`@pytest.mark.integracion`):
   - Siembra volumen multi-tenant sintético y 50 operadores staff (`seed_and_tokens.py`).
   - Ejecuta 50 VUs concurrentes contra la API junto con ejecuciones paralelas de
     `admin.refresh_all_business_aggregates()` y `admin.refresh_sla(95, true)`
     (`SECURITY DEFINER`, propietario `kallicode_admin_agg`) y escrituras DML del
     portal cliente (`core.tickets`).
   - Verifica p95 < 500 ms global y por endpoint, 0% errores 5xx, >= 99% checks,
     0 deadlocks, uso activo de `kallicode_admin_ro` y no degradación del portal.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx
from admin_api.settings import get_admin_settings

from tests.load.orchestrate_load import (
    ENDPOINTS_CARGA,
    calcular_percentil,
    ejecutar_prueba_carga_concurrente,
    payload_telemetria_fresca,
)
from tests.load.seed_and_tokens import (
    limpiar_datos_carga,
    sembrar_datos_carga_y_tokens,
)

ROOT = Path(__file__).resolve().parent.parent
K6_SCRIPT = ROOT / "tests" / "load" / "k6_admin_load.js"


# =============================================================================
# 1. Pruebas unitarias (sin BD): verificación estática de k6_admin_load.js
# =============================================================================
def test_k6_script_existe_y_declara_tres_escenarios_y_50_vus() -> None:
    """El script k6 debe definir los 3 escenarios del ticket y la meseta de 50 VUs."""
    assert K6_SCRIPT.is_file(), f"No existe el script k6 en {K6_SCRIPT}"
    contenido = K6_SCRIPT.read_text(encoding="utf-8")

    for escenario in (
        "escenario_1_agregados_negocio",
        "escenario_2_ops_polling",
        "escenario_3_lectura_bajo_refresco_secdef",
    ):
        assert escenario in contenido, f"Falta escenario obligatorio en k6: {escenario}"

    assert re.search(
        r"target\s*:\s*50\b", contenido
    ), "El escenario principal de k6 debe alcanzar la meseta de 50 VUs concurrentes"
    assert "SharedArray" in contenido
    assert "__VU" in contenido


def test_k6_script_cubre_endpoints_y_thresholds_slo_innegociables() -> None:
    """Verifica que k6_admin_load.js incluya todos los endpoints y umbrales p95 < 500ms."""
    contenido = K6_SCRIPT.read_text(encoding="utf-8")

    rutas_esperadas = (
        "/admin/v1/business/summary",
        "/admin/v1/business/overview",
        "/admin/v1/business/customers",
        "/admin/v1/business/usage/tokens",
        "/admin/v1/ops/agents",
        "/admin/v1/ops/models",
        "/admin/v1/ops/sla",
        "/admin/v1/health",
    )
    for ruta in rutas_esperadas:
        assert ruta in contenido, f"El script k6 no ejercita la ruta requerida: {ruta}"

    assert "p(95)<500" in contenido
    assert "rate<0.01" in contenido
    assert "rate>=0.99" in contenido


def test_calcular_percentil_determinista() -> None:
    """Valida el cálculo de percentiles p50, p95 y p99 para el informe de carga."""
    assert calcular_percentil([], 95) == 0.0
    muestra = [float(i) for i in range(1, 101)]
    assert calcular_percentil(muestra, 50) == 50.0
    assert calcular_percentil(muestra, 95) == 95.0
    assert calcular_percentil(muestra, 99) == 99.0


# =============================================================================
# 2. Prueba de integración (PostgreSQL 16 real): 50 VUs + SECURITY DEFINER
# =============================================================================
@pytest.mark.integracion
async def test_carga_50_vus_concurrentes_con_refresco_secdef_sin_contencion(
    app: Any,
    dsn: str,
    esquema: str,
    entorno: None,
) -> None:
    """Ejecuta 50 VUs concurrentes mientras corren refresh_* y DML de portal cliente."""
    datos_seed = await sembrar_datos_carga_y_tokens(
        dsn,
        num_tenants=20,
        num_staff=50,
        guardar_archivo=False,
    )
    assert datos_seed["tenants_count"] == 20
    assert len(datos_seed["tokens"]) == 50

    s = get_admin_settings()
    base_telemetria = s.resolve_telemetry_base_url()
    payload_e2 = payload_telemetria_fresca("1h")

    try:
        with respx.mock(assert_all_called=False) as mock_e2:
            mock_e2.get(f"{base_telemetria}/telemetry/agents").mock(
                return_value=httpx.Response(200, json=payload_e2)
            )
            mock_e2.get(f"{base_telemetria}/telemetry/providers").mock(
                return_value=httpx.Response(200, json=payload_e2)
            )
            mock_e2.get(f"{base_telemetria}/telemetry/queues").mock(
                return_value=httpx.Response(200, json=payload_e2)
            )

            metricas = await ejecutar_prueba_carga_concurrente(
                app,
                dsn,
                datos_seed["tokens"],
                num_vus=50,
                rondas_por_vu=2,
            )

        # 1) SLOs globales innegociables
        assert metricas["vus_concurrentes"] == 50
        assert metricas["total_requests"] == 100
        assert metricas["error_5xx_count"] == 0, f"Errores 5xx detectados: {metricas}"
        assert metricas["error_5xx_rate"] < 0.01
        assert metricas["checks_rate"] >= 0.99, f"Checks por debajo de 99%: {metricas}"
        assert (
            metricas["p95_global_ms"] < 500.0
        ), f"Latencia p95 global ({metricas['p95_global_ms']} ms) excede el SLO de 500 ms"

        # 2) SLO p95 < 500 ms en cada uno de los 8 endpoints
        for _, etiqueta, _ in ENDPOINTS_CARGA:
            ep_stats = metricas["endpoints"][etiqueta]
            assert int(ep_stats["requests"]) > 0
            assert (
                float(ep_stats["p95_ms"]) < 500.0
            ), f"Endpoint {etiqueta} superó 500 ms p95: {ep_stats}"

        # 3) Ejecución concurrente de SECURITY DEFINER y cero contención / deadlocks
        assert metricas["refrescos_secdef_ejecutados"] >= 1
        assert metricas["refrescos_secdef_fallidos"] == 0
        assert metricas["deadlocks_delta"] == 0
        assert metricas["sesiones_ro_observadas"] >= 1
        # Las escrituras del portal cliente siguen por debajo de 500 ms p95 bajo carga
        assert metricas["portal_dml_p95_bajo_carga_ms"] < 500.0

        # 4) Verificación adicional sin telemetría de E2 levantada (circuit breaker activo):
        #    /admin/v1/ops/sla, /admin/v1/business/* y /admin/v1/health (estado 'degradado')
        #    funcionan 100% sobre PostgreSQL RO sin depender del backend E2.
        with respx.mock(assert_all_called=False) as mock_caido:
            mock_caido.get(f"{base_telemetria}/telemetry/agents").mock(
                side_effect=httpx.ConnectError("E2 telemetry aun no desplegado")
            )
            transporte = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(
                transport=transporte, base_url="http://admin.test"
            ) as c_deg:
                headers_vu0 = {"Authorization": f"Bearer {datos_seed['tokens'][0]}"}
                for _ in range(3):
                    r_ag = await c_deg.get(
                        "/admin/v1/ops/agents?ventana=1h", headers=headers_vu0
                    )
                    assert r_ag.status_code == 503
                    assert r_ag.json()["error"]["codigo"] == "TELEMETRIA_NO_DISPONIBLE"
                r_sla_deg = await c_deg.get("/admin/v1/ops/sla", headers=headers_vu0)
                assert r_sla_deg.status_code == 200
                r_health_deg = await c_deg.get("/admin/v1/health", headers=headers_vu0)
                assert r_health_deg.status_code == 200
                assert r_health_deg.json()["estado"] == "degradado"
    finally:
        await limpiar_datos_carga(dsn)
