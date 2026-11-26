# Informe Final de Integridad y Auditoría Cross-Tenant (Hito M6 — Release Candidate MVP)

- **Ticket:** `[KC-ADM-B6-12]` (Plan E6 `KC-ADM-12-5` · Épica EAD6 / EAD3)
- **Responsables:** ADM2 (Backend, Datos & Seguridad · Equipo E6) en colaboración con ADM1 (Lead Full-Stack)
- **Ámbito exclusivo:** Monorepo `kallicode-admin` (`apps/api/`, `apps/workers/`, `apps/web/`, `db/`, `infra/`)
- **Auditoría adversaria base:** [revision_cross_tenant.md](revision_cross_tenant.md)
- **Dictamen Final de Seguridad:** **CERTIFICADO — 0 vulnerabilidades críticas ni graves abiertas · Apto para Release Candidate (Hito M6)**

---

## 1. Resumen Ejecutivo de la Auditoría Final (Hito M6)

Este documento consolida la auditoría final de cierre del Bloque 6 para la Consola de Administración (`kallicode-admin`). Debido a que la consola representa la única excepción controlada al aislamiento por inquilino (*Row-Level Security*) de la plataforma KalliCode, una configuración errónea de permisos o enmascarado no provoca un fallo ruidoso sino una **fuga silenciosa** de datos cross-tenant.

La certificación final verifica conjuntamente y sin dobles simulados sobre PostgreSQL 16 + Redis:
1. **Hermeticidad del rol analítico `kallicode_admin_ro`** (`KC_ADMIN_DATABASE_URL_RO`) y cumplimiento de las 6 comprobaciones de `admin.validate_read_role()`.
2. **Enmascaramiento por defecto en servidor y revelación acotada** mediante concesiones vigentes en `admin.access_grants` (`motivo >= 20` caracteres, referencia verificable y límites por alcance de `JERARQUIA`).
3. **Integridad criptográfica SHA-256** de punta a punta entre `admin.staff_actions` (`admin.verify_staff_action_chain()`) y la cadena central por inquilino en `audit.audit_events` / `audit.chain_heads` (`audit.verify_chain()`).
4. **Aislamiento de red privada y no-fuga en capa HTTP/observabilidad:** `ingress.external = false` en `infra/containerapps.bicep`, respuestas HTTP `500` sanitizadas sin trazas internas en `apps/api/src/admin_api/main.py` y métricas Prometheus en `/metrics` (`/admin/v1/metrics`) libres de PII.

---

## 2. Matriz de Verificación de las 7 Pantallas frente a Políticas Cross-Tenant

Todas las pantallas operativas definidas en [AppRouter.tsx](../../apps/web/src/router/AppRouter.tsx) y servidas por FastAPI cumplen estrictamente separación RBAC (`STAFF_ROLES`), lectura en `kallicode_admin_ro` (`SET TRANSACTION READ ONLY`), enmascarado por defecto y auditoría en `admin.staff_actions` + `audit.audit_events`:

| # | Pantalla (`AppRouter.tsx`) | Endpoint(s) Backend | Roles Permitidos (`STAFF_ROLES`) | Canal BD | Enmascarado por Defecto y Alcance Mínimo | Auditoría |
|---|---|---|---|---|---|---|
| 1 | **biz-overview** (`/overview`, `/business/overview`) | `GET /admin/v1/business/overview` | `staff_negocio`, `staff_admin` | `kallicode_admin_ro` (`admin.agg_*`) | Agregado sin PII individual (`enmascarado`: no aplica) | Trazas de acceso administrativo y métricas `admin_staff_actions_total` |
| 2 | **biz-customers** (`/business/customers`, `/business/customers/:tenant_id`) | `GET /admin/v1/business/customers`, `GET /admin/v1/business/customers/{tenant_id}` | `staff_soporte`, `staff_negocio`, `staff_admin` | `kallicode_admin_ro` | `razon_social`, `dominio`, `usuarios`, `integraciones` ocultos; exige `datos_negocio` / `expediente` | `read` / `reveal` en `admin.staff_actions` + `audit.audit_events` (`actor_tipo = 'staff'`) |
| 3 | **biz-subscriptions** (`/business/subscriptions`) | `GET /admin/v1/business/subscriptions`, `GET /admin/v1/business/upgrade-requests` | `staff_negocio`, `staff_admin` | `kallicode_admin_ro` | `razon_social` y `comentario` enmascarados sin concesión `datos_negocio` | `read` / `reveal` registrado con `grant_id` y `reason` |
| 4 | **biz-tokens** (`/business/tokens`) | `GET /admin/v1/business/usage/tokens`, `POST /admin/v1/business/reports` | `staff_negocio`, `staff_admin` | `kallicode_admin_ro` (`admin.agg_*`) | `razon_social` enmascarada por fila sin `datos_negocio`; exportación individual bloqueada sin concesión | `read` / `reveal` / `report` en ambas cadenas |
| 5 | **ops-agents** (`/ops/agents`) | `GET /admin/v1/ops/agents`, `GET /admin/v1/ops/queues` | `staff_operaciones`, `staff_admin` | `kallicode_admin_ro` (`core.production_lines`) + Telemetría E2 | Métricas agregadas de fábrica y colas sin exposición de código fuente ni PII | `admin.staff_actions` y control `RL-4` (`60 req/min`) |
| 6 | **ops-models** (`/ops/models`) | `GET /admin/v1/ops/models`, `GET /admin/v1/health` | `staff_operaciones`, `staff_negocio`, `staff_admin` | `kallicode_admin_ro` + Telemetría E2 | Telemetría por proveedor/modelo/tier (`flash`, `pro`, `fable`) sin prompts ni respuestas LLM | Sin payload sensible; fallos en `admin_dependency_failures_total` |
| 7 | **ops-sla** (`/ops/sla`) | `GET /admin/v1/ops/sla`, `GET /admin/v1/ops/sla/cases/{job_id}` | `staff_operaciones`, `staff_negocio`, `staff_admin` | `kallicode_admin_ro` (`admin.sla_cases`) | `tenant_id`, `razon_social` y número de ticket enmascarados sin concesión `datos_negocio` / `expediente` | `read` / `reveal` con enlace SHA-256 por tenant |

---

## 3. Resultados de Comprobaciones de Base de Datos (`kallicode_admin_ro`, Inventario y RLS)

### 3.1 Validación del Motor mediante `admin.validate_read_role()` ([002_read_role.sql](../../db/002_read_role.sql))
La función de barrera ejecuta seis comprobaciones directas sobre los catálogos internos de PostgreSQL (`pg_roles`, `pg_class`, `pg_attribute`, `has_column_privilege()`, `has_table_privilege()`, `aclexplode()`), garantizando cero falsos negativos:

| Regla | Qué Certifica | Resultado Verificado |
|---|---|---|
| `V1_sin_bypassrls` | `kallicode_admin_app` y `kallicode_admin_ro` tienen `rolbypassrls = false` y `rolsuper = false` | **0 filas (OK)** |
| `V2_solo_lectura` | `kallicode_admin_ro` carece de `INSERT`, `UPDATE`, `DELETE` y `TRUNCATE` en cualquier esquema de datos | **0 filas (OK)** |
| `V3_fuera_de_inventario` | Ninguna columna en `core.*` accesible a `kallicode_admin_ro` queda fuera de `admin.access_inventory` | **0 filas (OK)** |
| `V4_inventario_no_concedido` | Toda columna declarada en `admin.access_inventory` coincide 1:1 con privilegios efectivos | **0 filas (OK)** |
| `V5_auditoria_append_only` | Ningún rol no propietario posee `UPDATE`, `DELETE` o `TRUNCATE` sobre `admin.staff_actions` | **0 filas (OK)** |
| `V6_cadena_integra` | Encadenamiento SHA-256 completo validado por `admin.verify_staff_action_chain()` | **0 filas (OK)** |

### 3.2 Aislamiento de Pools, Tablas Prohibidas y Columnas Sensibles
- **Separación estricta de DSNs:** `KC_ADMIN_DATABASE_URL_APP` (`kallicode_admin_app`) y `KC_ADMIN_DATABASE_URL_RO` (`kallicode_admin_ro`) operan sobre pools independientes sin compartir conexiones.
- **Tablas prohibidas con rechazo `permission denied`:** `core.password_reset_tokens`, `core.refresh_tokens`, `core.idempotency_keys`, `core.ticket_attachments`, `core.webhook_inbox`, `core.code_blobs`.
- **Exclusión de secretos y código en claro:** en `core.users` solo son legibles `tenant_id`, `nombre`, `rol`, `estado`, `ultimo_acceso` (excluidos `password_hash`, `email` y secretos MFA); en `core.connections` se excluyen tokens OAuth, API keys y `config`; en `core.llm_steps` se excluyen prompts y salidas LLM.

---

## 4. Estado de Integridad de Cadenas de Sellado SHA-256 Local y Central

Verificado conforme a [001_admin_schema.sql](../../db/001_admin_schema.sql), [005_staff_audit_central_migration.sql](../../db/005_staff_audit_central_migration.sql) y [audit.py](../../apps/api/src/admin_api/audit.py):
- **Cadena local (`admin.staff_actions`):**
  - Protegida frente a `UPDATE` y `DELETE` mediante el trigger `trg_staff_actions_immutable`.
  - El rol operativo `kallicode_admin_app` no es propietario de la tabla ni puede ejecutar `ALTER TABLE` o deshabilitar triggers.
  - `SELECT * FROM admin.verify_staff_action_chain()` confirma **0 roturas** de sello ni supresión de tramos.
- **Cadena central por tenant (`audit.audit_events` + `audit.chain_heads`):**
  - Toda acción asociada a un `tenant_id` se replica transaccionalmente en la misma sesión `db` (`actor_tipo = 'staff'`, payload `actor: {"typ": "staff", ...}`).
  - La verificación mediante `audit.verify_chain()` y `verificar_cadena_central_tenant()` confirma **0 eventos huérfanos** entre `admin.staff_actions` y `audit.audit_events`, y **0 roturas** de sello encadenado SHA-256.

---

## 5. Aislamiento de Red, Sanidad de Salida y Puertas de Calidad

- **Aislamiento estricto de red privada ([containerapps.bicep](../../infra/containerapps.bicep)):** tanto `apiApp` como `webApp` declaran `ingress.external: false` (sin IP pública ni exposición externa) y los workers carecen de bloque `ingress`.
- **Sanidad HTTP y observabilidad ([main.py](../../apps/api/src/admin_api/main.py), [metrics.py](../../apps/api/src/admin_api/routers/metrics.py)):**
  - Excepciones no controladas devuelven `HTTP 500` con sobre estándar sanitizado (`error` + `X-Trace-Id`), sin stack traces, rutas internas ni consultas SQL.
  - `/admin/v1/metrics` y `/metrics` exponen exclusivamente métricas de baja cardinalidad registradas en `ADMIN_METRICS_REGISTRY`, sin `tenant_id`, correos ni PII.

### Puertas de Calidad Ejecutadas

| Puerta / Suite | Alcance | Resultado |
|---|---|---|
| `tests/test_final_integrity.py` | Consistencia documental, perímetro HTTP/Bicep/métricas, `validate_read_role()`, enmascarado/concesiones y cadenas SHA-256 | **3 passed** |
| `make no-fuga` (`tests/test_no_leak.py`) | Privilegios columnares reales, tablas prohibidas y `kallicode_admin_ro` read-only | **24 passed** |
| `make lint` / `make types` | `ruff`, `black --check`, `mypy` | **OK** (`79` archivos sin cambios, `0` errores en `36` archivos fuente) |
| `make test` | Suite unitaria (`-m "not integracion"`) | **352 passed**, 381 deselected |
| `make test-int` (`--cov`) | Suite completa con integración y cobertura (`>= 80%`) | **731 passed, 1 skipped, 85.08% cobertura** *(1 fallo de umbral `< 500 ms` en `test_load_performance.py` por sobrecarga de `--cov`, pasando `4 passed` con `--no-cov`)* |

---

## 6. Dictamen Formal de Seguridad (Autorización M6)

Con base en las pruebas de no-fuga, adversarias, de aislamiento de red, de endurecimiento HTTP y de certificación integral punta a punta sobre PostgreSQL 16 y Redis:
- **Vulnerabilidades críticas o graves abiertas:** **0**
- **Estado de integridad criptográfica local y central:** **100% íntegra (0 roturas, 0 huérfanos)**
- **Autorización técnica:** **APROBADO** el paso a Release Candidate / despliegue controlado en red privada para el Hito M6.
