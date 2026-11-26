# Runbook RB-04: Interrupción y Recuperación de Telemetría Operativa del Pipeline

- **Manual Maestro:** [admin_console_ops.md](admin_console_ops.md)
- **Alcance:** Cliente de telemetría interna en [telemetry.py](../../apps/api/src/admin_api/telemetry.py) (`_TelemetryCircuitBreaker`), endpoints `/admin/v1/ops/agents`, `/admin/v1/ops/queues`, `/admin/v1/ops/models` y contrato con Equipo 2.

---

## 1. Distinción Crítica: «Sin Trabajo» vs «Sin Telemetría»

Antes de abrir incidente con Plataforma (Equipo 2), distinguir ambos estados en [ops.py](../../apps/api/src/admin_api/routers/ops.py) y [telemetry.py](../../apps/api/src/admin_api/telemetry.py):

| Condición | Respuesta en `/admin/v1/ops/agents` y `/queues` | Respuesta en `/admin/v1/health` | Diagnóstico |
| :--- | :--- | :--- | :--- |
| **Sin trabajo en el pipeline** | HTTP `200`, `telemetria.disponible: true`, `telemetria_desde` reciente, contadores en `0`. | `estado: "ok"`, `dependencias.telemetria: true` | **Normal.** No hay jobs activos; las líneas en `core.production_lines` se leen directamente en BD `RO`. |
| **Sin latidos en la ventana (`telemetria_desde: null`)** | HTTP `200`, `telemetria.disponible: false`, contadores en `null` (nunca `0`). | `dependencias.telemetria: true` (servicio E2 responde HTTP 200) | Revisar si el recolector de Equipo 2 está recibiendo latidos en la ventana solicitada. |
| **Servicio E2 caído, timeout (> 2s/3s) o señal > `KC_ADMIN_TELEMETRY_MAX_AGE_S` (900 s)** | HTTP `503` con código **`TELEMETRIA_NO_DISPONIBLE`** en `/ops/agents`, `/ops/queues` y `/ops/models`. | HTTP `200` con **`estado: "degradado"`** (`dependencias.telemetria: false`) | **Incidente en telemetría E2 o enlace VNet.** Las pantallas de negocio y `GET /admin/v1/ops/sla` siguen operativas al 100%. |

---

## 2. Diagnóstico

1. Consultar salud y métricas desde red privada:
   ```bash
   curl -sS https://admin.internal.kallicode.com/admin/v1/health
   curl -sS https://admin.internal.kallicode.com/admin/v1/metrics | grep admin_dependency_failures_total
   ```
   Observar:
   - `dependencias.telemetria == false` mientras `dependencias.postgres == true` y `dependencias.lectura_analitica == true`.
   - Contadores `admin_dependency_failures_total{dependency="telemetria"}` y `admin_dependency_failures_total{dependency="telemetry_circuit_breaker"}`.
2. Revisar logs estructurados de la API:
   - `admin.telemetria.inalcanzable` / `admin.telemetria.error_servidor` / `admin.telemetria.rechazada` / `admin.telemetria.payload_invalido`.
   - `admin.ops.telemetria_desactualizada` (> `KC_ADMIN_TELEMETRY_WARN_AGE_S` = `300` s) o `admin.telemetria.desactualizada` (> `KC_ADMIN_TELEMETRY_MAX_AGE_S` = `900` s).
   - `admin.ops.telemetria_circuito_abierto`: ocurre tras `KC_ADMIN_TELEMETRY_CB_FAILURE_THRESHOLD` (`3`) fallos consecutivos y mantiene el circuito abierto `KC_ADMIN_TELEMETRY_CB_COOLDOWN_S` (`30.0` s) para no agotar conexiones.
3. Verificar la URL interna configurada (`KC_PIPELINE_TELEMETRY_URL` tiene prioridad sobre `KC_ADMIN_TELEMETRY_BASE_URL`) y confirmar que no apunta a `localhost` fuera de desarrollo local.

---

## 3. Acción Correctiva y Recuperación

1. **Si el fallo es de configuración/red en `kallicode-admin`**:
   - Corregir `KC_ADMIN_TELEMETRY_BASE_URL` o `KC_PIPELINE_TELEMETRY_URL` apuntando al endpoint interno privado de Equipo 2 (`/internal/v1`), verificar resolución Private DNS en la VNet y asegurarse de que la clave compartida `KC_JWT_PRIVATE_KEY` usada por `emitir_svc_token("admin-console", tenant_id="plataforma")` sea válida para el servicio receptor.
2. **Si el fallo es del servicio de telemetría (Equipo 2)**:
   - Escalar a Equipo 2 conservando operativa la consola de negocio y `/admin/v1/ops/sla` (que permanecen disponibles con `estado: "degradado"` en `/admin/v1/health`).
3. **Recuperación automática del Circuit Breaker**:
   - Una vez restablecido el endpoint interno de Equipo 2, **no es necesario reiniciar la API**: tras cumplirse el enfriamiento de `30.0` s (`KC_ADMIN_TELEMETRY_CB_COOLDOWN_S`), la siguiente petición de sonda a `/admin/v1/ops/agents` o `/admin/v1/ops/queues` cierra automáticamente el circuito (`_breaker.record_success()`).
   - Comprobar también que el worker interno `python -m admin_workers.main` sigue ejecutando `refrescar_agregados` y `evaluar_sla` con normalidad.

---

## 4. Verificación Post-Incidente

1. Verificar `GET /admin/v1/health` → HTTP `200`, `estado: "ok"`, `dependencias.telemetria: true`.
2. Verificar HTTP `200` en `GET /admin/v1/ops/agents?ventana=1h`, `GET /admin/v1/ops/queues` y `GET /admin/v1/ops/models?ventana=24h`.
3. Confirmar que dejan de incrementarse `admin_dependency_failures_total{dependency="telemetria"}` y `admin_dependency_failures_total{dependency="telemetry_circuit_breaker"}`.
