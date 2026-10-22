# 🗄️ Inventario de Fuentes de Datos y Brechas por Pantalla (Consola Admin)

## 1. Resumen Ejecutivo y Metodología Cross-Tenant

### 1.1 Propósito
Este documento inventaria todas las fuentes de datos necesarias para las 7 pantallas de la Consola Admin (kallicode-admin), identifica brechas de cobertura y clasifica cada campo por su estado de disponibilidad. Sirve como base para el planeamiento de migraciones, contratos de telemetría y acuerdos de interfaz con equipos externos.

### 1.2 Modelo de Lectura Cross-Tenant
- **Lectura acotada:** Todas las consultas a `core.*` pasan mediante el rol `kallicode_admin_ro`, que tiene acceso solo a columnas autorizadas en `admin.access_inventory`.
- **Agregados cross-tenant:** Las funciones `SECURITY DEFINER` (`kallicode_admin_agg`) calculan agregados globales a partir de datos por-tenants, sin exponer datos sensibles de organizaciones individuales.
- **Enmascarado por defecto:** Cualquier campo que contenga datos identificables del cliente (razón social, email, nombre) sale enmascarado automáticamente. La revelación requiere justificación ≥10 caracteres registrada en `admin.staff_actions` con hash HMAC/SHA-256.

### 1.3 Esquemas de Origen y Tablas Reales

| Esquema | Tablas Principales (core.*) | Esquema Privado (admin.*) |
|---------|----------------------------|--------------------------|
| **core.** | `core.organizations`, `core.plans`, `core.subscriptions`, `core.usage_tokens`, `core.llm_steps`, `core.tickets`, `core.upgrade_requests`, `core.production_lines`, `core.model_providers`, `core.model_assignments` | `admin.staff`, `admin.staff_actions`, `admin.access_inventory`, `admin.sla_targets`, `admin.sla_cases` |

### 1.4 Brechas Clasificadas (Alta Prioridad)

| Brecha | Severidad | Pantallas Afectadas | Solución |
|--------|-----------|--------------------|----------|
| **ADM-G05** | ALTO | biz-overview, biz-customers, biz-subs, biz-tokens | Vistas agregadas `db/003_business_aggregates.sql` vía rol `kallicode_admin_agg` (SECURITY DEFINER) |
| **ADM-G06** | ALTO | ops-agents, ops-models | Contrato de telemetría con Equipo 2 (`docs/mapeo_de_fuentes_core-backend.md`) y dobles en MSW |
| **ADM-G07** | ALTO | ops-sla | Migración `db/004_sla.sql` creando `admin.sla_targets` y `admin.sla_cases` |

## 2. Matriz de Trazabilidad Campo a Campo para las 7 Pantallas

### 2.1 biz-overview (Panel General de Negocio)

| Campo UI | Tabla/Columna BD Real (core.*) | Estado de Fuente | Estrategia de Acceso / Enmascaramiento |
|----------|-------------------------------|------------------|----------------------------------------|
| `mrr_total` | `core.subscriptions` + `core.plans.precio` (via `plan_precios`) | Requiere Agregado | Vista `kallicode_admin_agg.mrr_total`; enmascarado por defecto |
| `clientes_activos` | `core.organizations.fabrica_activa` + `core.users.estado` | Existente (inferido) | No sensible; `fabrica_activa = true` = onboarding completado |
| `consumo_tokens_total` | `core.usage_tokens` aggregated | Requiere Agregado | Vista `kallicode_admin_agg.consumo_tokens_total`; no sensible |
| `proyectos_activos` | `core.projects` (conteo por tenant) | Existente | No sensible |
| `tendencia_mrr_pct` | `core.subscriptions.estado` + `core.plans` | Requiere Agregado | Cálculo derivado en vista `kallicode_admin_agg`; no sensible |
| `kpi_upgrades_30d` | `core.upgrade_requests` WHERE estado IN ('registrada','en_gestion') | Requiere Agregado | Contado vía vista `kallicode_admin_agg`; no sensible |
| `kpi_downgrades_30d` | `core.subscriptions` WHERE estado = 'finalizada' | Requiere Agregado | Contado vía vista `kallicode_admin_agg`; no sensible |
| `arpu_mensual` | `core.usage_tokens` avg tokens / clientes totales | Requiere Agregado | Cálculo derivado; no sensible |

### 2.2 biz-customers (Listado paginado, Razón Social, Email, Plan, Estado, Consumo acumulado, Enmascarado por defecto)

| Campo UI | Tabla/Columna BD Real (core.*) | Estado de Fuente | Estrategia de Acceso / Enmascaramiento |
|----------|-------------------------------|------------------|----------------------------------------|
| `razon_social` | `core.organizations.nombre` | Existente | Enmascarado por defecto: `*****` excepto primeros y últimos 3 chars |
| `dominio` | No directo en core.* | Requiere Agregado | Ausente en schema; podría provenir de `core.connections` o `core.users.email` |
| `email_contacto` | `core.users.email` | Existente | Enmascarado por defecto; revelación con justificación en `admin.staff_actions` |
| `plan_vigente` | `core.subscriptions.plan_codigo` + `core.plans.nombre` | Existente (via Join) | No sensible; muestra nombre plan vigente |
| `estado_cliente` | `core.organizations.fabrica_activa` (inferido) + `eliminado_en IS NULL` | Existente (inferido) | No sensible; `fabrica_activa=true` = onboarding completado |
| `consumo_acumulado` | `core.usage_tokens` aggregated por tenant | Requiere Agregado | Vista `kallicode_admin_agg.consumo_por_cliente`; no sensible |
| `ultimo_ticket_fecha` | `core.tickets.creado_en` (más reciente por tenant) | Existente | No sensible; muestra fecha del último ticket |

### 2.3 biz-subs (Suscripciones, Fechas de renovación por aniversario, Solicitudes de Upgrade)

| Campo UI | Tabla/Columna BD Real (core.*) | Estado de Fuente | Estrategia de Acceso / Enmascaramiento |
|----------|-------------------------------|------------------|----------------------------------------|
| `fecha_inicio` | `core.subscriptions.inicia_el` | Existente | No sensible; fecha de activación de la suscripción |
| `fecha_renovacion` | `core.subscriptions.renueva_el` | Existente | No sensible; inicio del próximo ciclo |
| `aniversario` | `core.subscriptions.inicia_el` (mismo día mes) | Existente | No sensible; deriva de `inicia_el` |
| `ciclo_cobro` | Derivado: `renueva_el - inicia_el` | Calculado | No sensible; ej: mensual si diferencia = 1 año al día |
| `solicitud_upgrade` | `core.upgrade_requests` WHERE tenant_id = org.id | Existente | Estados: 'registrada'=pendiente, 'en_gestion'=en proceso, 'aplicada'=completada, 'descartada'=cancelada |
| `monto_suscripcion` | `core.subscriptions.monto` (unido con plans) | Existente | No sensible; monto mensual en USD |
| `moneda` | `core.subscriptions.moneda` | Existente | No sensible; ISO 4217 (USD, EUR, etc.) |

### 2.4 biz-tokens (Tokens desglosados por tiers flash/pro/fable, Invocaciones, Costes)

| Campo UI | Tabla/Columna BD Real (core.*) | Estado de Fuente | Estrategia de Acceso / Enmascaramiento |
|----------|-------------------------------|------------------|----------------------------------------|
| `modelo` | `core.llm_steps.modelo` / `core.model_assignments.proveedor` | Requiere Telemetría E2 | Sensible por proveedor; enmascarado por defecto para roles no-admin |
| `proveedor` | `core.model_providers.proveedor` | Requiere Telemetría E2 | Sensible; valores: `anthropic`, `openai`, `google`, `deepseek_selfhosted` |
| `tokens_entrada` | `core.usage_tokens.tokens_in` / `core.llm_steps.tokens_in` | Requiere Telemetría E2 | No sensible (agregado); suma por tier y período |
| `tokens_salida` | `core.usage_tokens.tokens_out` / `core.llm_steps.tokens_out` | Requiere Telemetría E2 | No sensible (agregado); suma por tier y período |
| `costo` | No directo en core.* | Requiere DDL SLA / Agregado | Cálculo: `tokens_in * precio_entrada(tier) + tokens_out * precio_salida(tier)`; enmascarado `$XX.XX` |
| `invocaciones` | `core.llm_steps.invocaciones` / `core.usage_tokens.invocaciones` | Existente | No sensible; conteo total de llamadas LLM |
| `tier` | `core.llm_steps.tier` / `core.usage_tokens.tier` | Existente | Tiers: `pro`, `flash`, `vision` (schema usa "vision", no "fable" - brecha de nomenclatura) |

### 2.5 ops-agents (Líneas de producción, Profundidad de colas, Agentes activos)

| Campo UI | Tabla/Columna BD Real (core.*) | Estado de Fuente | Estrategia de Acceso / Enmascaramiento |
|----------|-------------------------------|------------------|----------------------------------------|
| `lineas_produccion` | `core.production_lines` (una por tenant) | Requiere Telemetría E2 | No sensible; PK: (tenant_id, numero), columnas: estado, job_id |
| `agentes_activos` | `core.production_lines` WHERE estado = 'ocupada' | Requiere Telemetría E2 | No sensible; count de líneas con job_id NOT NULL |
| `agentes_inactivos` | `core.production_lines` WHERE estado = 'mantenimiento' | Requiere Telemetría E2 | No sensible; count de líneas en mantenimiento |
| `queue_depth` | `core.jobs` WHERE estado IN ('pendiente_asignacion','triage','design','build','qa','gate2','pausado_por_cuota','escalado_humano') | Requiere Telemetría E2 | No sensible cuando hay telemetría; "Sin telemetría" cuando no |
| `telemetria` | N/A (bandera de estado derivado) | Requiere Telemetría E2 | Booleano: true = pipeline reportando, false = pipeline caído |
| `throughput` | `core.production_lines` + `core.jobs` aggregated | Requiere Agregado | Operaciones por minuto; cálculo en vista `kallicode_admin_agg` |

### 2.6 ops-models (Proveedores LLM, Asignación por tier, Latencia p50/p95, Tasa de error)

| Campo UI | Tabla/Columna BD Real (core.*) | Estado de Fuente | Estrategia de Acceso / Enmascaramiento |
|----------|-------------------------------|------------------|----------------------------------------|
| `proveedores_modelos` | `core.model_providers` WHERE tenant_id = org.id | Requiere Telemetría E2 | Sensible por proveedor; muestra proveedor y estado (valida/invalida/sin_configurar) |
| `asignacion_tier` | `core.model_assignments` WHERE tenant_id = org.id | Requiere Telemetría E2 | Una fila por (tenant_id, funcion); principal/fallback proveedor y modelo |
| `latencia_p50` | `core.llm_steps.duracion_ms` promedio por tier y función | Requiere Telemetría E2 | Promedio en segundos; cálculo derivado en vista agregada |
| `latencia_p95` | `core.llm_steps.duracion_ms` percentil 95 por tier y función | Requiere Telemetría E2 | Percentil 95 en segundos; cálculo derivado |
| `tasa_error_1h` | No directo en core.* | Requiere Telemetría E2 | Se inferiría de `core.llm_steps.validacion = 'esquema_valido'` vs fallos; brecha: no hay columna explícita |
| `tokens_minuto_actual` | `core.llm_steps.tokens_in` + `core.llm_steps.tokens_out` por minuto | Requiere Telemetría E2 | Suma de tokens procesados en la última hora, promediado por minuto |
| `uso_cuota_pct` | `core.quotas` (si existe) o cálculo desde `core.usage_tokens` | Requiere DDL SLA | Porcentaje de cuota usada; >90% requiere alerta visual |

### 2.7 ops-sla (Objetivos 72h/24h/8h, Reloj de caso, Pausas por firma de gates)

| Campo UI | Tabla/Columna BD Real (admin.* / core.*) | Estado de Fuente | Estrategia de Acceso / Enmascaramiento |
|----------|-----------------------------------------|------------------|----------------------------------------|
| `casos_total` | `admin.sla_cases` WHERE periodo_seleccionado = UI | Requiere DDL SLA | Total de casos en período seleccionado (24h/72h/8h) |
| `casos_cumplidos` | `admin.sla_cases` WHERE tiempo_proveedor <= objetivo_y_horas y estado = 'resuelto' | Requiere DDL SLA | Casos que cumplieron el objetivo SLA |
| `porcentaje_sla` | Calculado: `(casos_cumplidos / casos_total) * 100` | Requiere DDL SLA | Cálculado; solo si `casos_total >= sla_min_cases` (default 5) |
| `tiempo_cliente` | `admin.sla_cases.tiempo_espera_cliente` | Requiere DDL SLA | **No cuenta para SLA**; mostrado solo información |
| `tiempo_proveedor` | `admin.sla_cases.tiempo_proveedor` | Requiere DDL SLA | **Cuenta para SLA**; tiempo desde que proveedor toma caso hasta entrega |
| `niveles_etapa` | `admin.sla_cases.niveles_etapa` (JSON: triage, design, build, qa, security, deploy) | Requiere DDL SLA | Desglose por 6 etapas con tiempos promedio por etapa |
| `sla_min_cases` | `AdminSettings` | Existente | Umbral mínimo default 5, configurable por `staff_admin` |
| `periodo_seleccionado` | UI | Existente | `24h`, `72h`, `8h` |

## 3. Plan de Remediación de Brechas (Gaps)

| Brecha | Sprint | Bloque | Solución Técnica | Responsable |
|--------|--------|--------|------------------|-------------|
| **ADM-G05** | Sprint 1 (Semana 1) | Bloque 1 | Crear vista `kallicode_admin_agg` en `db/003_business_aggregates.sql` con funciones `SECURITY DEFINER` para: `mrr_total`, `consumo_tokens_total`, `kpi_upgrades_30d`, `kpi_downgrades_30d`. Otorgar permisos `kallicode_admin_ro` sobre columnas agregadas. | ADM2 (Data Engineer) |
| **ADM-G06** | Sprint 1 (Semana 2) | Bloque 2 | Definir contrato de telemetría con Equipo 2 (`docs/mapeo_de_fuentes_core-backend.md`): schema `core.production_lines`, `core.model_providers`, `core.model_assignments`, `core.llm_steps`. Implementar doble fuente en MSW (Mock Service Worker) con feature flag `telemetria_enabled`. Capturar métricas: `queue_depth`, `telemetria` bandera, latencias, tasas de error, uso cuota. | ADM2 + Equipo 2 (Fabrica) |
| **ADM-G07** | Sprint 2 (Semana 3) | Bloque 3 | Aplicar migración `db/004_sla.sql`: crear tablas `admin.sla_targets` (objetivos por plan: 72h/24h/8h) y `admin.sla_cases` (por caso: tiempos, etapas, flags de pausa, `tiempo_cliente`, `tiempo_proveedor`). Implementar worker de reloj SLA con pausas automáticas en gates humanos. Lógica: no contar tiempo en tejado del cliente. | ADM2 + Equipo 5 (Testing/Datos) |

## 4. Acuerdos de Interfaz y Dependencias Cruzadas

| Interfaz | Referencia | Descripción |
|----------|------------|-------------|
| `admin.access_inventory` | `db/002_read_role.sql` | Catálogo de columnas autorizadas para rol `kallicode_admin_ro` sobre `core.*` |
| `kallicode_admin_agg()` | `db/003_business_aggregates.sql` | Funciones agregadas `SECURITY DEFINER`: `mrr_total`, `consumo_tokens_total`, `kpi_upgrades_30d`, `kpi_downgrades_30d` |
| `admin.sla_targets` | `db/004_sla.sql` | Estructura de objetivos SLA por plan: `objetivo_horas` (72/24/8), `niveles_etapa` JSON, `sla_min_cases` |
| `admin.sla_cases` | `db/004_sla.sql` | Por caso individual: `tiempo_espera_cliente`, `tiempo_proveedor`, `niveles_etapa` JSON, `pause_reason`, `pause_start`, `pause_end` |
| `AdminSettings` | Config app | Parámetros: `aggregate_max_age_s` (default 21600 = 6h), `aggregate_stale_s` (default 86400 = 24h), `sla_min_cases` (default 5), `rate_limit_live` (default 60) |
| `admin.staff_actions` | `db/001_admin_schema.sql` | Registro de acciones con hash HMAC/SHA-256: `usuario_id`, `accion`, `motivo`, `hash_hmac`, `registro_fecha` |
| `billing.token_usage` | `core.usage_tokens` / `core.llm_steps` | Consumo de tokens por modelo/proveedor/período (fuente real, no `billing.*`) |
| `core.model_providers` | `mapeo_de_fuentes_core-backend.md` | Proveedores LLM por tenant: `proveedor`, `estado`, `modelos_disponibles`, `ultimo_test` |
| `core.model_assignments` | `mapeo_de_fuentes_core-backend.md` | Asignaciones por función: `principal_proveedor`, `principal_modelo`, `fallback_proveedor`, `fallback_modelo` |

**Dependencias Cruzadas:**
- `db/001_admin_schema.sql` → Creación esquema `admin`, tablas `staff`, `sla_targets`, `sla_cases`, `access_inventory`, triggers de hash HMAC.
- `db/002_read_role.sql` → Rol `kallicode_admin_ro`, política RLS por columna, función `validate_read_role()`.
- `db/003_business_aggregates.sql` → Migración Sprint 1: vistas agregadas cross-tenant, rol `kallicode_admin_agg`.
- `db/004_sla.sql` → Migración Sprint 2: tablas `sla_targets` y `sla_cases`, lógica de reloj SLA, pausas en gates.
- `docs/mapeo_de_fuentes_core-backend.md` → Contrato detallado de tablas core.*, campos y tipos para Equipo 2 y validación.
- `AdminSettings` → Configuración de umbrales e intervalos (validar defaults: `aggregate_max_age_s=21600`, `aggregate_stale_s=86400`, `sla_min_cases=5`).
