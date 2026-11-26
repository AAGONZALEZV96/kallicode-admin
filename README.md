# kallicode-admin · Consola Interna de Administración (Puerta de Entrada y Kit del Evaluador)

Servicio y SPA de la consola interna de KalliCode (`/admin/v1`, **31 endpoints**, **7 pantallas operativas** + ficha 360° `CustomerDetail`, capítulo 18 de *«Kallicode - Diseño Backend API v1.1»*). Entregable oficial del **Equipo E6 · KC-ADM** para el **Hito M6 — Release GA (`v1.0.0`)**.

---

## 1. Propósito y Premisa de Seguridad

Esta consola es **la única excepción declarada al aislamiento por inquilino (*cross-tenant*)** de KalliCode. Todo el resto de la plataforma garantiza que los datos de un cliente son inaccesibles desde el contexto de otro mediante *Row-Level Security* (`FORCE ROW LEVEL SECURITY`) en PostgreSQL 16. Para dar soporte operativo, supervisar SLAs y auditar facturación/FinOps, la consola necesita visión transversal multi-inquilino.

Esta excepción es segura y auditable porque descansa en **cuatro reglas inseparables** (eliminar cualquiera de ellas convertiría la consola en una brecha):

1. **Rol de lectura acotado (`kallicode_admin_ro`).** Carece de `SUPERUSER` y de `BYPASSRLS`, opera en transacciones `READ ONLY` (`KC_ADMIN_DATABASE_URL_RO`) y solo posee `GRANT SELECT` explícito **columna a columna** sobre las ~95 columnas autorizadas en `admin.access_inventory` (99 columnas auditadas en total). El código fuente de los clientes (`core.code_blobs`) y las tablas de credenciales jamás están en ese inventario.
2. **Enmascaramiento por defecto y concesiones justificadas (`admin.access_grants`).** La razón social, correos electrónicos, metadatos sensibles y `tenant_id` identificable se devuelven enmascarados por defecto (`A•••• S.L.`). Revelarlos exige crear una concesión temporal con motivo escrito (`>= 20` caracteres), referencia a un ticket (`SUP-###` / `KC-###`) y vencimiento automático; el alcance `contenido_codigo` no puede superar los **60 minutos**.
3. **Sellado inmutable append-only (`admin.staff_actions` + `audit.audit_events`).** Toda lectura, concesión, revocación o exportación sobre datos de un cliente se registra con el rol segregado `kallicode_admin_app` (`KC_ADMIN_DATABASE_URL_APP`) en `admin.staff_actions` (protegida contra `UPDATE` y `DELETE` por el disparador `trg_staff_actions_immutable`) y se replica criptográficamente con cadena SHA-256 hacia `audit.audit_events` y `audit.chain_heads` (`actor_tipo = 'staff'`).
4. **Visibilidad completa para el cliente en su portal (§11.6).** El registro sellado se expone directamente al cliente en su propio portal (`GET /api/v1/audit/staff-accesses`), permitiéndole verificar quién de KalliCode accedió a sus datos (con iniciales ofuscadas y rol), cuándo, con qué alcance y bajo qué motivo.

---

## 2. Despliegue Rápido en Local con Docker (One-Liner Quickstart)

> **Prerrequisito del monorepo:** las pruebas de integración y la inicialización del esquema aplican primero las migraciones base de la plataforma (`../kallicode-backend/db/0[0-5]_*.sql`) y después las cinco migraciones de la consola (`db/001`..`005`).

### 2.1 One-Liner para preparar variables, levantar infraestructura e inicializar esquema

```bash
cp -n .env.example .env && docker compose up -d --build && make no-fuga
```

Este comando:
1. Genera `.env` desde [`.env.example`](.env.example) con las dos cadenas de conexión segregadas (`kallicode_admin_app` y `kallicode_admin_ro`), Redis y puerto `8000`.
2. Levanta en Docker PostgreSQL 16 + `pgvector` en `localhost:5433` (`kc_admin_isolated_postgres`) y Redis 7 en `localhost:6380` (`kc_admin_isolated_redis`).
3. Aplica las migraciones `001`..`005`, siembra las organizaciones de prueba (`org_acme`, `org_globex`), presembrando los **4 usuarios de evaluación** (uno por rol canónico) y verificando las 24 pruebas de no-fuga.

### 2.2 Levantar API FastAPI, Workers y Frontend SPA

En terminales separadas (o en segundo plano):

```bash
# Terminal 1 — Backend FastAPI (/admin/v1) en el puerto estándar 8000
set -a && source .env && set +a && uv run uvicorn admin_api.main:app --host 0.0.0.0 --port 8000

# Terminal 2 — Workers de refresco de agregados, evaluación SLA e informes
set -a && source .env && set +a && uv run python -m admin_workers.main

# Terminal 3 — Frontend SPA React + TypeScript (modo interactivo presembrado en puerto 5173)
npm --prefix apps/web run dev:mock
```

### 2.3 URLs de Acceso Local

| Componente | URL Local | Descripción |
|---|---|---|
| **SPA Consola Web (`apps/web`)** | `http://localhost:5173` | Interfaz React 18 + TypeScript con soporte bilingüe (`ES`/`EN`), WCAG 2.1 AA y las 7 pantallas operativas |
| **API FastAPI (`apps/api`)** | `http://localhost:8000` | Servicio `/admin/v1` (31 endpoints bajo autenticación JWT `typ=staff` + MFA TOTP) |
| **Sonda de Salud Operativa** | `http://localhost:8000/admin/v1/health` | Verifica estado de pools PostgreSQL (`app` y `ro`), Redis, Blob y telemetría E2 |
| **Métricas Prometheus** | `http://localhost:8000/metrics` | Exposición restringida a redes privadas (`KC_ADMIN_METRICS_ALLOW_CIDRS`) de las 5 familias Prometheus |

### 2.4 Usuarios y Credenciales Presembradas para Evaluadores (4 Roles de Personal)

Las siguientes cuentas corporativas (`@kallicode.com`) están presembradas tanto en el modo interactivo de la SPA (`npm --prefix apps/web run dev:mock`) como en PostgreSQL 16 tras ejecutar `make no-fuga` o `make test-int`:

| Rol Canónico (`STAFF_ROLES`) | Email Corporativo | Contraseña por Defecto | Código MFA / Bypass Local | Semilla TOTP (Base32) | Pantallas Principales Habilitadas |
|---|---|---|---|---|---|
| **`staff_admin`** | `admin@kallicode.com` | `Prueba-Segura-2026` | `123456` (o `654321`) | `JBSWY3DPEHPK3PXP` | Acceso total a las 7 pantallas + gobierno de `/admin/v1/staff*` y auditoría global |
| **`staff_soporte`** | `soporte@kallicode.com` | `Prueba-Segura-2026` | `123456` (o `654321`) | `JBSWY3DPEHPK3PXP` | `/business/customers` y ficha 360° `/business/customers/:tenant_id` con solicitud de concesión |
| **`staff_operaciones`** | `operaciones@kallicode.com` | `Prueba-Segura-2026` | `123456` (o `654321`) | `JBSWY3DPEHPK3PXP` | `/ops/agents`, `/ops/models` y `/ops/sla` (reloj SLA y pausas justificadas) |
| **`staff_negocio`** | `negocio@kallicode.com` | `Prueba-Segura-2026` | `123456` (o `654321`) | `JBSWY3DPEHPK3PXP` | `/overview`, `/business/customers`, `/business/subscriptions`, `/business/tokens` + lectura SLA/modelos |

> **Nota sobre TOTP en vivo contra FastAPI (`:8000`):** además de los códigos de recuperación numéricos presembrados (`123456` y `654321`), puedes generar en cualquier instante el código TOTP de 6 dígitos vigente para la semilla `JBSWY3DPEHPK3PXP` con:
> ```bash
> uv run python -c "import pyotp; print(pyotp.TOTP('JBSWY3DPEHPK3PXP').now())"
> ```

---

## 3. Batería de Comandos de Verificación por CLI (Make Targets y Auditoría)

Todos los comandos siguientes están verificados sobre el entorno local con los contenedores de `docker compose up -d` activos (`localhost:5433` y `localhost:6380`):

### 3.1 Puertas Estáticas de Calidad (Formato, Estilo y Tipado)

```bash
make lint && make types
```
- Ejecuta `uv run ruff check .`, `uv run black --check apps/ tests/` y `uv run mypy apps/api/src apps/workers/src` (0 errores en los 36 módulos fuente).

### 3.2 Puerta Obligatoria de Seguridad Cross-Tenant (No-Fuga)

```bash
make no-fuga
```
- Ejecuta `tests/test_no_leak.py` (24 pruebas sobre PostgreSQL 16 real): valida bidireccionalmente que los privilegios `SELECT` reales de `kallicode_admin_ro` coinciden exactamente con las ~95 columnas autorizadas en `admin.access_inventory` (99 columnas registradas), verifica que `NOBYPASSRLS` y `transaction_read_only = on` están activos y confirma que las tablas prohibidas son inaccesibles.

### 3.3 Suite de Pruebas Unitarias y de Consistencia (Sin Base de Datos)

```bash
make test
```
- Ejecuta `uv run pytest -m "not integracion" -q --no-cov` (358 pruebas unitarias en ~20 s): valida enmascaramiento, paginación por lista blanca, matriz RBAC de los 31 endpoints × 4 roles, congelación del contrato OpenAPI `1.0.0`, aislamiento de red privada Bicep, cabeceras de seguridad, runbooks, guías de usuario y acta de Sign-Off UAT.

### 3.4 Suite Completa de Integración y Cobertura (`>= 80%` Global)

```bash
make test-int
```
- Ejecuta la suite completa (739 pruebas activas sobre PostgreSQL 16 + `pgvector` y Redis 7) midiendo cobertura con `--cov-report=term-missing` (**85.00 %** de cobertura global, superando el umbral del 80 % y manteniendo módulos críticos de seguridad, telemetría, paginación, métricas e informes entre el 91 % y el 100 %).

### 3.5 Verificación de Carga Concurrente y No-Contención (`50 VUs`)

```bash
make load-test
```
- Ejecuta `tests/test_load_performance.py` validando el script `tests/load/k6_admin_load.js` y lanzando **50 usuarios virtuales (VUs) concurrentes** en paralelo con refrescos `SECURITY DEFINER` (`admin.refresh_all_business_aggregates()` y `admin.refresh_sla(95, true)`), certificando latencia **`p95 < 500 ms`**, **tasa de error `< 1 %`** y **`0` deadlocks**.

### 3.6 Auditoría Directa en Motor PostgreSQL (`kallicode_admin_app`)

```bash
psql "postgresql://kallicode_admin_app:test@localhost:5433/kallicode_test" \
  -c "SELECT * FROM admin.validate_read_role();" \
  -c "SELECT * FROM admin.verify_staff_action_chain();"
```
- `admin.validate_read_role()` debe devolver **`(0 rows)`** en las 6 reglas (`V1_sin_bypassrls`, `V2_solo_lectura`, `V3_fuera_de_inventario`, `V4_inventario_no_concedido`, `V5_auditoria_append_only`, `V6_cadena_integra`).
- `admin.verify_staff_action_chain()` debe devolver **`(0 rows)`**, confirmando que ningún eslabón SHA-256 de `admin.staff_actions` ha sido alterado ni suprimido.

### 3.7 Validación y Empaquetado del Frontend SPA (`apps/web`)

```bash
npm --prefix apps/web test -- --run
npm --prefix apps/web run build
```
- Ejecuta las **18 suites / 184 pruebas** de Vitest (incluyendo simetría de internacionalización `ES`/`EN`, diseño adaptable, accesibilidad y flujos por pantalla) y verifica el empaquetado de producción con TypeScript (`tsc -b`) y Vite (`vite build`).

### 3.8 Catálogo de Suites Automatizadas en `tests/`

| Fichero de Prueba | Qué Defiende |
|---|---|
| `test_authorization_matrix.py` | 31 endpoints × 4 roles, negativa exhaustiva. Falla si aparece un endpoint sin declarar. |
| `test_no_leak.py` | Los privilegios reales de `kallicode_admin_ro` coinciden con `admin.access_inventory` en ambas direcciones. |
| `test_masking.py` / `test_masking_and_grants.py` | Ningún campo identificable sobrevive sin concesión; la jerarquía de alcances no se salta. |
| `test_grants.py` | Ciclo completo, motivos genéricos rechazados, techo de 60 min en código, límite de 3 simultáneas y caducidad. |
| `test_staff_audit.py` / `test_audit_chain.py` / `test_staff_audit_migration.py` | Append-only, cadena SHA-256 local y central (`audit.audit_events`), migración histórica idempotente y detección de tampering. |
| `test_auth_flow.py` / `test_staff_tokens.py` / `test_staff_roles.py` | Indistinguibilidad de fallos de acceso, Argon2id, TOTP, rotación de refresh tokens y permisos por rol. |
| `test_endpoints_smoke.py` / `test_openapi_contract.py` | Camino feliz por pantalla, paridad con `openapi-admin-v1.yaml` y honestidad del dato ausente (`503`, nunca un cero). |
| `test_pagination.py` | Ordenación traducida desde lista blanca; ninguna entrada del usuario se interpola en SQL. |
| `test_observability.py` | Sonda `/admin/v1/health`, exposición restringida de `/metrics` (5 familias Prometheus) y cero PII en logs/métricas. |
| `test_network_isolation.py` / `test_security_headers.py` | Red privada (`ingress.external: false` en Bicep), validación de `Host`, proxies confiables, CORS estricto y cabeceras HTTP. |
| `test_adversario.py` / `test_role_exposure.py` | Pruebas adversarias cross-tenant: inyección SQL, manipulación de cursores, escalada de privilegios y acceso sin grant. |
| `test_load_performance.py` | Campaña de 50 VUs concurrentes bajo refresco `SECURITY DEFINER`, validando `p95 < 500 ms`, `< 1 %` errores y `0` deadlocks. |
| `test_runbooks.py` / `test_user_guides.py` | Consistencia automática entre runbooks (`RB-01`..`RB-04`), guías de usuario y el código fuente real. |
| `test_final_integrity.py` | Certificación integral M6 de `V1`..`V6`, enmascaramiento, cadenas SHA-256 local/central y enlaces portables. |
| `test_contract_freeze.py` | Congelación del contrato OpenAPI `/admin/v1` (`v1.0.0` GA, 31 operaciones, 7 tags) sin cambios disruptivos. |
| `test_uat_signoff.py` | Verificación determinista del acta UAT multi-rol (`UAT-01`..`UAT-05`), las 7 pantallas SPA, las 4 firmas y el backlog Fase 2. |

---

## 4. Mapa Maestro de Documentación y Rúbrica (Índice hacia `docs/`)

Todos los entregables documentales requeridos por la rúbrica del Hito M6 se encuentran indexados a continuación mediante enlaces relativos portables:

| Área de Evaluación / Rúbrica M6 | Documento Principal | Documentos Complementarios | Suite que lo Valida |
|---|---|---|---|
| **1. Acta de Aceptación UAT y Sign-Off M6 (GA)** | [`docs/informes/uat_signoff_m6.md`](docs/informes/uat_signoff_m6.md) | [`docs/informes/revision_negocio.md`](docs/informes/revision_negocio.md), [`docs/informes/revision_ops.md`](docs/informes/revision_ops.md) | [`tests/test_uat_signoff.py`](tests/test_uat_signoff.py) |
| **2. Auditoría de Seguridad e Integridad Cross-Tenant** | [`docs/seguridad/informe_final_integridad_m6.md`](docs/seguridad/informe_final_integridad_m6.md) | [`docs/seguridad/revision_cross_tenant.md`](docs/seguridad/revision_cross_tenant.md), [`docs/matriz-permisos-staff.md`](docs/matriz-permisos-staff.md), [`docs/tokens-staff.md`](docs/tokens-staff.md) | [`tests/test_final_integrity.py`](tests/test_final_integrity.py), [`tests/test_no_leak.py`](tests/test_no_leak.py), [`tests/test_adversario.py`](tests/test_adversario.py) |
| **3. Informe de Rendimiento y Pruebas de Carga (k6)** | [`docs/informes/carga.md`](docs/informes/carga.md) | [`tests/load/k6_admin_load.js`](tests/load/k6_admin_load.js), [`tests/load/orchestrate_load.py`](tests/load/orchestrate_load.py) | [`tests/test_load_performance.py`](tests/test_load_performance.py) |
| **4. Manual de Operaciones y Runbooks (Escenarios 1 a 4)** | [`docs/runbooks/admin_console_ops.md`](docs/runbooks/admin_console_ops.md) | [`rb-01-agregados-y-vistas.md`](docs/runbooks/rb-01-agregados-y-vistas.md), [`rb-02-ciclo-vida-staff.md`](docs/runbooks/rb-02-ciclo-vida-staff.md), [`rb-03-auditoria-cross-tenant.md`](docs/runbooks/rb-03-auditoria-cross-tenant.md), [`rb-04-telemetria-pipeline.md`](docs/runbooks/rb-04-telemetria-pipeline.md) | [`tests/test_runbooks.py`](tests/test_runbooks.py) |
| **5. Manual de Usuario por Rol de Staff** | [`docs/user_guides/admin_manual.md`](docs/user_guides/admin_manual.md) | [`guia_soporte.md`](docs/user_guides/guia_soporte.md), [`guia_operaciones.md`](docs/user_guides/guia_operaciones.md), [`guia_negocio.md`](docs/user_guides/guia_negocio.md), [`guia_admin.md`](docs/user_guides/guia_admin.md) | [`tests/test_user_guides.py`](tests/test_user_guides.py) |
| **6. Congelación de Contrato y OpenAPI `v1.0.0`** | [`docs/politica_contrato_admin.md`](docs/politica_contrato_admin.md) | [`docs/openapi-admin-v1.yaml`](docs/openapi-admin-v1.yaml), [`docs/contrato-telemetria-e2.md`](docs/contrato-telemetria-e2.md) | [`tests/test_contract_freeze.py`](tests/test_contract_freeze.py), [`tests/test_openapi_contract.py`](tests/test_openapi_contract.py) |
| **7. Backlog de Deuda Técnica y Fase 2** | [`docs/fase-2.md`](docs/fase-2.md) | [`docs/decisiones-negocio.md`](docs/decisiones-negocio.md), [`docs/inventario_fuentes.md`](docs/inventario_fuentes.md) | [`tests/test_uat_signoff.py`](tests/test_uat_signoff.py) |

---

## 5. Estado de los Puntos Previos y Decisiones de Arquitectura

### 5.1 Estructura del Monorepo y Árbol de Migraciones (`db/001`..`005`)

```text
db/                                        migraciones SQL de la consola (aplicar en orden)
  001_admin_schema.sql                       esquema admin, identidad staff, concesiones, auditoría encadenada y particiones
  002_read_role.sql                          roles kallicode_admin_app y kallicode_admin_ro, inventario (~95 cols) y validate_read_role()
  003_business_aggregates.sql                agregados de negocio vía funciones SECURITY DEFINER (rol kallicode_admin_agg)
  004_sla.sql                                objetivos SLA por plan, estados de pausa y motor de reloj neto compute_sla_case()
  005_staff_audit_central_migration.sql      puente append-only hacia audit.audit_events y audit.chain_heads (actor_tipo = 'staff')
apps/api/src/admin_api/                    backend FastAPI (/admin/v1, 7 routers, 31 endpoints, puerto estándar 8000)
apps/workers/src/admin_workers/            workers asíncronos con elección de líder por advisory locks (agregados, SLA, informes, grants)
apps/web/                                  SPA React 18 + TypeScript + Vite (7 pantallas operativas + ficha 360°, i18n ES/EN, WCAG 2.1 AA)
infra/                                     plantillas Azure Bicep de red privada (Zero Public Ingress, external: false)
docs/                                      contratos, runbooks, guías de usuario, informes de seguridad/carga y actas de Sign-Off M6
tests/                                     suite automatizada unitaria, de integración, adversaria, de carga (k6) y de certificación M6
```

Aplicación manual de migraciones en orden sobre una instancia PostgreSQL 16 con el esquema base cargado:

```bash
psql "$KC_ADMIN_DATABASE_URL_APP" -f db/001_admin_schema.sql
psql "$KC_ADMIN_DATABASE_URL_APP" -f db/002_read_role.sql
psql "$KC_ADMIN_DATABASE_URL_APP" -f db/003_business_aggregates.sql
psql "$KC_ADMIN_DATABASE_URL_APP" -f db/004_sla.sql
psql "$KC_ADMIN_DATABASE_URL_APP" -f db/005_staff_audit_central_migration.sql
```

### 5.2 Decisiones Arquitectónicas Innegociables

- **Sin `BYPASSRLS`, nunca.** El acceso analítico cross-tenant se gobierna exclusivamente mediante `admin.access_inventory` y políticas RLS dedicadas para `kallicode_admin_ro`.
- **Agregados en tablas con funciones `SECURITY DEFINER` (`kallicode_admin_agg`), no vistas materializadas.** Refrescar una vista materializada exige ser su propietario, lo que rompería la separación estricta entre el rol que lee (`kallicode_admin_ro`) y el que escribe (`kallicode_admin_app`).
- **Realm de identidad propio.** Contraseña con hash **Argon2id** + segundo factor **TOTP** obligatorio, emisor (`iss="kallicode-admin"`), audiencia (`aud="admin-v1"`) y `typ="staff"` incompatibles con la API del portal de clientes (`/api/v1`).
- **Puerto estándar unificado (`8000`).** El comando local de ejecución (`uvicorn admin_api.main:app --port 8000`), [`Dockerfile`](Dockerfile), [`.env.example`](.env.example) e [`infra/containerapps.bicep`](infra/containerapps.bicep) están alineados en el puerto `8000`.
- **Honestidad del dato ausente (`HTTP 503`).** Un agregado caducado (`> 24 h`) o una caída del colector de telemetría de Equipo 2 responden `503` con código semántico propio (`AGREGADO_NO_DISPONIBLE` o `TELEMETRIA_NO_DISPONIBLE`). Jamás se disfraza la falta de señal con un panel de ceros.

### 5.3 Resolución de los Puntos Previamente «Pendientes» (Cierre GA y Fase 2)

Los tres puntos abiertos al inicio del proyecto quedaron formalmente cerrados para el Release GA (`v1.0.0`) y trazados en [`docs/decisiones-negocio.md`](docs/decisiones-negocio.md) y [`docs/fase-2.md`](docs/fase-2.md):

1. **Precios de planes y tarifas de tokens en `003_business_aggregates.sql` (`900` / `2.900` / `9.500` EUR):** **Ratificados para el MVP / Release GA** en [`docs/decisiones-negocio.md`](docs/decisiones-negocio.md) (§2). Las tablas `admin.plan_prices` y `admin.token_rates` actúan como fuente oficial de ingresos recurrentes (MRR) y costes FinOps sin acoplar `core.plans`. La sincronización futura con un catálogo tarifario dinámico en `core.plans` queda registrada en [`docs/fase-2.md`](docs/fase-2.md) (`KC-ADM-F2-06`).
2. **Objetivos de nivel de servicio (SLA) en `004_sla.sql` (`72` / `24` / `8` h):** **Ratificados para el MVP / Release GA** en [`docs/decisiones-negocio.md`](docs/decisiones-negocio.md) (§3). Los compromisos por plan en `admin.sla_targets` y las 5 causas de pausa justificadas en `admin.sla_pause_states` (`admin.compute_sla_case`) constituyen la referencia productiva del reloj neto de SLA. La extensión para acuerdos SLA personalizados por contrato se registra en [`docs/fase-2.md`](docs/fase-2.md) (`KC-ADM-F2-07`).
3. **Columna `dominio` en `core.organizations` (§18.18):** **Resuelta en GA sin modificar el DDL central y diferida como columna nativa al backlog de Fase 2.** Conforme a [`docs/decisiones-negocio.md`](docs/decisiones-negocio.md) (§4), `admin_api` cumple el contrato §18.18 infiriendo `dominio` con triple fallback (dominio del correo del administrador en `core.users` ➔ proveedor en `core.connections` ➔ identificador normalizado de la organización), mientras que la incorporación futura de una columna `core.organizations.dominio` verificada por DNS en coordinación con `kallicode-backend` queda documentada formalmente en [`docs/fase-2.md`](docs/fase-2.md) (`KC-ADM-F2-08`).
