# Acta de Validación de Aceptación de Usuario (UAT) y Sign-Off de Release MVP (Hito M6 — GA)

- **Ticket:** `[KC-ADM-B6-14]` (Plan E6 `KC-ADM-12-1` y `KC-ADM-12-6` · Épica EAD6)
- **Hito del Programa:** **M6 — Release Candidate / Disponibilidad General (GA) de `kallicode-admin`**
- **Responsables:** ADM1 (Lead Full-Stack & Arquitectura), ADM2 (Backend, Datos & Seguridad) y ADM3 (Frontend & UX)
- **Alcance Diferido Aprobado:** [Backlog de Fase 2](../fase-2.md)
- **Estado del Release:** **APROBADO Y FIRMADO — Autorizado el paso a Producción en Red Privada**

---

## 1. Resumen Ejecutivo de Cierre (Hito M6)

Tras completar los seis bloques incrementales del Equipo E6, la Consola de Administración (`kallicode-admin`) ha superado las validaciones técnicas, de seguridad adversaria, de no-fuga cross-tenant, de carga concurrente, de accesibilidad e internacionalización y las pruebas de aceptación de extremo a extremo (UAT) sobre sus **7 pantallas operativas** (más la ficha 360° `CustomerDetail`) con los **4 roles canónicos de personal** (`STAFF_ROLES`: `staff_soporte`, `staff_operaciones`, `staff_negocio`, `staff_admin`).

La arquitectura desplegada garantiza:
1. **Aislamiento de red privada (`Zero Public Ingress`):** `ingress.external: false` tanto en `apiApp` como en `webApp` ([containerapps.bicep](../../infra/containerapps.bicep)), sin exposición pública a Internet.
2. **Doble conexión segregada sin `BYPASSRLS`:** escritura en `admin.*` con `kallicode_admin_app` (`KC_ADMIN_DATABASE_URL_APP`) y lectura analítica `READ ONLY` columna por columna (`admin.access_inventory`) con `kallicode_admin_ro` (`KC_ADMIN_DATABASE_URL_RO`).
3. **Privacidad por defecto y transparencia criptográfica:** datos identificables de clientes enmascarados salvo concesión temporal justificada (`motivo >= 20` caracteres + ticket `SUP-###` / `KC-###` en `admin.access_grants`), con doble sellado SHA-256 inmutable en `admin.staff_actions` (`trg_staff_actions_immutable`) y en `audit.audit_events` / `audit.chain_heads` visible desde el portal del cliente (`GET /api/v1/audit/staff-accesses`).

---

## 2. Guiones y Resultados de Validación UAT por Rol de Personal

Precondición común verificada en todos los guiones: inicio de sesión con cuenta corporativa `@kallicode.com` en `/login` (`POST /admin/v1/auth/login`, hash **Argon2id**) seguido de desafío obligatorio **TOTP** en `/mfa` (`POST /admin/v1/auth/mfa/verify`), emitiendo JWT con `typ="staff"`, `iss="kallicode-admin"`, `aud="admin-v1"` y `mfa=true`.

### 2.1 UAT-01 · Rol `staff_soporte` (Atención al Cliente y Revelación Temporal)
- **Pantallas verificadas:** `biz-customers` (`/business/customers`, `/customers`) y ficha 360° `CustomerDetail` (`/business/customers/:tenant_id`, `/customers/:tenant_id`).
- **Pasos ejecutados y resultado:**
  1. **Control RBAC:** acceso a `/business/customers` permitido; intento de navegación a `/overview` o `/ops/agents` bloqueado con vista `/403` (`Error403` / HTTP `403 ROL_STAFF_INSUFICIENTE`). -> **OK**
  2. **Enmascaramiento por defecto:** en el listado y en `/business/customers/org_acme`, `razon_social` se muestra ofuscada (`A•••• S.L.`), `enmascarado` enumera los bloques protegidos y las tablas de usuarios e integraciones permanecen ocultas. -> **OK**
  3. **Validación de motivo en `SolicitudConcesionModal`:** el envío con motivo `< 20` caracteres o genérico sin código de incidencia es rechazado (`422 MOTIVO_INSUFICIENTE`). -> **OK**
  4. **Concesión y revelación reactiva:** solicitud `POST /admin/v1/access-grants` con alcance `expediente`, duración `30` min y motivo con referencia `SUP-9901`; tras `201 Created`, TanStack Query invalida la caché y revela razón social (`Acme Logística S.L.`), usuarios e integraciones. -> **OK**
  5. **Trazabilidad en auditoría:** acción `grant_created` y lectura `reveal` selladas en `admin.staff_actions` y replicadas en `audit.audit_events` (`actor_tipo = 'staff'`), visibles en `GET /api/v1/audit/staff-accesses`. -> **OK**

### 2.2 UAT-02 · Rol `staff_operaciones` (Monitorización en Vivo de Fábrica y SLA)
- **Pantallas verificadas:** `ops-agents` (`/ops/agents`), `ops-models` (`/ops/models`) y `ops-sla` (`/ops/sla`).
- **Pasos ejecutados y resultado:**
  1. **Redirección inicial y RBAC:** al entrar en `/`, `InicioRedireccion` redirige automáticamente a `/ops/agents`; rutas `/business/*` quedan bloqueadas con `/403`. -> **OK**
  2. **Agentes, líneas y colas (`/ops/agents`):** visualización de las 6 etapas canónicas (`triage`, `design`, `build`, `qa`, `security`, `deploy`), líneas de `core.production_lines` y colas/DLQ (`/admin/v1/ops/queues`), con `ControlesLiveRefresh` operando a `15s`, pausa automática al ocultar pestaña y presupuesto `RL-4` de `60 req/min`. -> **OK**
  3. **Modelos LLM y salud (`/ops/models`):** métricas de disponibilidad (`>= 99.0%`), latencia `p50`/`p95`, tasa de error y escalados (`flash_a_pro`, `pro_a_fable`, `a_humano`), con separación estricta de los tiers `flash`, `pro` y `fable` y estado de dependencias desde `GET /admin/v1/health`. -> **OK**
  4. **Cumplimiento SLA y explicabilidad (`/ops/sla`):** filtrado por ciclo, plan y casos en riesgo/incumplidos (con `tenant_id` y `razon_social` enmascarados sin concesión), apertura del modal `DetalleRelojSLA` (`GET /admin/v1/ops/sla/cases/{job_id}`) verificando la ecuación `Tiempo Bruto = Tiempo Computado + Pausas Justificadas` y tramos de pausa (`espera_firma_cliente`, `escalado_humano`). -> **OK**

### 2.3 UAT-03 · Rol `staff_negocio` (Analítica Ejecutiva, Suscripciones y FinOps)
- **Pantallas verificadas:** `biz-overview` (`/overview`, `/business/overview`), `biz-customers` (`/business/customers`), `biz-subscriptions` (`/business/subscriptions`, `/subscriptions`), `biz-tokens` (`/business/tokens`, `/tokens`), más lectura ejecutiva en `/ops/models` y `/ops/sla`.
- **Pasos ejecutados y resultado:**
  1. **Panel general (`/overview`):** consulta de `GET /admin/v1/business/overview` mostrando los 4 bloques KPI (MRR/ingresos, clientes activos por plan `starter`/`growth`/`enterprise`, consumo LOC/tokens/coste y pipeline e2e `p50`), selector de comparativa e insignia de frescura (`<= 6h` en verde vs `> 6h` en alerta). -> **OK**
  2. **Suscripciones y upgrades (`/business/subscriptions`):** radar de renovaciones próximas (`<= 15` y `<= 30` días) en `/admin/v1/business/subscriptions` y cola priorizada por antigüedad en `/admin/v1/business/upgrade-requests`, con enmascarado por defecto e integración con `SolicitudConcesionModal`. -> **OK**
  3. **FinOps y reconciliación (`/business/tokens`):** agrupación por `cliente`, `tier` y `dia` en `/admin/v1/business/usage/tokens`, separación innegociable de `fable` respecto a `pro` y verificación del indicador `cuadra_con_facturacion`. -> **OK**
  4. **Exportación asíncrona (`ControlExportarReporte`):** solicitud `POST /admin/v1/business/reports` (`csv`, `xlsx`, `pdf`), registro de acción `report` en auditoría y consulta de estado en `GET /admin/v1/business/reports/{report_id}` con `hash_sha256`. -> **OK**

### 2.4 UAT-04 · Rol `staff_admin` (Gobierno de Personal, Revocación y Auditoría Forense)
- **Superficie verificada:** acceso completo a las 7 pantallas SPA + operaciones administrativas en `/admin/v1/staff*`, `/admin/v1/access-grants*` y `/admin/v1/audit/staff-actions*`.
- **Pasos ejecutados y resultado:**
  1. **Ciclo de vida de personal:** emisión de invitación (`POST /admin/v1/staff/invitations`), listado de cuentas y concesiones activas (`GET /admin/v1/staff`), cambio de rol y desactivación (`PATCH /admin/v1/staff/{staff_id}`) comprobando protección contra auto-degradación del último `staff_admin` (`409 CONFLICTO_ESTADO`). -> **OK**
  2. **Revocación de emergencia:** al desactivar un empleado o invocar `POST /admin/v1/auth/logout` (`todas_las_sesiones: true`), se invalidan tokens en Redis (`admin:denylist:{jti}` y `admin:staff:{staff_id}:revoked_at`), se revocan sus `access_grants` vigentes y cualquier petición ulterior recibe `401 TOKEN_INVALIDO` / `403 STAFF_DESACTIVADO`. -> **OK**
  3. **Auditoría forense y exportación:** consulta global `GET /admin/v1/audit/staff-actions?ambito=todas` comprobando motivo, contador `lecturas` y bandera criptográfica `verificado: true`, seguida de exportación asíncrona `POST /admin/v1/audit/staff-actions/exports`. -> **OK**

### 2.5 UAT-05 · Comportamiento ante Incidencias (Degradación Controlada de Telemetría E2)
- **Escenario:** desconexión simulada del servicio interno de telemetría de Equipo 2.
- **Resultado verificado:** `/admin/v1/ops/agents`, `/admin/v1/ops/queues` y `/admin/v1/ops/models` responden de forma controlada con `HTTP 503` y código canónico **`TELEMETRIA_NO_DISPONIBLE`** (activando `_TelemetryCircuitBreaker` tras 3 fallos durante `30s`), `/admin/v1/health` pasa a HTTP `200` con `estado: "degradado"` (`dependencias.telemetria: false`), y tanto las pantallas de negocio (`/overview`, `/business/*`) como `/admin/v1/ops/sla` continúan operando al 100% sin errores `500`. -> **OK**

---

## 3. Matriz de Consolidación de Evidencias del Hito M6

| # | Dimensión de Certificación | Entregable / Evidencia en Repositorio | Suite de Verificación | Estado M6 |
|---|---|---|---|---|
| 1 | **Seguridad e Integridad Cross-Tenant** | [informe_final_integridad_m6.md](../seguridad/informe_final_integridad_m6.md) y [revision_cross_tenant.md](../seguridad/revision_cross_tenant.md) | [test_final_integrity.py](../../tests/test_final_integrity.py), [test_no_leak.py](../../tests/test_no_leak.py), [test_adversario.py](../../tests/test_adversario.py) | **CERTIFICADO** (`0` fallos en `V1`..`V6`, `0` huérfanos) |
| 2 | **Pruebas de Carga y Rendimiento** | [carga.md](carga.md) y [k6_admin_load.js](../../tests/load/k6_admin_load.js) | [test_load_performance.py](../../tests/test_load_performance.py) | **CERTIFICADO** (`50` VUs, `p95 = 314.59 ms < 500 ms`, `0` deadlocks) |
| 3 | **Aislamiento de Red Privada** | [containerapps.bicep](../../infra/containerapps.bicep) y [network.bicep](../../infra/network.bicep) | [test_network_isolation.py](../../tests/test_network_isolation.py) | **CERTIFICADO** (`external: false`, cero ingress público) |
| 4 | **Manuales Operativos y Runbooks** | [admin_console_ops.md](../runbooks/admin_console_ops.md) (`RB-01`..`RB-04`) | [test_runbooks.py](../../tests/test_runbooks.py) | **CERTIFICADO** (4 escenarios validados contra código) |
| 5 | **Manual de Usuario y Guías por Rol** | [admin_manual.md](../user_guides/admin_manual.md) (`guia_soporte`..`guia_admin`) | [test_user_guides.py](../../tests/test_user_guides.py) | **CERTIFICADO** (4 roles y 7 pantallas documentadas) |
| 6 | **Congelación de Contrato `/admin/v1`** | [politica_contrato_admin.md](../politica_contrato_admin.md) y [openapi-admin-v1.yaml](../openapi-admin-v1.yaml) | [test_contract_freeze.py](../../tests/test_contract_freeze.py), [test_openapi_contract.py](../../tests/test_openapi_contract.py) | **CERTIFICADO** (`v1.0.0` GA, `31` operaciones, `7` tags) |
| 7 | **Calidad UX, i18n y Responsive SPA** | [revision_negocio.md](revision_negocio.md), [revision_ops.md](revision_ops.md), [AppRouter.tsx](../../apps/web/src/router/AppRouter.tsx) | [i18n.test.tsx](../../apps/web/src/__tests__/i18n.test.tsx), [responsive.test.tsx](../../apps/web/src/__tests__/responsive.test.tsx) | **CERTIFICADO** (simetría ES/EN, build y tests SPA en verde) |
| 8 | **Backlog de Fase 2** | [fase-2.md](../fase-2.md) | [test_uat_signoff.py](../../tests/test_uat_signoff.py) | **DOCUMENTADO** (sin bloqueantes para GA) |

---

## 4. Resumen Final de Puertas de Calidad Ejecutadas

- **Backend Lint, Formato y Tipos (`make lint` / `make types`):** `ruff check`, `black --check` y `mypy` con **0 errores**.
- **Suite de Sign-Off UAT (`tests/test_uat_signoff.py`):** **4 passed** (consistencia documental, cobertura de 4 roles y 7 pantallas, smoke test de API/degradación E2 y recorrido integrado multi-rol).
- **Validación No-Fuga (`make no-fuga` / `tests/test_no_leak.py`):** **24 passed** (`admin.validate_read_role()` con `0` filas en fallo).
- **Suite Unitaria (`make test`) e Integración con Cobertura (`make test-int`):** cobertura total **>= 85%** (superando el umbral mínimo del `80%`).
- **Frontend SPA (`npm --prefix apps/web run build` y `npm --prefix apps/web test`):** compilación TypeScript/Vite y suites Vitest en estado satisfactorio.

---

## 5. Acta Formal de Sign-Off (Aprobación Release GA — Hito M6)

Los abajo firmantes certifican que la Consola de Administración (`kallicode-admin`) cumple todos los requisitos funcionales, de rendimiento, de accesibilidad, de aislamiento de red y de seguridad cross-tenant establecidos para el Hito M6, quedando autorizada su puesta en producción:

| Rol de Gobernanza | Responsable / Representante | Ámbito Aprobado | Dictamen | Fecha |
|---|---|---|---|---|
| **Product Owner** | Dirección de Producto KalliCode | Aceptación funcional de los 4 guiones UAT sobre las 7 pantallas y catálogo de Fase 2 | **APROBADO (FIRMADO)** | 2026-11-26 |
| **Architecture Board / ADM1** | ADM1 — Lead Full-Stack & Arquitectura (E6) | Arquitectura aislada en red privada (`ADR-001`), contrato `/admin/v1` (`1.0.0`) y SLOs de carga (`p95 < 500 ms`) | **APROBADO (FIRMADO)** | 2026-11-26 |
| **Testing / CAL1** | CAL1 — Liderazgo de Calidad & Testing | Cobertura automatizada (`>= 80%`), suites Schemathesis, Vitest, k6 y regresión UAT | **APROBADO (FIRMADO)** | 2026-11-26 |
| **Seguridad / PLT4 & ADM2** | PLT4 (Seguridad Plataforma E5) & ADM2 (Datos E6) | Certificación `kallicode_admin_ro`, enmascaramiento por defecto y cadenas SHA-256 sin fugas | **APROBADO (FIRMADO)** | 2026-11-26 |
