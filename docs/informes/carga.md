# Informe de Pruebas de Carga y No-Contención PostgreSQL (KC-ADM-B6-07)

- **Ticket:** `[KC-ADM-B6-07]` — Pruebas de Carga con k6 sobre Funciones `SECURITY DEFINER` y Agregados
- **Épica:** `EAD6` — Endurecimiento, Red Privada, Observabilidad & Release MVP (Hito M6)
- **Responsable:** ADM1 (Lead Full-Stack & Arquitectura · Equipo E6)
- **Estado del Dictamen:** **APROBADO — Latencia global `p95 = 314.59 ms` (< 500 ms), `0%` errores 5xx, `100%` checks exitosos, `0` deadlocks y `0` bloqueos no concedidos sobre `core.*`**
- **Artefactos verificables:** [k6_admin_load.js](../../tests/load/k6_admin_load.js), [seed_and_tokens.py](../../tests/load/seed_and_tokens.py), [orchestrate_load.py](../../tests/load/orchestrate_load.py) y [test_load_performance.py](../../tests/test_load_performance.py)

---

## 1. Objetivo y Riesgo Arquitectónico Evaluado

El riesgo principal de rendimiento en `kallicode-admin` no es únicamente la latencia percibida por el personal interno, sino que las **consultas analíticas cross-tenant** y los **refrescos periódicos de agregados mediante funciones `SECURITY DEFINER`** (`admin.refresh_*`, ejecutadas con el rol `kallicode_admin_agg`) compitan por bloqueos (`locks`) o saturen el motor PostgreSQL 16 que atiende las transacciones del portal de clientes (`core.*`).

Esta campaña verifica empíricamente bajo **50 usuarios virtuales (VUs) concurrentes**:
1. Que todas las lecturas analíticas de negocio y operaciones se ejecuten a través del pool de solo lectura (`KC_ADMIN_DATABASE_URL_RO` / rol `kallicode_admin_ro`, `pool_size_ro = 10`, `statement_timeout = 30000 ms`, `transaction_read_only = on`).
2. Que la ejecución simultánea de `admin.refresh_all_business_aggregates()` y `admin.refresh_sla(95, true)` (`SECURITY DEFINER`) no bloquee las lecturas concurrentes ni degrade las escrituras DML del portal sobre `core.tickets`.
3. Que todos los endpoints bajo estrés cumplan el SLO innegociable: **`p95 < 500 ms`**, **tasa de error HTTP 5xx `< 1%`** y **tasa de éxito en checks JSON `>= 99%`**.

---

## 2. Topología de Prueba y Semilla Sintética Multi-Tenant

### 2.1 Volumen sintético sembrado (`tests/load/seed_and_tokens.py`)
- **Organizaciones y planes:** 20–24 organizaciones activas (`org_load_00`..`org_load_23`) distribuidas uniformemente entre los planes `starter`, `growth` y `enterprise` (más las organizaciones base `org_acme` y `org_globex`).
- **Actividad por tenant:** suscripciones activas, ciclos de facturación (`core.usage_cycles`), consumo de tokens por tier (`flash`, `pro`, `fable` en `core.usage_tokens`), tickets (`core.tickets`), ejecuciones (`core.jobs`) y tramos cronológicos de reloj SLA (`admin.sla_clock_segments`).
- **Pool de 50 identidades de personal (`st_load_00`..`st_load_49`)**:
  - Dado que [deps.py](../../apps/api/src/admin_api/deps.py) impone rate limiting por empleado (`limite_rl4 = 300 req/min` y `limite_vivo = 60 req/min` en `/ops/agents` y `/ops/models`), cada VU de los 50 concurrentes recibe su propio JWT RS256 válido con `typ="staff"`, `iss="kallicode-admin"`, `aud="admin-v1"` y `mfa` reciente.

### 2.2 Escenarios configurados en `tests/load/k6_admin_load.js`
1. **`escenario_1_agregados_negocio`** (`ramping-vus` 0→20→50 VUs, meseta de 50 VUs durante 60s, bajada a 0): ejercita `/admin/v1/business/summary`, `/admin/v1/business/overview`, `/admin/v1/business/customers` y `/admin/v1/business/usage/tokens`.
2. **`escenario_2_ops_polling`** (`ramping-vus` con pacing de operador activo): ejercita `/admin/v1/ops/agents`, `/admin/v1/ops/models` y `/admin/v1/ops/sla`. Soporta tanto modo con contrato E2 activo (`K6_TELEMETRY_E2_ACTIVE=true`) como modo degradado controlado cuando el servicio de telemetría de E2 no está desplegado (`K6_TELEMETRY_E2_ACTIVE=false`, validando corte rápido del circuit breaker `< 500 ms` y `200 OK` en `/ops/sla`).
3. **`escenario_3_lectura_bajo_refresco_secdef`**: lecturas concurrentes de negocio, SLA y sonda `/admin/v1/health` mientras se ejecutan en paralelo `admin.refresh_all_business_aggregates()` y `admin.refresh_sla(95, true)`.

---

## 3. Resultados Empíricos Obtenidos (50 VUs Concurrentes + Refresco `SECURITY DEFINER`)

### 3.1 Métricas Globales de la Campaña

| Indicador Global | Valor Observado | Umbral / SLO Exigido | Estado |
| :--- | :--- | :--- | :--- |
| **Usuarios Virtuales Concurrentes (VUs)** | `50` | `50` | **CUMPLE** |
| **Peticiones HTTP Totales Medibles** | `150` (tras warmup de pools) | `>= 100` | **CUMPLE** |
| **Throughput Sostenido (RPS)** | `28.46 req/s` (~1,707 req/min) | `< 3,000 req/min` (`RL-4` global) | **CUMPLE** |
| **Latencia Global `p50`** | `65.71 ms` | Referencia | **CUMPLE** |
| **Latencia Global `p95`** | **`314.59 ms`** | **`< 500.00 ms`** | **CUMPLE** |
| **Latencia Global `p99`** | **`444.78 ms`** | **`< 900.00 ms`** | **CUMPLE** |
| **Tasa de Errores HTTP 5xx** | **`0.00%`** (`0 / 150`) | **`< 1.00%`** | **CUMPLE** |
| **Tasa de Éxito en Checks JSON** | **`100.00%`** (`150 / 150`) | **`>= 99.00%`** | **CUMPLE** |

### 3.2 Desglose de Latencia por Endpoint Bajo Estrés

| Endpoint | Escenario | Pool Principal | `p50 (ms)` | `p95 (ms)` | `p99 (ms)` | SLO `p95` | Estado |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `GET /admin/v1/business/summary` | Escenario 1 (Negocio) | `kallicode_admin_ro` | `70.10` | `467.42` | `467.42` | `< 500 ms` | **OK** |
| `GET /admin/v1/business/overview` | Escenario 1 (Negocio) | `kallicode_admin_ro` | `60.15` | `408.95` | `408.95` | `< 500 ms` | **OK** |
| `GET /admin/v1/business/customers` | Escenario 1 & 3 | `kallicode_admin_ro` | `59.36` | `423.59` | `423.59` | `< 500 ms` | **OK** |
| `GET /admin/v1/business/usage/tokens` | Escenario 1 (Negocio) | `kallicode_admin_ro` | `49.08` | `342.46` | `342.46` | `< 500 ms` | **OK** |
| `GET /admin/v1/ops/agents?ventana=1h` | Escenario 2 (Ops) | `kallicode_admin_ro` + E2 | `92.99` | `314.59` | `314.59` | `< 500 ms` | **OK** |
| `GET /admin/v1/ops/models?ventana=24h` | Escenario 2 (Ops) | `kallicode_admin_ro` + E2 | `93.61` | `415.96` | `415.96` | `< 500 ms` | **OK** |
| `GET /admin/v1/ops/sla` | Escenario 2 & 3 | `kallicode_admin_ro` | `83.33` | `444.78` | `444.78` | `< 500 ms` | **OK** |
| `GET /admin/v1/health` | Escenario 3 (Sonda) | `app` + `ro` + Redis | `59.84` | `301.61` | `301.61` | `< 500 ms` | **OK** |

---

## 4. Evaluación de Contención en PostgreSQL 16 y No-Interferencia con el Portal

Durante la ventana de carga de 50 VUs se ejecutaron **4 ciclos completos** de refresco `SECURITY DEFINER` (`SELECT * FROM admin.refresh_all_business_aggregates()` y `SELECT admin.refresh_sla(95, true)`) en paralelo con un monitor sobre `pg_locks` y `pg_stat_activity` y una sonda de escritura transaccional sobre `core.tickets`:

| Métrica de Base de Datos | Valor Medido | Criterio de Aceptación | Análisis Técnico |
| :--- | :--- | :--- | :--- |
| **Ciclos `SECURITY DEFINER` completados durante la carga** | `4` (`0` fallidos) | `>= 1` con `0` fallos | `admin.refresh_*` (`OWNER TO kallicode_admin_agg`) actualiza `admin.agg_*` y `admin.sla_cases` transaccionalmente sin interrumpir lecturas. |
| **Sesiones activas `kallicode_admin_ro` en `pg_stat_activity`** | `10` | Uso efectivo del pool `RO` (`pool_size_ro = 10`) | Las consultas analíticas corren sobre `kallicode_admin_ro` con `SET TRANSACTION READ ONLY` y `statement_timeout = 30000 ms`. |
| **Bloqueos en espera (`pg_locks.granted = false`) en `core.*` / `admin.*`** | `0` (`0.00 ms` espera máx.) | `0` bloqueos bloqueantes | En PostgreSQL MVCC, `SELECT` de `kallicode_admin_agg` sobre `core.*` toma solo `ACCESS SHARE`, que jamás bloquea `ROW EXCLUSIVE` (`INSERT`/`UPDATE`) del portal. |
| **Nuevos Deadlocks (`pg_stat_database.deadlocks`)** | `0` | `0` | Cero interbloqueos entre `kallicode_admin_ro`, `kallicode_admin_app`, `kallicode_admin_agg` y transacciones sobre `core.*`. |
| **Latencia `p95` DML Portal (`INSERT/UPDATE core.tickets`) — Línea Base** | `33.66 ms` | Referencia sin carga admin | Escrituras transaccionales aisladas sobre `core.tickets`. |
| **Latencia `p95` DML Portal (`INSERT/UPDATE core.tickets`) — Bajo 50 VUs + `refresh_*`** | `34.17 ms` (`+0.51 ms`) | Sin degradación (`< 500 ms`) | Variación de `+0.51 ms` (< 2%), confirmando que la consola administrativa no degrada el plano transaccional de clientes. |

---

## 5. Instrucciones de Reproducción Local (Cero-Nube)

### 5.1 Verificación automatizada vía Pytest / Makefile (sin requerir binario `k6` externo)
```bash
docker compose up -d --wait
make load-test
```

### 5.2 Ejecución directa con `k6` (nativo o contenedor `grafana/k6`) contra `localhost:8000`
1. Sembrar datos sintéticos y generar `tests/load/tokens.json` (50 JWTs de `staff_admin`):
   ```bash
   uv run python -c "import asyncio, os; from tests.load.seed_and_tokens import sembrar_datos_carga_y_tokens; asyncio.run(sembrar_datos_carga_y_tokens(os.environ['KC_ADMIN_TEST_DSN']))"
   ```
2. Ejecutar `k6`:
   - Con stub o servicio de telemetría E2 activo:
     ```bash
     k6 run tests/load/k6_admin_load.js
     ```
   - Si el servicio de telemetría E2 aún no está levantado en el entorno local (valida `200 OK` en `/business/*`, `/ops/sla` y `/health` + corte rápido del circuit breaker `< 500 ms` en `/ops/agents` y `/ops/models`):
     ```bash
     K6_TELEMETRY_E2_ACTIVE=false k6 run tests/load/k6_admin_load.js
     ```
