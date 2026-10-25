# Catálogo de Roles de Staff y Matriz de Permisos de la Consola Admin

- **Documento:** `docs/matriz-permisos-staff.md`
- **Versión:** 1.1.0
- **Ticket de Referencia:** KC-ADM-B1-09 (Épica EAD1)
- **Superficie de Exposición:** `/admin/v1` (Red Privada - Zero Ingress Público)
- **Ámbito:** Personal Interno de KalliCode (`admin.staff`)

---

## 1. Definición y Alcance de los 4 Roles de Staff

El acceso a la consola de administración (`/admin/v1`) está restringido exclusivamente a 4 roles de personal, diseñados bajo el principio de menor privilegio:

### 1.1 `staff_soporte` (Atención y Soporte Técnico)
- **Alcance Funcional**: Atención directa a clientes, diagnóstico de incidencias y revisión de expediente técnico.
- **Acceso Permitido**:
  - Consulta del listado y fichas individuales de clientes (con datos identificables y razón social enmascarados por defecto).
  - Consulta de expedientes técnicos y lectura de datos identificables **únicamente bajo una concesión temporal activa y justificada** (`admin.access_grants`).
  - Creación y revocación de sus propias concesiones de acceso.
  - Descarga de informes solicitados previamente.
  - Consulta de su propio historial de acciones de auditoría (`ambito=propias`).
- **Restricciones Innegociables**:
  - **NUNCA** accede a agregados de negocio (MRR, churn, facturación, volumen global).
  - **NUNCA** accede a telemetría de operaciones ni salud de infraestructura (agentes, colas, SLAs).
  - **NUNCA** accede a la gestión ni administración de personal (`/admin/v1/staff`).

### 1.2 `staff_operaciones` (Guardia Técnica, SRE y Fábrica de Software)
- **Alcance Funcional**: Supervisión técnica de la fábrica de software, salud de agentes, monitoreo de colas de mensajería, rendimiento de modelos LLM y cumplimiento de acuerdos SLA.
- **Acceso Permitido**:
  - Telemetría en vivo de agentes de IA y líneas de producción.
  - Inspección de profundidad de colas y Dead Letter Queues (DLQ).
  - Métricas de latencia, disponibilidad, tasa de error y escalado de tiers de modelos LLM.
  - Evaluación y seguimiento de SLAs y desglose de pausas de reloj de jobs.
  - Creación y gestión de sus propias concesiones de acceso temporal.
  - Consulta de su propio historial de acciones de auditoría (`ambito=propias`).
- **Restricciones Innegociables**:
  - **No accede** a datos comerciales, agregados de negocio ni suscripciones.
  - **No accede** a código fuente ni datos identificables de clientes sin una concesión explícita.
  - **No accede** a la administración de personal.

### 1.3 `staff_negocio` (Comercial, Dirección y Métricas)
- **Alcance Funcional**: Gestión comercial, control de contratos, suscripciones, consumo global de tokens y reportería analítica.
- **Acceso Permitido**:
  - Panel general de negocio (MRR, churn, cartera global).
  - Listado de clientes, suscripciones por aniversario y solicitudes de upgrade de planes.
  - Monitorización consolidada de consumo de tokens y verificación de costes.
  - Solicitud (encolado) y descarga de reportes comerciales e históricos exportables.
  - Métricas de modelos LLM y SLAs para dimensionamiento comercial.
  - Creación y gestión de sus propias concesiones de acceso temporal.
  - Consulta de su propio historial de acciones de auditoría (`ambito=propias`).
- **Restricciones Innegociables**:
  - Los datos identificables de clientes (PII, correos, dominios) se devuelven **enmascarados por defecto** salvo que exista concesión temporal activa.
  - **No accede** a telemetría profunda de infraestructura (agentes ni colas de mensajería).
  - **No accede** a la gestión de personal ni auditoría global.

### 1.4 `staff_admin` (Super-Rol de Staff y Cumplimiento)
- **Alcance Funcional**: Gobierno general, auditoría forense integral, seguridad y administración completa del ciclo de vida del personal.
- **Acceso Permitido**:
  - Super-rol de staff; incluye la totalidad de accesos de los roles anteriores (soporte, operaciones y negocio).
  - Gestión completa de cuentas de personal (`/admin/v1/staff`): invitar nuevos empleados, modificar roles y suspender/desactivar cuentas.
  - Supervisión y revocación anticipada de concesiones de acceso ajenas (`admin.access_grants`).
  - Auditoría forense completa de todas las acciones de todos los empleados (`/admin/v1/audit/staff-actions?ambito=todas`).
  - Exportación certificada de registros de auditoría inmutables sellados criptográficamente.

---

## 2. Catálogo de Permisos Internos

Los permisos representan las capacidades atómicas de la API de administración. Se derivan dinámicamente del rol del empleado autenticado y son expuestos en `/admin/v1/staff/me` para gobernar las pantallas y capacidades de la interfaz web.

### 2.1 Lista Canónica de Permisos

| Permiso Interno | Módulo / Dominio | Descripción |
|---|---|---|
| `negocio.overview.leer` | Negocio | Consulta de métricas agregadas globales (MRR, churn, salud de cartera). |
| `negocio.clientes.leer` | Negocio / Clientes | Listado y consulta de fichas individuales de clientes (enmascaradas sin concesión). |
| `negocio.suscripciones.leer` | Negocio | Consulta de suscripciones por aniversario y solicitudes de upgrade. |
| `negocio.tokens.leer` | Negocio | Consulta de consumo de tokens LLM y costes asociados. |
| `informes.crear` | Negocio / Reportes | Solicitud de generación asíncrona de reportes comerciales. |
| `informes.descargar` | Negocio / Reportes | Descarga de reportes analíticos generados. |
| `ops.telemetria.leer` | Operaciones | Telemetría en tiempo real de agentes y líneas de producción. |
| `ops.colas.leer` | Operaciones | Inspección de profundidad de colas de mensajería y DLQ. |
| `ops.modelos.leer` | Operaciones | Latencia, tasa de error y escalado de modelos de IA. |
| `ops.sla.leer` | Operaciones | Monitoreo de cumplimiento de SLAs y casos individuales con pausas. |
| `personal.gestionar` | Personal | Invitación, modificación de rol y desactivación de cuentas de staff. |
| `personal.leer` | Personal | Listado y visualización de cuentas de personal y su estado. |
| `concesiones.solicitar` | Concesiones | Solicitud justificada de concesiones de acceso temporal a datos de cliente. |
| `concesiones.propias` | Concesiones | Visualización y revocación de concesiones propias. |
| `concesiones.todas` | Concesiones | Inspección global de todas las concesiones de acceso del personal. |
| `concesiones.revocar_ajenas` | Concesiones | Revocación forzosa de concesiones pertenecientes a otros empleados. |
| `auditoria.propias` | Auditoría | Consulta de la traza de auditoría de las acciones realizadas por el propio empleado. |
| `auditoria.total.leer` | Auditoría | Consulta forense global de todas las acciones de todos los empleados de staff. |
| `auditoria.exportar` | Auditoría | Exportación formal de registros de auditoría sellados por hash chain. |
| `expediente.leer` | Clientes / Datos | Acceso y lectura a datos identificables y expediente técnico bajo concesión. |

### 2.2 Mapeo Canónico de Permisos por Rol

```
staff_soporte:
  ├── negocio.clientes.leer
  ├── expediente.leer
  ├── concesiones.solicitar
  ├── concesiones.propias
  ├── informes.descargar
  └── auditoria.propias

staff_operaciones:
  ├── ops.telemetria.leer
  ├── ops.colas.leer
  ├── ops.modelos.leer
  ├── ops.sla.leer
  ├── concesiones.solicitar
  ├── concesiones.propias
  ├── informes.descargar
  └── auditoria.propias

staff_negocio:
  ├── negocio.overview.leer
  ├── negocio.clientes.leer
  ├── negocio.suscripciones.leer
  ├── negocio.tokens.leer
  ├── informes.crear
  ├── informes.descargar
  ├── ops.modelos.leer
  ├── ops.sla.leer
  ├── concesiones.solicitar
  ├── concesiones.propias
  └── auditoria.propias

staff_admin:
  ├── negocio.overview.leer
  ├── negocio.clientes.leer
  ├── negocio.suscripciones.leer
  ├── negocio.tokens.leer
  ├── informes.crear
  ├── informes.descargar
  ├── ops.telemetria.leer
  ├── ops.colas.leer
  ├── ops.modelos.leer
  ├── ops.sla.leer
  ├── personal.gestionar
  ├── personal.leer
  ├── concesiones.solicitar
  ├── concesiones.propias
  ├── concesiones.todas
  ├── concesiones.revocar_ajenas
  ├── auditoria.propias
  ├── auditoria.total.leer
  ├── auditoria.exportar
  └── expediente.leer
```

---

## 3. Matriz Exhaustiva de Autorización de los 31 Endpoints (/admin/v1)

A continuación se detalla la matriz canónica de control de acceso basada en roles (RBAC) para los **31 endpoints** expuestos bajo el prefijo `/admin/v1`:

| # | Método | Ruta del Endpoint | Descripción Funcional | staff_soporte | staff_operaciones | staff_negocio | staff_admin |
|---|---|---|---|:---:|:---:|:---:|:---:|
| **1** | `GET` | `/admin/v1/health` | Sonda de salud y frescura de la API | ✅ | ✅ | ✅ | ✅ |
| **2** | `POST` | `/admin/v1/auth/login` | Inicio de sesión de staff (1er factor Argon2id) | ✅ | ✅ | ✅ | ✅ |
| **3** | `POST` | `/admin/v1/auth/mfa/verify` | Validación 2FA / TOTP y emisión de tokens | ✅ | ✅ | ✅ | ✅ |
| **4** | `POST` | `/admin/v1/auth/mfa/enroll` | Inscripción o reinscripción de TOTP | ✅ | ✅ | ✅ | ✅ |
| **5** | `POST` | `/admin/v1/auth/refresh` | Rotación obligatoria de refresh token de staff | ✅ | ✅ | ✅ | ✅ |
| **6** | `POST` | `/admin/v1/auth/logout` | Cierre de sesión y marcado de JTI en denylist | ✅ | ✅ | ✅ | ✅ |
| **7** | `POST` | `/admin/v1/auth/forgot-password` | Solicitud de restablecimiento (anti-enumeración) | ✅ | ✅ | ✅ | ✅ |
| **8** | `POST` | `/admin/v1/auth/reset-password` | Restablecer contraseña con token de un solo uso | ✅ | ✅ | ✅ | ✅ |
| **9** | `POST` | `/admin/v1/staff/invitations/accept` | Alta y activación de empleado invitado | ✅ | ✅ | ✅ | ✅ |
| **10** | `GET` | `/admin/v1/staff/me` | Perfil del empleado autenticado y permisos | ✅ | ✅ | ✅ | ✅ |
| **11** | `GET` | `/admin/v1/staff` | Listar catálogo de personal interno | ❌ | ❌ | ❌ | ✅ |
| **12** | `POST` | `/admin/v1/staff/invitations` | Invitar a un nuevo empleado (dominio corporativo) | ❌ | ❌ | ❌ | ✅ |
| **13** | `PATCH` | `/admin/v1/staff/{staff_id}` | Modificar rol o suspender/desactivar empleado | ❌ | ❌ | ❌ | ✅ |
| **14** | `POST` | `/admin/v1/access-grants` | Solicitar concesión temporal justificada | ✅ | ✅ | ✅ | ✅ |
| **15** | `GET` | `/admin/v1/access-grants` | Listar concesiones (`ambito=propias` / `todas`) | ✅* | ✅* | ✅* | ✅ |
| **16** | `DELETE` | `/admin/v1/access-grants/{grant_id}` | Revocación anticipada de concesión | ✅* | ✅* | ✅* | ✅ |
| **17** | `GET` | `/admin/v1/business/overview` | Panel general de negocio (MRR, churn, agregados) | ❌ | ❌ | ✅ | ✅ |
| **18** | `GET` | `/admin/v1/business/customers` | Listado general de clientes | ✅** | ❌ | ✅** | ✅** |
| **19** | `GET` | `/admin/v1/business/customers/{tenant_id}` | Ficha consolidada individual de cliente | ✅** | ❌ | ✅** | ✅** |
| **20** | `GET` | `/admin/v1/business/subscriptions` | Suscripciones por aniversario de contrato | ❌ | ❌ | ✅ | ✅ |
| **21** | `GET` | `/admin/v1/business/upgrade-requests` | Solicitudes de cambio y ampliación de plan | ❌ | ❌ | ✅ | ✅ |
| **22** | `GET` | `/admin/v1/business/usage/tokens` | Consumo global de tokens y costes de tiers | ❌ | ❌ | ✅ | ✅ |
| **23** | `POST` | `/admin/v1/business/reports` | Encolar generación de reporte analítico | ❌ | ❌ | ✅ | ✅ |
| **24** | `GET` | `/admin/v1/business/reports/{report_id}` | Descarga de reporte generado (URL SAS) | ✅* | ✅* | ✅* | ✅ |
| **25** | `GET` | `/admin/v1/ops/agents` | Telemetría de agentes y líneas de producción | ❌ | ✅ | ❌ | ✅ |
| **26** | `GET` | `/admin/v1/ops/queues` | Profundidad de colas y Dead Letter Queues (DLQ) | ❌ | ✅ | ❌ | ✅ |
| **27** | `GET` | `/admin/v1/ops/models` | Métricas de latencia, disponibilidad y tiers LLM | ❌ | ✅ | ✅ | ✅ |
| **28** | `GET` | `/admin/v1/ops/sla` | Cumplimiento de acuerdos de nivel de servicio (SLA)| ❌ | ✅ | ✅ | ✅ |
| **29** | `GET` | `/admin/v1/ops/sla/cases/{job_id}` | Desglose cronológico de reloj y pausas de job | ❌ | ✅ | ✅ | ✅ |
| **30** | `GET` | `/admin/v1/audit/staff-actions` | Registro de acciones del personal (HMAC chain) | ✅* | ✅* | ✅* | ✅ |
| **31** | `POST` | `/admin/v1/audit/staff-actions/exports` | Exportación formal y certificada de auditoría | ❌ | ❌ | ❌ | ✅ |

*Notas de Ámbito y Enmascaramiento:*
- **✅**: Acceso permitido.
- **❌**: Acceso denegado con respuesta estricta HTTP 403 Forbidden y sobre de error `ROL_STAFF_INSUFICIENTE`.
- **(\*) Ámbito Propio vs Todas**: Para roles `staff_soporte`, `staff_operaciones` y `staff_negocio`, los endpoints de listado de concesiones, descarga de reportes y auditoría operan por defecto en ámbito de sus propios registros (`staff_id = usuario_actual`). El parámetro `ambito=todas` y la revocación de concesiones ajenas están estrictamente restringidos a `staff_admin`.
- **(\*\*) Enmascaramiento por Defecto**: En los endpoints de clientes (`/admin/v1/business/customers*`), la razón social (`A•••• S.L.`), correos y datos identificables se retornan ofuscados por defecto. Solo se revelan en claro si el empleado cuenta con una concesión activa en `admin.access_grants` para dicho `tenant_id`.

---

## 4. Reglas Transversales de Seguridad

### 4.1 Identidad y Tokens Staff Innegociables
1. **Tipado Estricto de JWT**:
   Todo token de acceso debe contener sin excepción los siguientes claims verificados criptográficamente:
   - `typ="staff"` (un token con `typ="user"` o sin typ es rechazado de inmediato con HTTP 401).
   - `iss="kallicode-admin"` y `aud="admin-v1"`.
   - `sub`: Identificador del empleado (`st_<ulid>`).
   - `rol`: Uno de los 4 roles canónicos (`staff_soporte`, `staff_operaciones`, `staff_negocio`, `staff_admin`).
   - `mfa`: Marca Unix timestamp de la verificación del segundo factor.
   - `jti`, `iat`, `exp`.
2. **Segundo Factor (MFA) Obligatorio**:
   - Sesión de access token con TTL máximo de 15 minutos.
   - Inactividad máxima de 30 minutos (`staff_idle_timeout_min`). Si transcurre más tiempo desde la marca `mfa`, la petición es rechazada con HTTP 403 `MFA_REQUERIDO`.
3. **Verificación de Rol y Estado en Base de Datos**:
   - En cada petición, el rol y estado activo del empleado se confirman en PostgreSQL (`admin.staff`). Si el empleado fue degradado o desactivado, la petición se bloquea de inmediato sin esperar a la caducidad del JWT.
4. **Denylist en Redis para Revocación Inmediata**:
   - El logout o desactivación registra el `jti` en `admin:denylist:{jti}` en Redis durante el tiempo restante de vida del token, impidiendo su reutilización.

### 4.2 Acceso Justificado a Datos Identificables (Concesiones Temporales)
- Los datos de clientes no son accesibles de forma indiscriminada.
- Toda consulta de expediente o revelación de PII exige una concesión en `admin.access_grants`.
- La solicitud exige motivo fundado (mínimo 20 caracteres y sin justificaciones genéricas como "revisión").
- La concesión tiene duración temporal estricta y queda registrada en la cadena inmutable de auditoría.

---

## 5. Manejo Canónico de Violaciones de Autorización

Cuando un empleado autenticado intenta consumir un endpoint fuera del ámbito permitido para su rol:
1. Las dependencias `exigir` o `exigir_rol` interceptan la petición antes de ejecutar cualquier consulta a base de datos.
2. La API responde estrictamente con:
   - **Código HTTP:** `403 Forbidden`
   - **Formato de respuesta (Sobre Oficial):**

```json
{
  "error": {
    "codigo": "ROL_STAFF_INSUFICIENTE",
    "mensaje": "Tu rol no permite esta operación.",
    "trace_id": "tr_01HZ98234ABCDEF12345678",
    "timestamp": "2026-10-25T19:40:00Z"
  }
}
```

> [!NOTE]
> Por higiene de seguridad y prevención de fuga de información de arquitectura interna, el mensaje de error nunca enumera qué roles tienen acceso ni detalles internos de la base de datos.
