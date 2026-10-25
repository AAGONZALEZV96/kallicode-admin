# Especificación de las 7 Pantallas de la Consola de Administración

**Versión:** 1.1 (Congelada para Bloque 1 - Contratos Alineados)
**Fuente:** Capítulo 18 del documento «Kallicode - Diseño Backend API v1.1»
**Contrato OpenAPI:** `docs/openapi-admin-v1.yaml` (generado desde código)

---

## Convenciones Transversales y Advertencias de Diseño

| Aspecto | Regla |
|---------|-------|
| **Autenticación** | Todas las pantallas requieren sesión staff válida (`typ=staff`, MFA verificado). |
| **Autorización** | Por rol: `staff_soporte`, `staff_operaciones`, `staff_negocio`, `staff_admin` (matriz en `docs/matriz-permisos-staff.md`). |
| **Enmascarado** | Datos identificables enmascarados por defecto; revelación exige concesión vigente (`GET /admin/v1/access-grants`). |
| **Auditoría** | Cada lectura/revelación registrada en `admin.staff_actions`; visible en `GET /admin/v1/audit/staff-actions`. |
| **Paginación** | `page` (1-based), `page_size` (1–100), `orden` (lista blanca por endpoint). |
| **Dato ausente** | Agregado obsoleto/fallido → **503 AGREGADO_NO_DISPONIBLE** (nunca cero). |
| **Telemetría** | Sin telemetría → estado `telemetria.disponible: false` (nunca ceros). |
| **Elementos No Soportados** | ⚠️ **El selector de "Región/País" del wireframe es estético y NO está soportado por la API `/admin/v1`**. Debe deshabilitarse u ocultarse para evitar mutaciones de estado global que la API ignorará. |

---

## 1. biz-overview — Panel General de Negocio (§18.16)

**Endpoint:** `GET /admin/v1/business/overview`
**Roles:** `staff_negocio`, `staff_admin`
**Parámetros:** `periodo` (mes_actual|mes_anterior|trimestre|ano), `comparar_con` (periodo_anterior|mismo_periodo_ano_anterior)

| Bloque | Campos | Fuente | Frescura |
|--------|--------|--------|----------|
| **clientes** | `activos`, `nuevos`, `perdidos`, `por_plan` | `admin.agg_customer_state` | `frescura.agg_customer_state` |
| **ingreso_recurrente** | `importe`, `moneda`, `variacion_pct` | `admin.agg_customer_state` | `frescura.agg_customer_state` |
| **consumo** | `loc`, `tokens`, `coste_estimado` | `admin.agg_usage_cycle` | `frescura.agg_usage_cycle` |
| **pipeline** | `tickets_entregados`, `tiempo_e2e_p50_h`, `escalado_humano_pct` | `admin.agg_pipeline_daily` | `frescura.agg_pipeline_daily` |

**Estados UI:**
- Carga: skeleton de 4 tarjetas.
- Error 503: "Agregados recalculándose. Reintentar en 2 min" + botón Reintentar.
- Vacío: Imposible (siempre hay datos globales).

---

## 2. biz-customers — Listado de Clientes (§18.17)

**Endpoint:** `GET /admin/v1/business/customers`
**Roles:** `staff_soporte`, `staff_negocio`, `staff_admin`
**Parámetros:** `q` (búsqueda por ID; razón social exige concesión), `estado` (activo|suspendido|moroso|baja), `plan`
**Paginación/Orden:** `page`, `page_size`, `orden` (`consumo-desc` | `alta-desc` | `nombre-asc`)

| Columna | Campo API | Enmascarado | Concesión requerida |
|---------|-----------|-------------|---------------------|
| Razón social | `razon_social` | Sí (inicial + ••••) | `datos_negocio` |
| Plan | `plan` | No | — |
| Estado | `estado` | No | — |
| Líneas activas | `lineas_contratadas` | No | — |
| Consumo | `consumo_ciclo` | No | — |
| Última actividad | `ultima_actividad` | No | — |
| **Acciones** | Ver ficha, Solicitar revelación | — | — |

**Ficha detalle (`GET /admin/v1/business/customers/{tenant_id}`):**
Reúne identificación, suscripción, líneas, consumo histórico, usuarios, integraciones, estado del grafo de conocimiento y actividad reciente del pipeline. Bloques de usuarios e integraciones requieren concesión.

---

## 3. biz-subs — Gestión de Suscripciones (§18.19–18.20)

**Endpoints:** 
- `GET /admin/v1/business/subscriptions`
- `GET /admin/v1/business/upgrade-requests`

**Roles:** `staff_negocio`, `staff_admin`

| Vista / Pestaña | Parámetros API | Datos Críticos |
|-----------------|----------------|----------------|
| **Suscripciones Activas** | `estado=activo` | `plan`, `estado`, `inicia_el`, `renueva_el`, `cuota_uso_pct` |
| **Por Renovar (≤30 días)** | `renueva_en_dias=30` | `dias_para_renovacion` (calculado por aniversario) |
| **Solicitudes de Cambio** | `estado=pendiente` | `plan_actual`, `plan_deseado`, `urgente`, `motivo`, `antiguedad_h` |

**Nota:** La consola es de **solo lectura comercial**; los cambios de plan se operan desde el portal del cliente.

---

## 4. biz-tokens — Análisis de Consumo de Tokens (§18.21)

**Endpoint:** `GET /admin/v1/business/usage/tokens`
**Roles:** `staff_negocio`, `staff_admin`
**Parámetros:** `ciclo` (YYYY-MM), `tenant_id`, `agrupar_por` (`cliente` | `tier` | `dia`)

| Visualización | Requisito de Agrupación | Datos Mostrados |
|---------------|-------------------------|-----------------|
| **Gráfico temporal** | `agrupar_por=dia` | `tokens_entrada`, `tokens_salida` por día |
| **Tabla por cliente** | `agrupar_por=cliente` | `tenant_id`, `razon_social` (enmascarado), `por_tier` (flash/pro/fable), `coste` |
| **Alerta de integridad** | Transversal | ⚠️ Mostrar alerta si `cuadra_con_facturacion` es `false` |

**Exportación:** `POST /admin/v1/business/reports` (tipo `consumo`, formato `csv|pdf`).

---

## 5. ops-agents — Estado de Agentes y Colas (§18.24, §18.25)

**Endpoints combinados para la vista:**
1. `GET /admin/v1/ops/agents` (Agentes, Líneas y Telemetría)
2. `GET /admin/v1/ops/queues` (Profundidad y estado de colas)

**Roles:** `staff_operaciones`, `staff_admin`
**Parámetros:** `ventana` (5m|1h|24h), `etapa`

| Sección UI | Endpoint | Campos Mapeados |
|------------|----------|-----------------|
| **Salud Telemetría** | `/agents` | `telemetria.disponible`, `telemetria.antiguedad_s` |
| **Líneas Globales** | `/agents` | `lineas.activas`, `lineas.mantenimiento`, `lineas.libres` |
| **Métricas Agentes** | `/agents` | `etapas[].agentes_total`, `agentes_ocupados`, `agentes_caidos` |
| **Estado Colas** | `/queues` | `colas[].pendientes`, `antiguedad_max_s`, `estado` (normal\|atencion\|critico) |

**Regla crítica:** Si `/agents` devuelve `telemetria.disponible: false`, anular contadores y mostrar "Sin telemetría".

---

## 6. ops-models — Telemetría de Modelos y Servicios (§18.26, §18.31)

**Endpoints combinados para la vista:**
1. `GET /admin/v1/ops/models` (Rendimiento de LLMs y Escalados)
2. `GET /admin/v1/health` (Servicios Core de la Plataforma)

**Roles:** `staff_operaciones`, `staff_negocio`, `staff_admin`
**Parámetros:** `ventana` (1h|24h|7d|30d), `proveedor`, `comparar` (bool)

| Bloque Wireframe | Endpoint | Campos Mapeados |
|------------------|----------|-----------------|
| **Model Health** | `/models` | `proveedor`, `modelo`, `tier`, `disponibilidad_pct`, `latencia_p95_ms`, `tasa_error_pct` |
| **Escalados** | `/models` | `escalados.flash_a_pro`, `escalados.pro_a_fable`, `escalados.a_humano` |
| **Core Services** | `/health` | `dependencias.postgres`, `dependencias.blob`, `dependencias.telemetria`, `dependencias.agregados` |

**Nota sobre Tiers:** El tier `fable` se reporta estrictamente separado de `pro` para el cálculo exacto de costes.

---

## 7. ops-sla — Cumplimiento de Niveles de Servicio (§18.27–18.28)

**Endpoints:**
- `GET /admin/v1/ops/sla` — Resumen global y listado de casos
- `GET /admin/v1/ops/sla/cases/{job_id}` — Reloj detallado de un caso específico

**Roles:** `staff_operaciones`, `staff_negocio`, `staff_admin`

| Métrica / Vista | Datos de la API |
|-----------------|-----------------|
| **Panel Global** | `resumen.cumplimiento_pct`, `incumplidos`, `en_riesgo` |
| **Listado Casos** | `tenant_id` (enmascarado), `plan`, `objetivo_h`, `resultado` (dentro\|incumplido) |
| **Desglose Reloj** | `tramos[]` {inicio, fin, etapa, computa, causa_pausa}, `transcurrido_h`, `bruto_h` |

**Dato ausente:** Si `sin_definicion` contiene planes sin objetivos configurados, mostrar advertencia en UI. Un SLA no configurado nunca devuelve "100%".