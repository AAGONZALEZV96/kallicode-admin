# Acta Formal de Revisión de Usabilidad Operativa: Pantallas Ops de Consola de Administración

- **Documento:** `docs/informes/revision_ops.md`
- **Ticket:** `[KC-ADM-B5-10]` — Revisión de Usabilidad Operativa de Pantallas Ops con Equipo de Soporte
- **Épica:** EAD5 — Consola de Operaciones (`kallicode-admin`)
- **Fecha de Auditoría y Certificación:** 13 de Noviembre de 2026
- **Rama Auditada:** `feature/KC-ADM-B5-10-ops-usability-review` (sobre `develop` consolidada con Bloque 5)
- **Responsable de Auditoría:** ADM1 (Tech Lead Full-Stack & Arquitecto de Consola) junto con Equipo de Soporte y Guardia Operativa

---

## 1. Resumen Ejecutivo y Dictamen de Operabilidad

El presente informe formaliza la auditoría técnica, funcional, de accesibilidad y de usabilidad en escenario real de guardia sobre las tres pantallas operativas de la consola de administración de KalliCode:

1. **`ops-agents`** ([OpsAgents.tsx](apps/web/src/vistas/OpsAgents.tsx)) — Estado de agentes de producción, etapas del pipeline y colas Redis Streams.
2. **`ops-models`** ([OpsModels.tsx](apps/web/src/vistas/OpsModels.tsx)) — Disponibilidad, latencia, tasa de error, escalados LLM y salud de dependencias core.
3. **`ops-sla`** ([OpsSLA.tsx](apps/web/src/vistas/OpsSLA.tsx) y [DetalleRelojSLA.tsx](apps/web/src/componentes/DetalleRelojSLA.tsx)) — Cumplimiento de niveles de servicio, riesgos (`> 75 %`) y explicabilidad del reloj por tramos.

### Dictamen Formal de Operabilidad

> **DICTAMEN:** **APROBADO PARA OPERACIÓN DE GUARDIA.** Se certifica que un ingeniero de guardia o operador de soporte (`staff_operaciones` / `staff_admin`) puede diagnosticar cuellos de botella del pipeline, degradación o caída de proveedores LLM, sobrecarga en colas `kc:inbox`/`kc:dlq` e incidencias/pausas de SLA íntegramente desde las vistas `ops-agents`, `ops-models` y `ops-sla`, sin abrir clientes SQL manuales ni consolas de Redis. El mecanismo de refresco en vivo (`useLiveRefresh` / `ControlesLiveRefresh`) respeta la cuota backend RL-4 (`60 req/min`) y detiene toda consulta en segundo plano cuando la pestaña no está visible.

---

## 2. Matriz Técnica Comparativa de Pantallas Operativas

| Dimensión | Pantalla 1: `ops-agents` | Pantalla 2: `ops-models` | Pantalla 3: `ops-sla` |
| :--- | :--- | :--- | :--- |
| **Componente Principal** | `OpsAgents.tsx` | `OpsModels.tsx` | `OpsSLA.tsx` + `DetalleRelojSLA.tsx` |
| **Endpoints Backend** | `GET /admin/v1/ops/agents` <br> `GET /admin/v1/ops/queues` | `GET /admin/v1/ops/models` <br> `GET /admin/v1/health` | `GET /admin/v1/ops/sla` <br> `GET /admin/v1/ops/sla/cases/{job_id}` |
| **Fuente de Datos** | Agregado telemetría Equipo 2 (`KC_PIPELINE_TELEMETRY_URL`, servicio JWT `typ="svc"`) | Agregado telemetría LLM Equipo 2 + sondeo `/admin/v1/health` | Agregados `admin.sla_cases`, `admin.sla_clock_segments`, `admin.agg_sla_compliance` (Pool RO) |
| **Cadencia y Cuota RL-4** | `15s` (`2` req/ciclo = `8 req/min` max), `pausarEnSegundoPlano`, `isFetching` guard | `15s` (`2` req/ciclo = `8 req/min` max), `pausarEnSegundoPlano`, `isFetching` guard | `30s` (`1` req/ciclo = `2 req/min` max), `pausarEnSegundoPlano`, `isFetching` guard |
| **Roles Autorizados (200)** | `staff_operaciones`, `staff_admin` | `staff_operaciones`, `staff_negocio`, `staff_admin` | `staff_operaciones`, `staff_negocio`, `staff_admin` |
| **Roles Bloqueados (403)** | `staff_soporte`, `staff_negocio` | `staff_soporte` | `staff_soporte` |
| **Enmascaramiento / PII** | Sin PII (solo identificadores agregados de etapas/colas) | Sin PII (métricas de modelos y dependencias) | `tenant_id` (`org_••••`) y `razon_social` (`I••••• S.L.`) enmascarados sin concesión activa |
| **Degradación 503 / Frescura** | Banner `banner-telemetria-desactualizada` (> 5 min), guiones `—` / `Sin telemetría` si `disponible=false`, error 503 con `X-Trace-Id` | Banner `alerta-disponibilidad-1h` (< 99 % en ventana 1 h), `ContenedorEstado` con `X-Trace-Id` y reintento | Banner de frescura > 6 h sin texto interno, `503` si agregado obsoleto > 24 h / fallido, `"N/A"` si casos evaluados `< 5` |
| **Suites Reproducibles** | `OpsAgents.test.tsx` (9 tests) | `OpsModels.test.tsx` (6 tests) | `OpsSLA.test.tsx` (7 tests) |

---

## 3. Validación de Simulacros de Diagnóstico Operativo

### 3.1. Escenario A: Pipeline Atascado o Degradado (`ops-agents`)
- **Objetivo del simulacro:** Localizar la etapa cuello de botella, discriminar agentes caídos frente a falta de carga y diagnosticar colas atascadas en Redis Streams (`kc:inbox`, `kc:dlq`) manteniendo refresco cada 15 s.
- **Comprobaciones verificadas:**
  - **Visibilidad de etapas:** Presentación uniforme de las 6 etapas canónicas (`triage`, `design`, `build`, `qa`, `security`, `deploy`) mostrando `agentes_total`, `agentes_ocupados`, `agentes_caidos`, `jobs_completados` y `duracion_p95_s`, destacando alertas activas por etapa.
  - **Agentes caídos vs ocupados:** Tarjeta `kpi-agentes` diferencia ocupados/totales de caídos (`var(--bad)` cuando `agentesCaidos > 0`).
  - **Colas Redis Streams (`kc:inbox`, `kc:dlq`):** Tabla ordenada por prioridad (`critico` > `atencion` > `normal`) y profundidad, exponiendo `pendientes`, `fallidos`, `antiguedad_max_s` y `umbral_atencion_s`, junto con el toggle `incluir_dlq`.
  - **Regla de no-invención de ceros (`null` vs `0`):** Cuando `telemetria.disponible === false` o los contadores son `null`, la vista muestra guiones (`—`) y `Sin telemetría`; cuando la telemetría está disponible con `0` carga real, muestra `0` explícitamente. Verificado en `OpsAgents.test.tsx` (tests 5 y 6) y `test_ops_endpoints.py::test_ops_agents_sin_trabajo_vs_sin_telemetria`.
  - **Supervisión de recuperación a 15 s bajo RL-4:** Confirmado `ControlesLiveRefresh` con cadencia por defecto de `15 segundos (Recomendado)`, indicador de frescura relativa y alerta > 5 minutos.

### 3.2. Escenario B: Proveedor LLM Degradado / Caído y Escalados (`ops-models`)
- **Objetivo del simulacro:** Detectar caída de disponibilidad por debajo del `99 %` en ventana `1h`, aislar consumo del tier `fable` y auditar la ruta de escalados (`flash_a_pro`, `pro_a_fable`, `a_humano`) y dependencias core.
- **Comprobaciones verificadas:**
  - **Alerta crítica en ventana `1h`:** Cuando un proveedor reporta disponibilidad `< 99.0 %` en ventana de 1 hora, `OpsModels.tsx` renderiza `role="alert"` (`data-testid="alerta-disponibilidad-1h"`) y el backend emite el evento `WARN` auditado en `test_ops_endpoints.py::test_ops_models_log_warn_proveedor_degradado_en_1h`.
  - **Regla de segregación de Fable (`claude-fable-5`):** Los modelos del tier `fable` se agrupan y totalizan en tarjetas y sección independientes de `flash` y `pro` tanto en llamadas, tokens (`tokens_por_tier`) como costes (`coste_por_tier`), garantizado en `OpsModels.test.tsx` y `test_ops_endpoints.py::test_ops_models_fable_segregado_tarifas_y_comparacion`.
  - **Trazabilidad de escalados LLM:** Tarjetas dedicadas contabilizan `flash_a_pro`, `pro_a_fable` y `a_humano` (con comparativa porcentual cuando `comparar_con=periodo_anterior` está activo).
  - **Salud de infraestructura:** Panel `panel-salud-servicios` muestra estados `OPERATIVO` / `DEGRADADO` para `Postgres`, `Blob Storage`, `Telemetría` y `Agregados` mediante `/admin/v1/health`.

### 3.3. Escenario C: Riesgo e Incumplimiento de SLA (`ops-sla` + `DetalleRelojSLA`)
- **Objetivo del simulacro:** Detectar casos en riesgo (`> 75 %`) antes del vencimiento y justificar ante clientes el cómputo exacto descontando pausas tipificadas.
- **Comprobaciones verificadas:**
  - **Detección continua de riesgo (`> 75 %`) e incumplimiento (`> 100 %`):** El worker periódico `evaluar_sla` invoca `admin.refresh_sla()` y `admin.calcular_reloj_caso()`, marcando casos activos `> 75 %` como `en_riesgo` y `> 100 %` como `incumplido`, mientras preserva en `en_curso` los casos con pausas justificadas (`test_sla_worker.py::test_sla_worker_evalua_riesgo_75_incumplimiento_y_respeta_pausas`).
  - **Explicabilidad por tramos (`GET /admin/v1/ops/sla/cases/{job_id}`):** Al seleccionar un caso en `OpsSLA.tsx`, `DetalleRelojSLA.tsx` muestra la ecuación `Tiempo Bruto = Tiempo Computado + Pausas Justificadas` y la línea cronológica tramo por tramo diferenciando `computa: true` frente a pausas tipificadas (`espera_firma_cliente`, `escalado_humano`, `ventana_mantenimiento`, `indisponibilidad_proveedor_llm`, `otro`), eliminando cualquier referencia interna mediante `sanitizarReglaTexto`. Verificado en `OpsSLA.test.tsx` (test 4) y `test_ops_sla_endpoints.py::test_ops_sla_case_detail_desglose_matematico_y_errores`.

---

## 4. Auditoría de Refresco en Vivo (RL-4), Estándares UI/UX, WCAG y RBAC

### 4.1. Comportamiento del Refresco en Vivo bajo Cuota RL-4
- Backend aplica `Depends(limite_vivo)` en `/admin/v1/ops/agents`, `/admin/v1/ops/queues` y `/admin/v1/ops/models` con tope de `60 req/min` por empleado.
- Frontend en `useLiveRefresh.ts` e integrado en las tres vistas:
  - En estado visible normal (`15s` en `OpsAgents` y `OpsModels`, `30s` en `OpsSLA`), el consumo por pestaña abierta oscila entre `2 req/min` y `8 req/min` (entre `3.3 %` y `13.3 %` de la cuota RL-4).
  - Cuando `document.hidden === true`, el polling se suspende en todas las vistas (`0 req/min` en segundo plano, verificado en `opsVistas.test.tsx` durante simulación de `90 s`).
  - Guardia `estaConsultando` (`isFetching`) y mutex interno evitan acumulación o solapamiento de peticiones en redes lentas (`useLiveRefresh.test.ts`, tests 5 y 11).

### 4.2. UI Limpia, Estados Homogéneos y Accesibilidad Básica
- **Ausencia de fugas y emojis:** Revisión estática sobre `OpsAgents.tsx`, `OpsModels.tsx`, `OpsSLA.tsx`, `ControlesLiveRefresh.tsx` y `DetalleRelojSLA.tsx` confirma cero cadenas de sección (`§18.xx`), cero nombres internos de tablas (`admin.*`) y cero emojis informales en la interfaz renderizada.
- **Homogeneidad `ContenedorEstado`:**
  - Carga con `EstadoCarga` (`role="status"`, `aria-busy="true"`, `aria-live="polite"`).
  - Errores HTTP (`503`, `403`, red) con `EstadoError` (`role="alert"`), visualización obligatoria de `X-Trace-Id` y botón `Reintentar`.
- **Accesibilidad básica y teclado:** Controles con `<label>`/`aria-label`, regiones `role="region"`/`role="status"`, badges con texto semántico además del color (`var(--text)`, `var(--muted)`, `var(--surface)`), y cierre por teclado `Escape` con foco inicial al abrir en `Modal.tsx`.

### 4.3. Matriz RBAC Verificada (Frontend y Backend)

| Rol Staff | `ops-agents` | `ops-models` | `ops-sla` | Evidencia Backend (`test_ops_endpoints.py` / `test_ops_sla_endpoints.py`) |
| :--- | :---: | :---: | :---: | :--- |
| `staff_operaciones` | **200 Permitido** | **200 Permitido** | **200 Permitido** | `200 OK` (con enmascaramiento por defecto en SLA) |
| `staff_admin` | **200 Permitido** | **200 Permitido** | **200 Permitido** | `200 OK` |
| `staff_negocio` | **403 Bloqueado** | **200 Permitido** | **200 Permitido** | `403 ROL_STAFF_INSUFICIENTE` en agents/queues |
| `staff_soporte` | **403 Bloqueado** | **403 Bloqueado** | **403 Bloqueado** | `403 ROL_STAFF_INSUFICIENTE` en las 3 vistas/endpoints |

---

## 5. Registro de Hallazgos Menores y Mejoras Ergonómicas para Bloque 6 (Endurecimiento)

Sin ser bloqueantes para la operación de guardia del Bloque 5, la auditoría documenta los siguientes tres puntos de mejora para la fase de endurecimiento (Bloque 6):

1. **`ERG-OPS-01` — Identificador heredado en fallback estático de `OpsModels.tsx`:**
   - *Observación:* La constante de respaldo `DATOS_DEFECTO` (usada únicamente cuando el componente se monta de forma aislada sin proveedor de consultas ni `obtenerDatos`) aún contiene `"gemini-2.5-flash"` en lugar de `"gemini-3-flash"` del catálogo canónico v1.1.
   - *Acción sugerida Bloque 6:* Actualizar `DATOS_DEFECTO` en `OpsModels.tsx` y alinear las aserciones estáticas en `opsVistas.test.tsx`.
2. **`ERG-OPS-02` — Atrapamiento de foco (`Tab` cycle) y retorno de foco en `Modal.tsx`:**
   - *Observación:* `Modal.tsx` mueve el foco al contenedor al abrir y soporta cierre con `Escape` + clic en overlay, pero no restringe el ciclo `Tab`/`Shift+Tab` dentro del diálogo ni restaura automáticamente el foco al botón disparador al cerrarse `DetalleRelojSLA`.
   - *Acción sugerida Bloque 6:* Añadir gestión de foco cíclico y restauración del elemento activo previo al cerrar el modal.
3. **`ERG-OPS-03` — Acceso directo a concesión justificada desde `OpsSLA.tsx`:**
   - *Observación:* Un operador `staff_operaciones` ve correctamente `tenant_id` (`org_••••`) y `razon_social` enmascarados en `OpsSLA.tsx`; cuando necesita contactar al cliente afectado por un caso en riesgo debe navegar a clientes para solicitar una concesión en `admin.access_grants`.
   - *Acción sugerida Bloque 6:* Evaluar enlazar `SolicitudConcesionModal.tsx` directamente desde la fila o desde `DetalleRelojSLA` para roles autorizados a solicitar concesiones.

---

## 6. Evidencia de Validación Local Ejecutada

| Verificación | Comando | Resultado Observado |
|---|---|---|
| Suites Frontend Ops + LiveRefresh | `cd apps/web && npm test -- --run src/vistas/__tests__/OpsAgents.test.tsx src/vistas/__tests__/OpsModels.test.tsx src/vistas/__tests__/OpsSLA.test.tsx src/hooks/__tests__/useLiveRefresh.test.ts src/vistas/__tests__/opsVistas.test.tsx` | **5 archivos, 42 passed** (`OpsAgents`: 9, `OpsModels`: 6, `OpsSLA`: 7, `useLiveRefresh`: 15, `opsVistas`: 5) |
| Build de Producción Frontend | `cd apps/web && npm run build` | **OK** (`tsc -b && vite build`, 348 módulos, `412.73 kB` en `1.79s`) |
| Suites Backend Ops + SLA Worker + SLA API | `KC_ADMIN_TEST_DSN="postgresql://postgres:postgres@localhost:5433/kallicode_test" KC_ADMIN_REDIS_URL="redis://localhost:6380/1" uv run pytest tests/test_ops_endpoints.py tests/test_sla_worker.py tests/test_ops_sla_endpoints.py -v --no-cov` | **39 passed** en `5.71s` |
| Linter y Formato Python | `make lint` | **OK** (`ruff`, `black` 63 archivos, `mypy` 33 archivos: 0 errores) |
| Tipado Python | `make types` | **OK** (`Success: no issues found in 33 source files`) |
| Política de No-Fuga PG16 | `make no-fuga` | **22 passed** en `2.85s` |

---

## 7. Firmas de Conformidad Operativa

| Rol | Representante | Dictamen | Fecha |
| :--- | :--- | :---: | :---: |
| **Lead de Administración (Consola E6)** | ADM1 (`kallicode-admin`) | **APROBADO** | 13/11/2026 |
| **Equipo de Guardia / Soporte Técnico** | Representante Operaciones & Soporte KalliCode | **APROBADO** | 13/11/2026 |
