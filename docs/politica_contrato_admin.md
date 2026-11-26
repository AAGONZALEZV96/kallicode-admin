# Política de Congelación y Versionado de Contrato (`/admin/v1` · Release M6)

- **Ticket:** `[KC-ADM-B6-13]` (Plan E6 `KC-ADM-12-5` · Épica EAD6 / EAD2)
- **Responsables:** ADM2 (Backend, Datos & Seguridad) en colaboración con ADM1 (Lead Full-Stack)
- **Especificación congelada:** [openapi-admin-v1.yaml](openapi-admin-v1.yaml)
- **Estado:** **VIGENTE — Línea base `1.0.0` (GA) congelada para Release Candidate M6**

---

## 1. Declaración de Congelación de Línea Base (`/admin/v1` · `1.0.0`)

A partir del corte de Release Candidate (Hito M6), queda formalmente congelado el contrato [openapi-admin-v1.yaml](openapi-admin-v1.yaml) que gobierna la comunicación entre la API FastAPI ([main.py](../apps/api/src/admin_api/main.py)) y sus consumidores internos ([clienteApi.ts](../apps/web/src/api/clienteApi.ts) en `apps/web/` y herramientas operativas internas):

- **Versión del contrato congelado:** OpenAPI `3.0.3`, `info.version: 1.0.0` (`KalliCode · API de Administración`).
- **Huella SHA-256 de congelación (`docs/openapi-admin-v1.yaml`):**
  - SHA-256 binario del archivo: `092541b0e37858c396dda59eb4f47cb4f1e011a4bb27050dced71dbc9331a43c`
  - SHA-256 canónico JSON: `ce5d2c918d57d45477e4d637855784919088e3016f9f7e28d9885351c85ebcee`
- **Superficie congelada (`31` operaciones en `7` tags canónicos):**
  1. `Salud` (`/admin/v1/health`)
  2. `Identidad y sesión` (`/admin/v1/auth/login`, `/mfa/verify`, `/mfa/enroll`, `/refresh`, `/logout`, `/forgot-password`, `/reset-password`, `/invitations/accept`)
  3. `Gestión del personal` (`/admin/v1/staff/me`, `/staff`, `/staff/invitations`, `/staff/{staff_id}`)
  4. `Concesiones de acceso` (`/admin/v1/access-grants`, `/access-grants/{grant_id}`)
  5. `Consola de negocio` (`/admin/v1/business/overview`, `/customers`, `/customers/{tenant_id}`, `/subscriptions`, `/upgrade-requests`, `/usage/tokens`, `/reports`, `/reports/{report_id}`)
  6. `Consola de operaciones` (`/admin/v1/ops/agents`, `/queues`, `/models`, `/sla`, `/sla/cases/{job_id}`)
  7. `Auditoría del personal` (`/admin/v1/audit/staff-actions`, `/audit/staff-actions/exports`)
- **Rutas internas excluidas del esquema contractual (`include_in_schema=False`):**
  - Sonda Prometheus (`/admin/v1/metrics`, `/metrics`), alias retrocompatible `/admin/v1/business/summary` y puente de transparencia del portal (`/api/v1/audit/staff-accesses`, `/audit/staff-accesses`).
- **Componentes de contrato inmutables en `1.0.0`:**
  - `BearerAuth` (`type: http`, `scheme: bearer`, `bearerFormat: JWT`, claims obligatorios `typ=staff`, `iss=kallicode-admin`, `aud=admin-v1`).
  - `ErrorStandard` (`codigo`, `code`, `mensaje`, `detalle`, `trace_id`, `timestamp` con `nullable: true` en `detalle`).
  - `CustomerSummary` (declara explícitamente el enmascaramiento por defecto en `name` salvo concesión activa).
  - Validación estricta `extra="forbid"` en los modelos Pydantic de entrada.

---

## 2. Taxonomía Estricta de Cambios Post-Release (SemVer)

La ruta raíz `/admin/v1` representa la versión mayor `v1` (`1.x.y`). Todo cambio posterior al Hito M6 debe clasificarse antes de abrir Pull Request:

### 2.1 Cambios Compatibles (Permitidos dentro de `/admin/v1` — `MINOR` / `PATCH`)
Se permiten dentro de `/admin/v1` siempre que **no rompan consumidores existentes** que ignoren campos desconocidos:
- Adición de nuevos endpoints bajo `/admin/v1/*`.
- Adición de **campos opcionales** en respuestas JSON (el frontend `apps/web/` nunca debe asumir listas cerradas destructivas).
- Adición de **parámetros de query opcionales** con valor por defecto idéntico al comportamiento previo.
- Ampliación de documentación descriptiva o incorporación de campos de entrada opcionales (como `recurso` en `CrearIn`) que mantengan compatibilidad con peticiones anteriores.

### 2.2 Cambios Incompatibles / *Breaking Changes* (Prohibidos en `/admin/v1` — Exigen `/admin/v2`)
Quedan **terminantemente prohibidos** sobre cualquier ruta existente de `/admin/v1`:
1. Eliminar, mover o renombrar un endpoint existente.
2. Eliminar o renombrar propiedades en peticiones o respuestas JSON.
3. Cambiar el tipo de dato, formato (por ejemplo `date-time`) o restringir la nulabilidad de un campo existente.
4. Añadir nuevos parámetros de query, cabecera o propiedades del cuerpo con **`required: true`** sobre una operación existente.
5. Modificar el significado o eliminar códigos HTTP / códigos canónicos de error en [errors.py](../apps/api/src/admin_api/errors.py) (`_ERRORES_ADMIN`: `CREDENCIALES_INVALIDAS`, `TOKEN_INVALIDO`, `MFA_REQUERIDO`, `MFA_INVALIDO`, `MFA_NO_INSCRITO`, `STAFF_DESACTIVADO`, `ROL_STAFF_INSUFICIENTE`, `ACCESO_NO_JUSTIFICADO`, `CONCESION_CADUCADA`, `CONCESION_DUPLICADA`, `CONFLICTO_ESTADO`, `MOTIVO_INSUFICIENTE`, `AGREGADO_NO_DISPONIBLE`, `SLA_SIN_DEFINICION`, `TELEMETRIA_NO_DISPONIBLE`, `JOB_NO_ENCONTRADO`).
6. Relajar invariantes de seguridad (enmascaramiento por defecto, verificación MFA, `extra="forbid"` o auditoría append-only).

Cualquiera de estos cambios obliga obligatoriamente a introducir el prefijo **`/admin/v2`**.

---

## 3. Regla de Convivencia y Gobernanza (Plan de Programa §9.4)

1. **Periodo mínimo de convivencia (`>= 1 sprint`):**
   - Ningún endpoint o comportamiento de `/admin/v1` puede retirarse sin haber mantenido **al menos un sprint completo de convivencia simultánea** con la alternativa en `/admin/v2` (o el nuevo campo compatible).
2. **Protocolo formal de aprobación:**
   - **Anuncio:** comunicación obligatoria en el **Scrum de Scrums del miércoles anterior** detallando impacto en `apps/web/` y consumidores internos.
   - **Aprobación:** validación formal por el **Architecture Board** (ADM1 + ADM2 + representante de plataforma).
   - **Registro ADR:** creación obligatoria de un nuevo registro de decisión arquitectónica en `docs/adr/` continuando la numeración de [001-arquitectura-consola.md](adr/001-arquitectura-consola.md).

---

## 4. Política de Deprecación Explícita vía Cabeceras HTTP

- **Estado actual (`v1.0.0` GA):** existen **0 endpoints deprecados**.
- **Regla para futuras deprecaciones:** cuando un endpoint de `/admin/v1` entre en ventana de retirada tras aprobarse un sucesor en `/admin/v2`, la API FastAPI deberá responder incluyendo cabeceras estándar IETF:
  - `Deprecation: @<unix_timestamp>` (RFC 9745, instante exacto desde el cual la operación queda deprecada; o `true` cuando aplique interoperabilidad heredada).
  - `Sunset: <HTTP-date GMT>` (RFC 8594, fecha efectiva de apagado tras cumplir el sprint mínimo de convivencia).
  - `Link: </admin/v2/...>; rel="successor-version"` apuntando al recurso sucesor y/o a la nota de migración.

---

## 5. Control Automatizado de No-Regresión y Sincronización Frontend

- **Puerta de congelación y compatibilidad:** [tests/test_contract_freeze.py](../tests/test_contract_freeze.py) falla automáticamente en CI si se altera sin aprobación [openapi-admin-v1.yaml](openapi-admin-v1.yaml) o si `app.openapi()` de FastAPI introduce cualquier *breaking change* frente a la línea base `1.0.0`.
- **Puerta estructural y fuzzing:** [tests/test_openapi_contract.py](../tests/test_openapi_contract.py) valida mediante Schemathesis las `31` operaciones sembradas, esquemas `ErrorStandard`/`BearerAuth`/`CustomerSummary` y rechazo `extra="forbid"`.
- **Sincronización con SPA (`apps/web/`):** todo cambio compatible en `/admin/v1` requiere actualizar en el mismo bloque [clienteApi.ts](../apps/web/src/api/clienteApi.ts), los mocks de [msw_handlers.ts](../apps/web/src/pruebas/msw_handlers.ts) y ejecutar `npm --prefix apps/web run build` + `npm --prefix apps/web test`.
