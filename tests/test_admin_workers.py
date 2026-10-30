"""Pruebas de integración del worker asíncrono y elección de líder (KC-ADM-B2-10).

Verifica:
1. Refresco normal de agregados de negocio mediante la función SQL
   admin.refresh_all_business_aggregates() y persistencia en admin.aggregate_state.
2. Elección de líder (Leader Election) mediante pg_try_advisory_xact_lock:
   - Réplica líder ejecuta el ciclo con éxito.
   - Réplica secundaria omite silenciosamente registrando admin.worker.skipping_not_leader.
   - Liberación automática del bloqueo al terminar la transacción.
3. Monitoreo de frescura y emisión de alarma WARN admin.business.frescura_alta cuando
   la antigüedad supera el umbral configurado (6 horas / 21,600 s).
4. Resiliencia ante fallos transitorios de base de datos o agregados fallidos.
5. Intervalo de ejecución configurable mediante KC_ADMIN_REFRESH_INTERVAL_S.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any
from unittest.mock import AsyncMock

import pytest
from admin_api.db import admin_session, read_session, todos
from admin_api.settings import get_admin_settings
from admin_workers.lider import (
    LOCK_ID_AGREGADOS,
    ejecutar_con_lider,
    intentar_liderazgo_xact,
)
from admin_workers.main import (
    _bucle,
    _parar,
    comprobar_frescura_agregados,
    refrescar_agregados,
)


@pytest.mark.integracion
@pytest.mark.asyncio
async def test_refresco_agregados_ejecucion_normal(entorno: None) -> None:
    """Verifica que el ciclo con líder actualice los agregados en admin.aggregate_state."""
    exito = await ejecutar_con_lider("refrescar_agregados", refrescar_agregados)
    assert exito is True

    async with read_session() as rdb:
        filas = await todos(rdb, "SELECT * FROM admin.aggregate_state ORDER BY agregado")

    agregados_esperados = {
        "customer_state",
        "monthly_business",
        "pipeline_daily",
        "tokens_daily",
        "upgrade_requests",
        "usage_cycle",
    }
    agregados_obtenidos = {f["agregado"] for f in filas}
    assert agregados_esperados.issubset(agregados_obtenidos)

    for f in filas:
        if f["agregado"] in agregados_esperados:
            assert f["status"] == "ok"
            assert f["refreshed_at"] is not None
            assert f["duration_ms"] is not None and f["duration_ms"] >= 0
            assert f["rows_total"] is not None and f["rows_total"] >= 0


@pytest.mark.integracion
@pytest.mark.asyncio
async def test_eleccion_lider_advisory_lock_concurrente(
    entorno: None, caplog: pytest.LogCaptureFixture
) -> None:
    """Verifica la exclusión mutua de réplicas concurrentes con pg_try_advisory_xact_lock."""
    caplog.set_level(logging.INFO, logger="kallicode")

    # Sesión 1 adquiere el bloqueo transaccional
    async with admin_session() as db1:
        es_lider_1 = await intentar_liderazgo_xact(db1, LOCK_ID_AGREGADOS)
        assert es_lider_1 is True

        # Sesión 2 intenta ejecutar el mismo trabajo mientras la sesión 1 sigue abierta
        ejecutado_en_replica_2 = False

        async def cuerpo_replica_2(sesion: Any) -> None:
            nonlocal ejecutado_en_replica_2
            ejecutado_en_replica_2 = True

        resultado_2 = await ejecutar_con_lider("refrescar_agregados", cuerpo_replica_2)
        assert resultado_2 is False
        assert ejecutado_en_replica_2 is False

        # Verifica que se haya registrado el log de omitir sin ser líder
        eventos_info = [r.getMessage() for r in caplog.records]
        assert "admin.worker.skipping_not_leader" in eventos_info

    # Una vez terminada la transacción de la sesión 1, la réplica 2 puede adquirir el bloqueo
    resultado_3 = await ejecutar_con_lider("refrescar_agregados", cuerpo_replica_2)
    assert resultado_3 is True
    assert ejecutado_en_replica_2 is True


@pytest.mark.asyncio
async def test_alerta_frescura_alta_mayor_6_horas(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Emite WARN admin.business.frescura_alta cuando el último refresco supera 6 horas."""
    caplog.set_level(logging.WARNING, logger="kallicode")

    filas_simuladas = [
        {
            "agregado": "customer_state",
            "rows_total": 50,
            "duration_ms": 120,
            "refreshed_at": "2026-10-29T10:00:00Z",
            "status": "ok",
            "error": None,
            "antiguedad_s": 25_200,  # 7 horas = 25,200 s > 21,600 s
        },
        {
            "agregado": "usage_cycle",
            "rows_total": 30,
            "duration_ms": 80,
            "refreshed_at": "2026-10-29T16:00:00Z",
            "status": "ok",
            "error": None,
            "antiguedad_s": 3_600,  # 1 hora = 3,600 s <= 21,600 s
        },
    ]

    async def mock_todos(
        sesion: Any, sql: str, *args: Any, **kwargs: Any
    ) -> list[dict[str, Any]]:
        return filas_simuladas

    monkeypatch.setattr("admin_workers.main.todos", mock_todos)

    desactualizados = await comprobar_frescura_agregados(AsyncMock(), max_antiguedad_s=21_600)
    assert len(desactualizados) == 1
    assert desactualizados[0]["agregado"] == "customer_state"

    eventos_warn = [r.getMessage() for r in caplog.records]
    assert "admin.business.frescura_alta" in eventos_warn


@pytest.mark.asyncio
async def test_alerta_agregados_fallidos(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Emite log CRITICAL admin.agregado.fallidos si falla el recálculo de agregados."""
    caplog.set_level(logging.CRITICAL, logger="kallicode")

    # Simulamos retorno de agregados con uno en estado fallido
    async def mock_todos(db: Any, sql: str, *args: Any, **kwargs: Any) -> list[dict[str, Any]]:
        if "refresh_all_business_aggregates" in sql:
            return [
                {"agregado": "customer_state", "filas": 10, "ms": 45, "estado": "ok"},
                {"agregado": "pipeline_daily", "filas": 0, "ms": 10, "estado": "fallido"},
            ]
        return []

    async def mock_uno(db: Any, sql: str, *args: Any, **kwargs: Any) -> dict[str, Any]:
        return {"n": 0}

    monkeypatch.setattr("admin_workers.main.todos", mock_todos)
    monkeypatch.setattr("admin_workers.main.uno", mock_uno)
    monkeypatch.setattr("admin_workers.main.comprobar_frescura_agregados", AsyncMock())

    await refrescar_agregados(None)

    eventos_criticos = [r.getMessage() for r in caplog.records]
    assert "admin.agregado.fallidos" in eventos_criticos


@pytest.mark.integracion
@pytest.mark.asyncio
async def test_resiliencia_ejecutar_con_lider_ante_error(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Verifica que ejecutar_con_lider registre admin.worker.fallido ante errores."""
    caplog.set_level(logging.ERROR, logger="kallicode")

    async def cuerpo_con_error(sesion: Any) -> None:
        raise ConnectionResetError("Conexión perdida con la base de datos")

    with pytest.raises(ConnectionResetError):
        await ejecutar_con_lider("refrescar_agregados", cuerpo_con_error)

    eventos_error = [r.getMessage() for r in caplog.records]
    assert "admin.worker.fallido" in eventos_error


@pytest.mark.asyncio
async def test_bucle_runner_no_muere_por_excepcion(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verifica que el bucle del runner no se interrumpa ante excepciones transitorias."""
    llamadas = 0

    async def mock_con_lider(nombre: str, fn: Any) -> bool:
        await fn(None)
        return True

    monkeypatch.setattr("admin_workers.main._con_lider", mock_con_lider)

    async def fallo_transitorio(sesion: Any) -> None:
        nonlocal llamadas
        llamadas += 1
        raise RuntimeError("Fallo transitorio")

    _parar.clear()

    async def detener_despues() -> None:
        while llamadas < 2:
            await asyncio.sleep(0.01)
        _parar.set()

    tarea_detener = asyncio.create_task(detener_despues())
    try:
        await _bucle("refrescar_agregados", fallo_transitorio, intervalo=1)
    finally:
        tarea_detener.cancel()
        _parar.clear()

    assert llamadas >= 2


def test_intervalo_refresco_configurable(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verifica la configuración de KC_ADMIN_REFRESH_INTERVAL_S."""
    monkeypatch.setenv("KC_ADMIN_REFRESH_INTERVAL_S", "450")
    get_admin_settings.cache_clear()
    s = get_admin_settings()
    assert s.refresh_interval_s == 450
    get_admin_settings.cache_clear()
