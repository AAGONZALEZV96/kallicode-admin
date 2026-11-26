# Manual de Operaciones y Runbooks de la Consola de Administración (`kallicode-admin`)

- **Ticket:** `[KC-ADM-B6-10]` — Épica EAD6 (Sprint 12 / Hito M6)
- **Alcance:** Consola interna de administración (`/admin/v1`), workers en segundo plano (`admin_workers`) y capa de datos segregada (`admin.*` / `core.*` / `audit.*`).
- **Principio rector:** Cero exposición pública (red privada / VPN corporativa, véase [001-arquitectura-consola.md](file:///home/aagonzalezv/CAPSTONE/kallicode-admin/docs/adr/001-arquitectura-consola.md) y `infra/network.bicep`). Toda referencia técnica en este manual ha sido verificada en el código fuente del monorepo.

---

## 1. Topología Operativa y Separación de Conexiones

La API FastAPI ([main.py](file:///home/aagonzalezv/CAPSTONE/kallicode-admin/apps/api/src/admin_api/main.py)) y los workers ([admin_workers.main](file:///home/aagonzalezv/CAPSTONE/kallicode-admin/apps/workers/src/admin_workers/main.py)) operan con tres roles de PostgreSQL 16 sin `BYPASSRLS` ni superusuario:

| Canal / Pool | Variable / Propietario | Rol PostgreSQL | Propósito y Límites |
| :--- | :--- | :--- | :--- |
| **Escritura Admin (`admin_session`)** | `KC_ADMIN_DATABASE_URL_APP` | `kallicode_admin_app` | DML en `admin.*` y `INSERT` en `audit.audit_events` (`actor_tipo = 'staff'`). Pool `KC_ADMIN_POOL_SIZE_APP` (`5`), timeout `KC_ADMIN_STATEMENT_TIMEOUT_MS_APP` (`5000` ms). En `core.*` solo lee `core.organizations(id)`. |
| **Lectura Cross-Tenant (`read_session`)** | `KC_ADMIN_DATABASE_URL_RO` | `kallicode_admin_ro` | Lectura analítica `SET TRANSACTION READ ONLY` columna a columna según `admin.access_inventory`. Pool `KC_ADMIN_POOL_SIZE_RO` (`10`), timeout `KC_ADMIN_STATEMENT_TIMEOUT_MS_RO` (`30000` ms). |
| **Agregación en Segundo Plano** | `SECURITY DEFINER` | `kallicode_admin_agg` (`NOLOGIN`) | Propietario de `admin.refresh_*`; recalcula `admin.agg_*` y `admin.sla_cases` sin bloquear escrituras transaccionales sobre `core.*`. |

---

## 2. Catálogo Verificado de Variables de Entorno

Variables declaradas en [settings.py](file:///home/aagonzalezv/CAPSTONE/kallicode-admin/apps/api/src/admin_api/settings.py), [sla.py](file:///home/aagonzalezv/CAPSTONE/kallicode-admin/apps/workers/src/admin_workers/sla.py), [.env.example](file:///home/aagonzalezv/CAPSTONE/kallicode-admin/.env.example) y [Makefile](file:///home/aagonzalezv/CAPSTONE/kallicode-admin/Makefile):

### 2.1 Entorno, Base de Datos y Red Privada
- `KC_ADMIN_ENV`: `local` | `dev` | `staging` | `prod`
- `KC_ADMIN_APP_VERSION`: versión desplegada devuelta por `GET /admin/v1/health`
- `KC_ADMIN_DATABASE_URL_APP`, `KC_ADMIN_DATABASE_URL_RO`
- `KC_ADMIN_POOL_SIZE_APP` (`5`), `KC_ADMIN_POOL_SIZE_RO` (`10`)
- `KC_ADMIN_STATEMENT_TIMEOUT_MS_APP` (`5000`), `KC_ADMIN_STATEMENT_TIMEOUT_MS_RO` (`30000`)
- `KC_ADMIN_ALLOWED_HOSTS`, `KC_ADMIN_TRUSTED_PROXIES`, `KC_ADMIN_CORS_ORIGINS`
- `KC_REDIS_URL`, `KC_BLOB_ACCOUNT_URL`, `KC_JWT_PRIVATE_KEY`, `KC_JWT_PUBLIC_KEY`

### 2.2 Identidad Staff, Concesiones y Rate Limits
- `KC_ADMIN_STAFF_EMAIL_DOMAINS` (`kallicode.com`), `KC_ADMIN_JWT_ISSUER` (`kallicode-admin`), `KC_ADMIN_JWT_AUDIENCE` (`admin-v1`)
- `KC_ADMIN_STAFF_ACCESS_TOKEN_TTL_MIN` (`15`), `KC_ADMIN_STAFF_REFRESH_TOKEN_TTL_H` (`8`), `KC_ADMIN_STAFF_IDLE_TIMEOUT_MIN` (`30`)
- `KC_ADMIN_INVITATION_TTL_DAYS` (`7`), `KC_ADMIN_LOGIN_MAX_ATTEMPTS` (`5`), `KC_ADMIN_LOGIN_LOCK_WINDOW_S` (`900`)
- `KC_ADMIN_GRANT_DEFAULT_MINUTES` (`240`), `KC_ADMIN_GRANT_MIN_MINUTES` (`15`), `KC_ADMIN_GRANT_MAX_MINUTES` (`480`), `KC_ADMIN_GRANT_CODE_MAX_MINUTES` (`60`), `KC_ADMIN_GRANT_MAX_CONCURRENT` (`3`)
- `KC_ADMIN_RATE_LIMIT_STAFF` (`300`), `KC_ADMIN_RATE_LIMIT_GLOBAL` (`3000`), `KC_ADMIN_RATE_LIMIT_LIVE` (`60`)

### 2.3 Agregados, Workers, Telemetría y Observabilidad
- `KC_ADMIN_AGGREGATE_MAX_AGE_S` (`21600` = 6 h), `KC_ADMIN_AGGREGATE_STALE_S` (`86400` = 24 h), `KC_ADMIN_REFRESH_INTERVAL_S` (`900` = 15 min)
- `SLA_EVALUATION_INTERVAL_S` / `KC_ADMIN_SLA_EVALUATION_INTERVAL_S` (`300` = 5 min), `KC_ADMIN_SLA_MIN_CASES` (`5`)
- `KC_ADMIN_TELEMETRY_BASE_URL` / `KC_PIPELINE_TELEMETRY_URL`, `KC_ADMIN_TELEMETRY_TIMEOUT_S` (`5`), `KC_ADMIN_TELEMETRY_CONNECT_TIMEOUT_S` (`2.0`), `KC_ADMIN_TELEMETRY_READ_TIMEOUT_S` (`3.0`)
- `KC_ADMIN_TELEMETRY_WARN_AGE_S` (`300`), `KC_ADMIN_TELEMETRY_MAX_AGE_S` (`900`), `KC_ADMIN_TELEMETRY_CB_FAILURE_THRESHOLD` (`3`), `KC_ADMIN_TELEMETRY_CB_COOLDOWN_S` (`30.0`)
- `KC_ADMIN_METRICS_ENABLED` (`true`), `KC_ADMIN_METRICS_ALLOW_CIDRS`, `KC_ADMIN_METRICS_BEARER_TOKEN`, `KC_ADMIN_HEALTH_CHECK_BLOB_REMOTE` (`false` por defecto)
- `KC_ADMIN_TEST_DSN`, `KC_ADMIN_REDIS_URL` (pruebas aisladas locales)

---

## 3. Roles Oficiales y Endpoints de Operación Base

### 3.1 Roles Canónicos (`STAFF_ROLES`)
- `staff_soporte`: soporte a clientes, solicitud de concesiones, lectura de expedientes autorizados.
- `staff_operaciones`: observabilidad de agentes, colas, modelos y cumplimiento SLA.
- `staff_negocio`: analítica de negocio, suscripciones, tokens, exportación de informes y SLA.
- `staff_admin`: gestión de personal (`POST /admin/v1/staff/invitations`, `PATCH /admin/v1/staff/{staff_id}`), revocación de concesiones ajenas y auditoría global (`GET /admin/v1/audit/staff-actions?ambito=todas`).

### 3.2 Sondas y Métricas en Red Privada
- `GET /admin/v1/health`: devuelve `estado` (`ok`, `degradado`, `no_disponible`), `dependencias` (`postgres`, `lectura_analitica`, `cache`, `blob`, `telemetria`, `agregados`), `agregados_frescura_s` y `version`. Devuelve HTTP `503` si falla BD, caché o almacenamiento; HTTP `200` con `estado: "degradado"` si solo falla telemetría o frescura en ventana de aviso.
- `GET /admin/v1/metrics` (y alias `/metrics`): formato Prometheus (`text/plain`) protegido por `KC_ADMIN_METRICS_ALLOW_CIDRS` y token opcional `KC_ADMIN_METRICS_BEARER_TOKEN`. Expone `admin_http_request_duration_seconds`, `admin_http_requests_total`, `admin_aggregates_freshness_seconds`, `admin_staff_actions_total` y `admin_dependency_failures_total`.

---

## 4. Índice de Runbooks Operativos

| Runbook | Escenario Operativo | Archivo |
| :--- | :--- | :--- |
| **RB-01** | Fallo o retraso en el refresco de vistas materializadas y agregados (`admin.agg_*`, `admin.sla_cases`, worker) | [rb-01-agregados-y-vistas.md](file:///home/aagonzalezv/CAPSTONE/kallicode-admin/docs/runbooks/rb-01-agregados-y-vistas.md) |
| **RB-02** | Gestión del ciclo de vida y revocación de emergencia de personal (`staff`, sesiones Redis y `access_grants`) | [rb-02-ciclo-vida-staff.md](file:///home/aagonzalezv/CAPSTONE/kallicode-admin/docs/runbooks/rb-02-ciclo-vida-staff.md) |
| **RB-03** | Detección e investigación de patrones anómalos de acceso cross-tenant y verificación SHA-256 | [rb-03-auditoria-cross-tenant.md](file:///home/aagonzalezv/CAPSTONE/kallicode-admin/docs/runbooks/rb-03-auditoria-cross-tenant.md) |
| **RB-04** | Interrupción y recuperación de la telemetría operativa del pipeline (Equipo 2 y circuit breaker) | [rb-04-telemetria-pipeline.md](file:///home/aagonzalezv/CAPSTONE/kallicode-admin/docs/runbooks/rb-04-telemetria-pipeline.md) |

---

## 5. Calendario y Checklist de Mantenimiento Periódico

| Frecuencia | Tarea de Mantenimiento | Procedimiento / Comando Verificado | Responsable |
| :--- | :--- | :--- | :--- |
| **Diaria** | Comprobar salud, frescura de agregados (`<= 21600 s`) y contadores de fallo | Consultar `GET /admin/v1/health` y las métricas `admin_aggregates_freshness_seconds` y `admin_dependency_failures_total` en `GET /admin/v1/metrics`. | Guardia `staff_operaciones` |
| **Diaria** | Verificar ejecución automática de caducidad de concesiones y picos de revelación | Confirmar que el worker `caducar_concesiones` (cada `300` s) cierra concesiones vencidas; revisar `GET /admin/v1/access-grants?ambito=todas` y `GET /admin/v1/audit/staff-actions?ambito=todas`. | Guardia `staff_admin` |
| **Semanal** | Auditar el modelo de acceso dual y privilegios reales en PostgreSQL | Ejecutar `make no-fuga` (o en producción `SELECT * FROM admin.validate_read_role();` esperando `0` filas). | ADM2 (Backend & Datos) |
| **Semanal** | Comprobar integridad criptográfica de auditoría local y cadena central | Ejecutar `SELECT * FROM admin.verify_staff_action_chain();` y `SELECT * FROM audit.verify_chain('<tenant_id>', '<desde>', '<hasta>');`. | ADM2 / Seguridad |
| **Mensual** | Revisar `admin.access_inventory` tras cambios en `core.*`, auditar vigencia de cuentas staff y validar regresión completa + carga | Verificar `admin.access_inventory`, revisar cuentas en `GET /admin/v1/staff` y correr `make lint`, `make types`, `make test`, `make test-int` y `make load-test`. | ADM1 + ADM2 + Equipo 5 |

---

## 6. Protocolo y Matriz de Escalado ante Incidentes

| Nivel / Equipo | Cuándo Escalar | Evidencia Mínima a Adjuntar |
| :--- | :--- | :--- |
| **Nivel 1 — Guardia `staff_operaciones`** | `agregados_frescura_s > 21600`, `estado: "degradado"`, o fallo transitorio de un job en `admin_workers`. | Respuesta completa de `GET /admin/v1/health`, `X-Trace-Id`, última fila de `admin.aggregate_state` y logs recientes del worker. |
| **Nivel 2 — Plataforma Pipeline (Equipo 2)** | Error persistente `503 TELEMETRIA_NO_DISPONIBLE` > 10 min tras validar red privada hacia `KC_ADMIN_TELEMETRY_BASE_URL` / `KC_PIPELINE_TELEMETRY_URL`. | Logs `admin.telemetria.inalcanzable` / `admin.telemetria.desactualizada`, valor de `telemetria_desde` y `X-Trace-Id`. |
| **Nivel 2 — Datos & Backend Consola (ADM2)** | `estado: "no_disponible"` (`503` en `postgres` o `lectura_analitica`), `admin.validate_read_role()` con filas en fallo, o error repetido en `admin.refresh_all_business_aggregates()`. | Salida de `admin.validate_read_role()`, columna `error` en `admin.aggregate_state` y estado de bloqueos en `pg_stat_activity`. |
| **Crítico — Seguridad / Equipo 5 + `staff_admin`** | Rotura en `admin.verify_staff_action_chain()` o `audit.verify_chain()`, sospecha de credenciales staff comprometidas o lectura anómala cross-tenant. | Exportación generada con `POST /admin/v1/audit/staff-actions/exports`, `staff_id`/`grant_id` involucrados y constancia de bloqueo vía **RB-02**. |

---

## 7. Comandos Oficiales del Proyecto (Local / Docker)

```bash
make up          # Levanta Postgres (5433) y Redis (6380) aislados según docker-compose.yml
make down        # Detiene contenedores locales
make sync        # Sincroniza dependencias con uv sync --all-extras
make lint        # Ejecuta ruff check ., black --check apps/ tests/ y mypy
make types       # Chequeo estático estricto de tipos con mypy
make test        # Pruebas unitarias rápidas sin BD (-m "not integracion")
make test-int    # Suite completa con integración y cobertura (>= 80%)
make no-fuga     # Auditoría de privilegios reales y no-fuga (tests/test_no_leak.py)
make load-test   # Pruebas de carga 50 VUs y contención SECURITY DEFINER
```
