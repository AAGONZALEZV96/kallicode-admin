# Auditoría Dedicada de Seguridad del Acceso Cross-Tenant (Equipo E6 + Equipo 5)

- **Ticket:** `[KC-ADM-B6-02]` — Auditoría Dedicada de Seguridad del Acceso Cross-Tenant con Equipo 5
- **Épica:** `EAD6` — Endurecimiento, Red Privada, Observabilidad & Release MVP (Hito M6)
- **Responsables:** ADM2 (Backend, Datos & Seguridad · Equipo E6) en revisión conjunta con Equipo 5 (Testing & Seguridad)
- **Estado del Dictamen:** **APROBADO — 0 vulnerabilidades abiertas de elevación de privilegios o lectura no autorizada**
- **Suites de Verificación Automática:** [tests/test_no_leak.py](../../tests/test_no_leak.py) y [tests/test_adversario.py](../../tests/test_adversario.py)

---

## 1. Resumen Ejecutivo y Alcance de la Revisión

La Consola de Administración (`kallicode-admin`) constituye la única excepción gobernada al aislamiento por inquilino (*Row-Level Security*) de la plataforma KalliCode. A diferencia de un fallo funcional ordinario, un defecto en los privilegios de base de datos o en las políticas RLS del canal analítico produce una **fuga silenciosa**: la consulta no falla, sino que expone filas o columnas adicionales sin alertar al operador.

Antes del corte de Release Candidate (Hito M6), se ha ejecutado una auditoría adversaria sobre las tres barreras técnicas que contienen el acceso cross-tenant:
1. **Aislamiento de roles y privilegios por columna en PostgreSQL 16** (`kallicode_admin_ro`, `kallicode_admin_app` y `kallicode_admin_agg`) definidos en [002_read_role.sql](../../db/002_read_role.sql), [003_business_aggregates.sql](../../db/003_business_aggregates.sql), [004_sla.sql](../../db/004_sla.sql) y [005_staff_audit_central_migration.sql](../../db/005_staff_audit_central_migration.sql).
2. **Enmascaramiento por defecto en servidor y revelación acotada por concesión temporal** (`admin.access_grants`) implementados en [masking.py](../../apps/api/src/admin_api/masking.py), [deps.py](../../apps/api/src/admin_api/deps.py), [business.py](../../apps/api/src/admin_api/routers/business.py), [ops.py](../../apps/api/src/admin_api/routers/ops.py) y [grants.py](../../apps/api/src/admin_api/routers/grants.py).
3. **Auditoría append-only doblemente encadenada** en `admin.staff_actions` (`trg_staff_actions_immutable`) y en la cadena central del tenant (`audit.audit_events` y `audit.chain_heads` con `actor_tipo = 'staff'`) implementada en [audit.py](../../apps/api/src/admin_api/audit.py).

---

## 2. Auditoría Columna por Columna y Matriz de Privilegios (`kallicode_admin_ro`)

### 2.1 Verificación contra catálogos del motor (`pg_attribute`, `pg_class`, `pg_roles`)

La auditoría interroga directamente `has_column_privilege()`, `has_table_privilege()`, `aclexplode()` y `admin.validate_read_role()` sobre PostgreSQL 16 real:

- **Cero `BYPASSRLS` y cero `SUPERUSER` (`V1_sin_bypassrls`)**:
  - `kallicode_admin_ro`, `kallicode_admin_app` y `kallicode_admin_agg` tienen `rolbypassrls = false`, `rolsuper = false`, `rolcreatedb = false`, `rolcreaterole = false`.
  - La consulta recursiva sobre `pg_auth_members` confirma que ningún rol hereda privilegios indirectos de superusuario o elusión de RLS.
- **Cero `GRANT SELECT ON tabla` en `core.*`**:
  - `information_schema.table_privileges` devuelve conjunto vacío para `grantee = 'kallicode_admin_ro'` en `core.*`. Toda lectura se otorga exclusivamente **columna a columna** a partir de `admin.access_inventory`.
- **Correspondencia bidireccional exacta con `admin.access_inventory` (95 columnas en 16 tablas de `core.*`)**:
  - `concedidas - inventario = ∅` (`V3_fuera_de_inventario = 0 filas`).
  - `inventario - concedidas = ∅` (`V4_inventario_no_concedido = 0 filas`).

### 2.2 Inventario auditado por tabla en `core.*` y `audit.*`

| Tabla | Columnas Concedidas a `kallicode_admin_ro` | Columnas PII (`pii = true`) | Columnas / Datos Excluidos y Bloqueados | Pantallas Consumidoras |
| :--- | :--- | :--- | :--- | :--- |
| `core.organizations` | `id`, `nombre`, `despliegue`, `fabrica_activa`, `creado_en`, `eliminado_en`, `idioma` (7) | `nombre` | Configuraciones internas no inventariadas | `todas`, `biz-overview`, `biz-customers` |
| `core.plans` | `codigo`, `nombre`, `lineas`, `loc_mes`, `max_usuarios` (5) | Ninguna (catálogo global) | — | `todas`, `biz-overview`, `biz-customers`, `biz-subs`, `biz-tokens` |
| `core.subscriptions` | `tenant_id`, `plan_codigo`, `estado`, `inicia_el`, `renueva_el`, `finaliza_el` (6) | Ninguna | Datos de medios de pago / tokens de pasarela | `todas`, `biz-overview`, `biz-customers`, `biz-subs` |
| `core.upgrade_requests` | `id`, `tenant_id`, `plan_deseado`, `comentario`, `urgente`, `estado`, `creado_en` (7) | `comentario` | — | `biz-subs` |
| `core.usage_cycles` | `tenant_id`, `ciclo`, `loc_consumidas`, `umbral` (4) | Ninguna | — | `biz-tokens`, `biz-customers` |
| `core.usage_tokens` | `tenant_id`, `tier`, `modelo`, `etapa`, `invocaciones`, `tokens_in`, `tokens_out`, `duracion_ms`, `creado_en` (9) | Ninguna | Prompts y respuestas LLM en claro | `biz-tokens`, `ops-models` |
| `core.usage_loc` | `tenant_id`, `ciclo`, `tipo`, `netas`, `creado_en` (5) | Ninguna | Código fuente o diffs del PR | `biz-tokens` |
| `core.users` | `tenant_id`, `nombre`, `rol`, `estado`, `ultimo_acceso` (5) | `nombre` | `password_hash`, `email`, secretos MFA, tokens de sesión (`SELECT *` falla con `permission denied`) | `biz-customers` (`CustomerDetail`) |
| `core.connections` | `tenant_id`, `categoria`, `proveedor`, `nombre`, `estado`, `ultimo_test` (6) | `nombre` | Credenciales OAuth, API keys, webhooks secrets y `config` JSON | `biz-customers` (`CustomerDetail`) |
| `core.production_lines` | `tenant_id`, `numero`, `estado` (3) | Ninguna | — | `ops-agents`, `biz-customers` |
| `core.jobs` | `tenant_id`, `id`, `ticket_id`, `estado`, `linea`, `iteraciones`, `creado_en`, `terminado_en` (8) | Ninguna | Artefactos de ejecución y variables de entorno | `ops-agents`, `ops-sla` |
| `core.tickets` | `tenant_id`, `id`, `numero`, `tipo`, `etapa`, `gate_pendiente`, `creado_en`, `cerrado_en` (8) | `numero` | Descripción libre, adjuntos y comentarios internos | `biz-overview`, `ops-sla` |
| `core.job_transitions` | `tenant_id`, `job_id`, `de_estado`, `a_estado`, `creado_en` (5) | Ninguna | — | `ops-agents`, `ops-sla` |
| `core.gate_signatures` | `tenant_id`, `ticket_id`, `gate`, `accion`, `creado_en` (5) | Ninguna | — | `ops-sla` |
| `core.llm_steps` | `tenant_id`, `etapa`, `paso`, `modelo`, `tier`, `confianza`, `validacion`, `reintentos`, `tokens_in`, `tokens_out`, `duracion_ms`, `creado_en` (12) | Ninguna | Prompts/completions (`entrada`, `salida`) | `ops-models` |
| `core.onboarding_documents` | `tenant_id`, `tipo_documento`, `estado`, `creado_en` (4) | Ninguna | Contenido binario/texto de los documentos | `biz-customers` |
| `audit.audit_events` | `id`, `tenant_id`, `ticket_id`, `job_id`, `etapa`, `actor_tipo`, `actor_id`, `evento`, `resumen`, `datos`, `sello_previo`, `sello`, `creado_en` (13) | Auditado por tenant | `INSERT`, `UPDATE`, `DELETE`, `TRUNCATE` revocados en `ro` | Auditoría y verificación de cadena central |
| `audit.chain_heads` | `tenant_id`, `ultimo_sello`, `eventos` (3) | — | `INSERT`, `UPDATE`, `DELETE`, `TRUNCATE` revocados en `ro` | Verificación de cabeza de cadena |

### 2.3 Tablas de cliente con bloqueo total (`permission denied`)

Las siguientes tablas carecen tanto de privilegios `GRANT SELECT` como de política `admin_ro_select`, rechazando cualquier consulta desde `kallicode_admin_ro` y `kallicode_admin_app` con error de motor (`permission denied`):
- `core.password_reset_tokens`
- `core.refresh_tokens`
- `core.idempotency_keys`
- `core.ticket_attachments`
- `core.webhook_inbox`
- `core.code_blobs`

### 2.4 Separación estricta de privilegios DML entre los 3 roles

1. **`kallicode_admin_ro` (`KC_ADMIN_DATABASE_URL_RO`)**:
   - Sesión abierta en modo `transaction_read_only = on`.
   - Cero privilegios `INSERT`, `UPDATE`, `DELETE`, `TRUNCATE`, `CREATE`, `ALTER` o `GRANT` en `core.*`, `audit.*` y `admin.*` (`V2_solo_lectura = 0 filas`).
   - `EXECUTE` revocado sobre todas las funciones mutacionales y de refresco `admin.refresh_*`.
2. **`kallicode_admin_app` (`KC_ADMIN_DATABASE_URL_APP`)**:
   - Único privilegio en `core.*`: `SELECT (id) ON core.organizations` para validar existencia del tenant al emitir una concesión. Cualquier intento de leer `core.organizations.nombre` o cualquier otra tabla de `core.*` lanza `permission denied`.
   - En `admin.staff_actions`: solo `SELECT, INSERT`; revocados `UPDATE, DELETE, TRUNCATE` y protegido por `trg_staff_actions_immutable` (`V5_auditoria_append_only = 0 filas`).
   - En `audit.audit_events`: solo `SELECT, INSERT` bajo la política RLS `admin_app_audit_insert` (`WITH CHECK (actor_tipo = 'staff')`), impidiendo insertar eventos en nombre de `humano`, `agente` o `sistema`.
3. **`kallicode_admin_agg` (`NOLOGIN`)**:
   - Rol sin inicio de sesión interactivo, propietario de las funciones `SECURITY DEFINER` de refresco de vistas materializadas/tablas de agregado (`admin.refresh_*`).

---

## 3. Auditoría de Enmascaramiento por Defecto y Concesiones (`admin.access_grants`)

1. **Enmascaramiento en servidor antes de serializar**:
   - [masking.py](../../apps/api/src/admin_api/masking.py) aplica el enmascaramiento antes de construir el sobre HTTP:
     - `PII_NEGOCIO`: `razon_social`, `nombre`, `dominio`, `comentario`, `conexion_nombre`, `email`, `correo`.
     - `PII_EXPEDIENTE`: `ticket_numero`, `numero`, `usuarios`, `integraciones`, `titulo` (las listas `usuarios` e `integraciones` se reemplazan por `None` conservando solo `usuarios_total` e `integraciones_total`).
     - `PII_CODIGO`: `diff`, `contenido`, `entrada`, `salida`, `fragmento`.
   - En `/admin/v1/ops/sla` ([ops.py](../../apps/api/src/admin_api/routers/ops.py)), `_tenant_visible` enmascara también `tenant_id` (`org_globex` → `o••••`) y el número de ticket cuando el empleado no posee concesión activa `datos_negocio` sobre ese tenant.
2. **Evaluación fila a fila por tenant e intransferibilidad**:
   - En listados multi-tenant (`/business/customers`, `/business/subscriptions`, `/business/upgrade-requests`, `/business/tokens`, `/ops/sla`), `enmascarar_filas` evalúa las concesiones vigentes del empleado autenticado (`st.id`) **para cada `tenant_id` individual**.
   - Una concesión activa sobre `org_acme` desenmascara únicamente la fila de `org_acme` y mantiene ofuscadas las filas de `org_globex` y del resto de organizaciones.
   - `_cargar_concesiones` filtra estrictamente `WHERE staff_id = :s AND revoked_at IS NULL AND expires_at > now()`, impidiendo reutilizar concesiones expiradas, revocadas o emitidas a otro empleado.
3. **Endurecimiento en la emisión de concesiones (`POST /admin/v1/access-grants`)**:
   - Rechaza motivos con `< 20` caracteres, motivos genéricos (`_PATRONES_VACIOS`) o sin código verificable de caso/incidencia (`_TIENE_REFERENCIA`: `KC-XXXX`, `SUP-XXXX`, `#XXXX`).
   - Restringe el alcance `contenido_codigo` a un máximo de `60` minutos y limita a `3` las concesiones simultáneas activas por empleado.

---

## 4. Auditoría del Sellado Criptográfico e Integración con Cadena Central

- **Doble registro transaccional**:
  - Toda acción administrativa y toda lectura desenmascarada por concesión invoca `registrar_accion` / `registrar_lectura` en [audit.py](../../apps/api/src/admin_api/audit.py), reutilizando la sesión `db` activa (cumpliendo la regla anti-deadlocks §2.5 de [AGENTS.md](../../AGENTS.md)).
  - Se inserta el registro en `admin.staff_actions` con sello SHA-256 encadenado local y, cuando `tenant_id IS NOT NULL`, se replica en la misma transacción hacia `audit.audit_events` y `audit.chain_heads` con semántica canónica:
    - `actor`: `{"typ": "staff", "staff_id": "...", "rol": "..."}`
    - `sello_n = SHA-256(sello_n-1 || canonico(evento_n))`
- **Política no-fuga en metadatos de auditoría**:
  - `validar_payload_sin_fuga` y `sanitizar_metadata_auditoria` bloquean claves sensibles (`password`, `token`, `secret`, `totp`, `authorization`, `cookie`, `dsn`, `private_key`, `code_blob`) antes del cálculo del hash.

---

## 5. Catálogo de Vectores Adversarios Ejecutados (`tests/test_adversario.py`)

| Vector | Prueba Automatizada | Escenario Probado | Resultado |
| :--- | :--- | :--- | :--- |
| **ADV-01** | `test_adv01_concesion_en_un_tenant_no_desenmascara_otro_tenant` | Empleado con concesión en `org_acme` consulta `/business/customers`, `/business/customers/org_globex`, `/business/subscriptions` y `/ops/sla?tenant_id=org_globex`. | **PASSED** — `org_globex` permanece enmascarado (`G•••• S.A.`, `o••••`). |
| **ADV-02** | `test_adv02_inyeccion_en_orden_paginacion_y_bloques_es_rechazada` / `test_adv02_busqueda_q_con_payload_sqli_no_filtra_ni_rompe` | Payloads SQLi en `sort`, `order`, `page_size`, `incluir`, `ciclo` y `q`. | **PASSED** — Rechazo `422` o búsqueda literal con `0` filas y cero trazas SQL. |
| **ADV-03** | `test_adv03_concesion_expirada_o_revocada_no_desenmascara_datos` | Concesiones en `admin.access_grants` con `expires_at <= now()` y `revoked_at IS NOT NULL` con JWT real de `staff_soporte`. | **PASSED** — `CustomerDetail` devuelve `A•••• S.L.` y `enmascarado` poblado. |
| **ADV-04** | `test_adv04_concesion_de_otro_empleado_no_es_transferible` | `atacante` intenta leer `org_acme` y exportar reporte individual usando la concesión vigente de `titular`. | **PASSED** — Lectura enmascarada y `403 CONCESION_REQUERIDA` en exportación. |
| **ADV-05** | `test_adv05_solicitud_concesion_rechaza_motivo_generico_y_exceso_cupo` | Motivo genérico sin código de caso, `contenido_codigo` > 60 min y 4.ª concesión simultánea. | **PASSED** — Rechazo determinista (`422` / `409`). |
| **ADV-06** | `test_adv06_rol_ro_rechaza_toda_escritura_en_core_admin_y_audit` / `test_adv06_rol_app_no_puede_falsificar_actor_no_staff_en_audit_events` | Sentencias `INSERT/UPDATE/DELETE/TRUNCATE` con `db_ro` y falsificación de `actor_tipo = 'humano'` en `audit.audit_events` con `db`. | **PASSED** — Rechazo por motor PostgreSQL y política RLS. |
| **ADV-07** | `test_adv07_rechaza_token_de_cliente_portal_mfa_caducado_y_escalada_rol` | JWT con `typ="access"`, MFA > 30 min e intento de `staff_operaciones` sobre `/business/customers` y `/staff`. | **PASSED** — Rechazo `401` / `403 ROL_STAFF_INSUFICIENTE`. |
| **ADV-08** | `test_adv08_lectura_con_concesion_sella_ambas_cadenas_y_bloquea_mutacion` | Verificación de doble sellado (`admin.staff_actions` + `audit.audit_events`), integridad de cadena y bloqueo de `UPDATE`/`DELETE`. | **PASSED** — Cadenas íntegras y mutación bloqueada por trigger y permisos. |

---

## 6. Conclusión y Sign-Off de Seguridad (Hito M6)

Todas las comprobaciones estáticas, de catálogo de PostgreSQL (`admin.validate_read_role()`), de no-fuga (`tests/test_no_leak.py`) y de ataques adversarios (`tests/test_adversario.py`) finalizan con **0 vulnerabilidades abiertas**. El modelo de acceso cross-tenant cumple íntegramente las reglas innegociables de [AGENTS.md](../../AGENTS.md) y queda aprobado para el cierre del Bloque 6 (Release MVP M6).
