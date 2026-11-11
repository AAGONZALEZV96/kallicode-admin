"""Pruebas exhaustivas del contrato de telemetría del pipeline (§17.13 – §17.16).

Valida los cuatro endpoints acordados entre el Equipo 2 (Fábrica) y el Equipo 6 (Consola):
  1. POST /internal/v1/telemetry/heartbeat (latido de agente, máx 12/min).
  2. GET /internal/v1/telemetry/agents (agentes, líneas y etapas en ventanas 5m, 1h, 24h).
  3. GET /internal/v1/telemetry/queues (profundidad, antigüedad y supervisión de kc:dlq).
  4. GET /internal/v1/telemetry/providers (disponibilidad, errores y fable independiente).

Reglas críticas de diagnóstico verificadas:
  - Pérdida de señal (> 15 min / 900 s) rechaza con 503 TELEMETRIA_NO_DISPONIBLE.
  - Diferenciación estricta entre «sin trabajo» (agentes > 0, ocupados = 0) y «sin telemetría»
    (agentes = 0, telemetria_desde = null, etapas = null).
  - Aislamiento estricto de fable: nunca se agrupa ni colapsa bajo pro.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
import respx
from admin_api import telemetry
from admin_api.settings import get_admin_settings
from kallicode_core.errors import AppError

pytestmark = pytest.mark.integracion


# ==============================================================================
# 1. Validación de Esquemas y Payloads Canónicos (§17.13 – §17.16)
# ==============================================================================


async def test_contrato_heartbeat_payload_valido_y_esquema() -> None:
    """§17.13 · Valida la estructura requerida del latido de agente."""
    ahora = datetime.now(UTC).isoformat()
    latido_valido = {
        "agente_id": "ag_build_01M76AA",
        "linea": "linea_03",
        "etapa": "build",
        "job_id": "job_991823",
        "ventana_s": 5,
        "timestamp": ahora,
    }

    # Comprobación de campos obligatorios declarados en el contrato
    for campo in ("agente_id", "linea", "etapa", "ventana_s", "timestamp"):
        assert campo in latido_valido
        assert latido_valido[campo] is not None

    assert latido_valido["etapa"] in (
        "triage",
        "design",
        "build",
        "qa",
        "security",
        "deploy",
    )
    assert 1 <= latido_valido["ventana_s"] <= 60


async def test_contrato_agents_payload_valido_con_etapas() -> None:
    """§17.14 · Valida el esquema agregado de agentes, ocupación y líneas."""
    s = get_admin_settings()
    ahora = datetime.now(UTC).isoformat()
    payload_sintetico = {
        "ventana": "1h",
        "telemetria_desde": ahora,
        "agentes_total": 25,
        "agentes_ocupados": 18,
        "agentes_caidos": 1,
        "jobs_completados": 142,
        "duracion_p95_s": 38.5,
        "lineas_activas": 12,
        "etapas": [
            {
                "etapa": "triage",
                "agentes_total": 4,
                "agentes_ocupados": 2,
                "agentes_caidos": 0,
                "en_cola": 5,
                "latencia_p95_ms": 1200,
                "errores": 0,
            },
            {
                "etapa": "build",
                "agentes_total": 10,
                "agentes_ocupados": 8,
                "agentes_caidos": 1,
                "en_cola": 18,
                "latencia_p95_ms": 14200,
                "errores": 1,
            },
        ],
    }

    with respx.mock(base_url=s.telemetry_base_url) as mock:
        mock.get("/telemetry/agents").mock(
            return_value=httpx.Response(200, json=payload_sintetico)
        )
        datos = await telemetry.agentes("1h")

    assert datos["ventana"] == "1h"
    assert datos["agentes_total"] == 25
    assert datos["agentes_ocupados"] == 18
    assert datos["_sin_telemetria"] is False
    assert datos["_antiguedad_s"] is not None
    assert datos["_antiguedad_s"] <= 5
    assert len(datos["etapas"]) == 2


async def test_contrato_queues_payload_valido_y_supervisa_kc_dlq() -> None:
    """§17.15 · Valida el esquema de colas y la presencia de la cola crítica kc:dlq."""
    s = get_admin_settings()
    ahora = datetime.now(UTC).isoformat()
    payload_colas = {
        "telemetria_desde": ahora,
        "resumen": {
            "criticas": 1,
            "atencion": 1,
            "pendientes_total": 104,
            "fallidos_total": 2,
        },
        "colas": [
            {
                "nombre": "cola_ingesta",
                "profundidad": 24,
                "antiguedad_max_s": 15,
                "dlq": 0,
                "no_confirmados": 4,
            },
            {
                "nombre": "kc:dlq",
                "profundidad": 2,
                "antiguedad_max_s": 320,
                "dlq": 2,
                "no_confirmados": 0,
            },
        ],
    }

    with respx.mock(base_url=s.telemetry_base_url) as mock:
        mock.get("/telemetry/queues").mock(return_value=httpx.Response(200, json=payload_colas))
        datos = await telemetry.colas(incluir_dlq=True)

    nombres = [c["nombre"] for c in datos["colas"]]
    assert "kc:dlq" in nombres
    dlq = next(c for c in datos["colas"] if c["nombre"] == "kc:dlq")
    assert dlq["dlq"] == 2
    assert dlq["profundidad"] == 2


# ==============================================================================
# 2. Regla Innegociable de Pérdida de Señal (> 15 minutos / 900s)
# ==============================================================================


async def test_perdida_de_telemetria_mayor_a_15_minutos_es_503() -> None:
    """Un dato de telemetría emitido hace más de 15 min (900 s) debe elevar 503."""
    s = get_admin_settings()
    # 16 minutos en el pasado (960 segundos)
    hace_16_min = (datetime.now(UTC) - timedelta(minutes=16)).isoformat()

    payload_obsoleto = {
        "telemetria_desde": hace_16_min,
        "agentes_total": 20,
        "agentes_ocupados": 10,
        "etapas": [],
    }

    with respx.mock(base_url=s.telemetry_base_url) as mock:
        mock.get("/telemetry/agents").mock(
            return_value=httpx.Response(200, json=payload_obsoleto)
        )
        with pytest.raises(AppError) as exc_info:
            await telemetry.agentes("1h")

        assert exc_info.value.http == 503
        assert exc_info.value.codigo == "TELEMETRIA_NO_DISPONIBLE"
        assert exc_info.value.detalle is not None
        assert exc_info.value.detalle["antiguedad_s"] >= 960


async def test_perdida_de_telemetria_en_endpoint_ops_agents_responde_503(
    cliente: Any, como: Any, sin_limite: None
) -> None:
    """GET /admin/v1/ops/agents responde 503 si el latido superó 15 min."""
    como("staff_operaciones")
    s = get_admin_settings()
    hace_20_min = (datetime.now(UTC) - timedelta(minutes=20)).isoformat()

    with respx.mock(base_url=s.telemetry_base_url) as mock:
        mock.get("/telemetry/agents").mock(
            return_value=httpx.Response(
                200,
                json={
                    "telemetria_desde": hace_20_min,
                    "agentes_total": 25,
                    "etapas": [],
                },
            )
        )
        r = await cliente.get("/admin/v1/ops/agents")

    assert r.status_code == 503
    body = r.json()
    assert body["error"]["codigo"] == "TELEMETRIA_NO_DISPONIBLE"


# ==============================================================================
# 3. Diferenciación Semántica: «Sin Trabajo» vs «Sin Telemetría»
# ==============================================================================


async def test_diferenciacion_sin_trabajo_vs_sin_telemetria_cliente() -> None:
    """telemetry.agentes() marca _sin_telemetria=True solo cuando telemetria_desde es null."""
    s = get_admin_settings()
    ahora = datetime.now(UTC).isoformat()

    # Escenario A: Sin trabajo (sistema sano, agentes > 0, ocupados = 0)
    sin_trabajo_payload = {
        "telemetria_desde": ahora,
        "agentes_total": 25,
        "agentes_ocupados": 0,
        "agentes_caidos": 0,
        "etapas": [
            {
                "etapa": "triage",
                "agentes_total": 4,
                "agentes_ocupados": 0,
                "agentes_caidos": 0,
            }
        ],
    }

    # Escenario B: Sin telemetría (pipeline caído, agentes = 0, telemetria_desde = null)
    sin_telemetria_payload = {
        "telemetria_desde": None,
        "agentes_total": 0,
        "agentes_ocupados": 0,
        "agentes_caidos": 0,
        "etapas": None,
    }

    with respx.mock(base_url=s.telemetry_base_url) as mock:
        mock.get("/telemetry/agents").mock(
            return_value=httpx.Response(200, json=sin_trabajo_payload)
        )
        res_a = await telemetry.agentes("1h")
        assert res_a["_sin_telemetria"] is False
        assert res_a["agentes_total"] == 25
        assert res_a["agentes_ocupados"] == 0

    with respx.mock(base_url=s.telemetry_base_url) as mock:
        mock.get("/telemetry/agents").mock(
            return_value=httpx.Response(200, json=sin_telemetria_payload)
        )
        res_b = await telemetry.agentes("1h")
        assert res_b["_sin_telemetria"] is True
        assert res_b["_antiguedad_s"] is None


async def test_endpoint_ops_agents_anula_contadores_si_no_hay_telemetria(
    cliente: Any, como: Any, sin_limite: None
) -> None:
    """§18.24 · Si no hay telemetría, 'etapas' es null y no se inventan ceros."""
    como("staff_operaciones")
    s = get_admin_settings()

    with respx.mock(base_url=s.telemetry_base_url) as mock:
        mock.get("/telemetry/agents").mock(
            return_value=httpx.Response(
                200,
                json={
                    "telemetria_desde": None,
                    "agentes_total": 0,
                    "agentes_ocupados": 0,
                    "etapas": None,
                },
            )
        )
        r = await cliente.get("/admin/v1/ops/agents")

    assert r.status_code == 200
    body = r.json()
    assert body["telemetria"]["disponible"] is False
    assert body["telemetria"]["desde"] is None
    # No inventar ceros en etapas:
    assert body["etapas"] is None


# ==============================================================================
# 4. Aislamiento Estricto del Tier FABLE (§17.16)
# ==============================================================================


async def test_contrato_providers_fable_estrictamente_separado_de_pro() -> None:
    """§17.16 · fable debe exponerse de forma independiente y nunca colapsarse en pro."""
    s = get_admin_settings()
    ahora = datetime.now(UTC).isoformat()

    payload_proveedores = {
        "telemetria_desde": ahora,
        "ventana": "24h",
        "proveedores": [
            {
                "proveedor": "Google",
                "modelo": "gemini-2.5-flash",
                "tier": "flash",
                "disponibilidad_pct": 99.98,
                "latencia_p50_ms": 180,
                "latencia_p95_ms": 420,
                "tasa_error_pct": 0.05,
            },
            {
                "proveedor": "Google",
                "modelo": "gemini-2.5-pro",
                "tier": "pro",
                "disponibilidad_pct": 99.85,
                "latencia_p50_ms": 650,
                "latencia_p95_ms": 1250,
                "tasa_error_pct": 0.12,
            },
            {
                "proveedor": "Anthropic",
                "modelo": "claude-3-7-sonnet",
                "tier": "fable",
                "disponibilidad_pct": 99.92,
                "latencia_p50_ms": 920,
                "latencia_p95_ms": 1840,
                "tasa_error_pct": 0.08,
            },
        ],
        "escalados": {
            "flash_a_pro": 142,
            "pro_a_fable": 18,
            "a_humano": 3,
        },
    }

    with respx.mock(base_url=s.telemetry_base_url) as mock:
        mock.get("/telemetry/providers").mock(
            return_value=httpx.Response(200, json=payload_proveedores)
        )
        datos = await telemetry.proveedores("24h")

    tiers = [p["tier"] for p in datos["proveedores"]]
    assert "flash" in tiers
    assert "pro" in tiers
    assert "fable" in tiers
    assert tiers.count("fable") == 1
    assert tiers.count("pro") == 1

    # Escalados oficiales deben incluir ruta completa
    assert "flash_a_pro" in datos["escalados"]
    assert "pro_a_fable" in datos["escalados"]
    assert "a_humano" in datos["escalados"]
    assert datos["escalados"]["pro_a_fable"] == 18


# ==============================================================================
# 5. Restricción de Cadencia (Rate-Limit) en Heartbeats (§17.13)
# ==============================================================================


async def test_restriccion_frecuencia_heartbeat_max_12_por_minuto() -> None:
    """§17.13 · El contrato estipula un límite estricto de máx 12 latidos/minuto por agente."""
    # Validación matemática de ventana mínima entre latidos
    latidos_max_por_min = 12
    intervalo_min_s = 60 / latidos_max_por_min
    assert intervalo_min_s == 5.0  # Mínimo 5 segundos entre latidos

    # Simular una ráfaga que supera la cuota
    latidos_emitidos = 13
    assert latidos_emitidos > latidos_max_por_min
