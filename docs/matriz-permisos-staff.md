# Catálogo de Roles de Staff y Matriz de Permisos de la Consola Admin

- **Documento:** `docs/matriz-permisos-staff.md`
- **Versión:** 1.0.0
- **Superficie de Exposición:** `/admin/v1` (Red Privada - Zero Ingress Público)
- **Ámbito:** Personal Interno de KalliCode (`admin.staff`)

---

## 1. Arquitectura de Identidad y Aislamiento de Personal

El personal de KalliCode opera bajo un **realm de identidad física y lógicamente separado** del realm de clientes:
1. **Separación de Tablas**: El personal no existe en la tabla de clientes `core.users`. Toda cuenta de personal reside exclusivamente en la tabla global `admin.staff` (sin columna `tenant_id`).
2. **Token Tipado Estricto**: Todo JWT emitido por la API de administración incluye obligatoriamente el claim `typ=staff`, emisor corporativo (`iss=kallicode-admin`), audiencia (`aud=kallicode-admin-api`) y la marca temporal de segundo factor `mfa`. Un token con `typ=staff` es rechazado de inmediato en `/api/v1` y `/internal/v1`.
3. **MFA y Sesión Corta**: Segundo factor TOTP obligatorio sin excepción. La sesión caduca a los 15 minutos para el access token, 8 horas para el refresh token, y tiene un tiempo de inactividad máximo de 30 minutos, tras el cual se exige revalidación de TOTP.
4. **Verificación en Base de Datos**: Para mitigar el hallazgo de seguridad BE-F11, el rol y estado (`status='active'`) del empleado se consultan directamente en PostgreSQL en cada petición HTTP, invalidando de inmediato cualquier sesión de un empleado degradado o desactivado.

---

## 2. Catálogo de Roles de Staff

Se establecen cuatro roles mutuamente excluyentes bajo el principio de privilegio mínimo:

### 2.1 `staff_soporte` (Atención y Soporte Técnico)
- **Propósito**: Diagnóstico, triaje e investigación de incidencias reportadas por clientes.
- **Capacidades**:
  - Consulta del listado de clientes y fichas individuales de soporte.
  - Creación y gestión de sus propias concesiones de acceso temporal (`access-grants`).
  - Lectura de tickets, expedientes y evidencias de clientes **únicamente bajo una concesión vigente y justificada**.
- **Restricciones**:
  - No puede ver agregados comerciales globales (MRR, facturación, volumen total de plataforma).
  - No puede consultar métricas de infraestructura (agentes, colas, rendimiento global de modelos).
  - No puede gestionar cuentas de personal ni revocar concesiones ajenas.

### 2.2 `staff_operaciones` (Guardia Técnica y SRE)
- **Propósito**: Monitorización continua de la salud de la fábrica de software, colas de mensajería y estabilidad de modelos de IA.
- **Capacidades**:
  - Visualización del estado en vivo de agentes y líneas de producción en la plataforma.
  - Inspección de profundidad de colas de mensajería y Dead Letter Queues (DLQ).
  - Monitorización de latencia, disponibilidad, tasa de error y escalado de tiers de modelos LLM.
  - Evaluación del cumplimiento de acuerdos de nivel de servicio (SLA) y desglose cronológico de pausas de reloj.
- **Restricciones**:
  - No tiene acceso a datos comerciales (MRR, suscripciones, facturación).
  - No tiene acceso por defecto a datos identificables ni código fuente de clientes.

### 2.3 `staff_negocio` (Comercial y Dirección)
- **Propósito**: Gestión comercial, control de contratos, renovaciones y análisis de rentabilidad.
- **Capacidades**:
  - Visualización del panel general de negocio (MRR, churn, clientes activos por plan).
  - Gestión de cartera de clientes, suscripciones por aniversario y solicitudes de upgrade de plan.
  - Monitorización del consumo consolidado de tokens y comprobación de cuadre contra facturación.
  - Encolado y descarga de reportes comerciales e históricos exportables (CSV / XLSX).
- **Restricciones**:
  - Todos los datos PII e identificadores de clientes (razón social, dominio, usuarios) retornan enmascarados salvo concesión activa.
  - No tiene acceso a la telemetría operativa de agentes ni a la inspección de colas del pipeline.
  - No puede administrar cuentas de empleados.

### 2.4 `staff_admin` (Administración de Plataforma y Cumplimiento)
- **Propósito**: Gobierno global, auditoría forense, seguridad y administración de personal.
- **Capacidades**:
  - Acceso irrestricto a todas las consolas (negocio y operaciones).
  - Gestión del ciclo de vida del personal: invitar empleados, modificar roles y desactivar cuentas.
  - Auditoría global de todas las acciones realizadas por el personal (`ambito=todas`).
  - Revocación anticipada de concesiones de acceso ajenas en caso de anomalía.
  - Exportación formal y certificada de registros de auditoría sellados criptográficamente.

---

## 3. Principios de Seguridad y Menor Privilegio

1. **Enmascarado por Defecto (Default Masking)**:
   Los endpoints que devuelven información de clientes ofuscan automáticamente la razón social (`A•••• S.L.`), correos y dominios. La revelación de datos en claro exige una concesión activa con alcance `datos_negocio` o `expediente`.
2. **Acceso Justificado y Temporal (`access-grants`)**:
   El acceso a datos de un tenant no es permanente:
   - Requiere justificación explícita de al menos 20 caracteres con referencia verificable a un ticket/incidencia (rechazo automático de motivos genéricos como "revisión" o "soporte").
   - Caduca automáticamente (máximo 4 horas para negocio/expediente; máximo 60 minutos para contenido de código).
   - Queda sellado en la cadena de bloques inmutable del tenant (`core.audit_events`) y es visible para el cliente desde su propio portal.
3. **Violación de Autorización**:
   Cualquier petición realizada por un empleado con un rol no autorizado en el endpoint es interceptada inmediatamente por el guardián de autorización, respondiendo con código HTTP 403 `ROL_STAFF_INSUFICIENTE`.

---

## 4. Matriz Exhaustiva de Permisos (/admin/v1)

A continuación se detalla la matriz de control de acceso basada en roles (RBAC) para los **31 endpoints** de la API de administración:

| # | Método | Ruta del Endpoint | Descripción Funcional | Soporte | Operaciones | Negocio | Admin | Restricción / Concesión Adicional |
|---|---|---|---|:---:|:---:|:---:|:---:|---|
| **1** | `POST` | `/admin/v1/auth/login` | Iniciar sesión (1er factor) | Público | Público | Público | Público | Red privada; sin token previo. |
| **2** | `POST` | `/admin/v1/auth/mfa/verify` | Verificar TOTP y emitir JWT | Desafío | Desafío | Desafío | Desafío | Exige token efímero `mfa_token`. |
| **3** | `POST` | `/admin/v1/auth/mfa/enroll` | Inscribir o reinscribir 2FA | ✅ | ✅ | ✅ | ✅ | Requiere `mfa_token` o contraseña vigente. |
| **4** | `POST` | `/admin/v1/auth/refresh` | Rotación de sesión de staff | ✅ | ✅ | ✅ | ✅ | Refresh token de staff (máx 30 min inactividad). |
| **5** | `POST` | `/admin/v1/auth/logout` | Cierre de sesión y denylist | ✅ | ✅ | ✅ | ✅ | Invalida JTI en Redis inmediatamente. |
| **6** | `POST` | `/admin/v1/auth/forgot-password` | Solicitar reset de password | Público | Público | Público | Público | Respuesta 204 constante anti-enumeración. |
| **7** | `POST` | `/admin/v1/auth/reset-password` | Restablecer contraseña | Token | Token | Token | Token | Exige token de un solo uso recibido por correo. |
| **8** | `POST` | `/admin/v1/staff/invitations/accept` | Alta de empleado invitado | Token | Token | Token | Token | Exige token de invitación válido (7 días). |
| **9** | `GET` | `/admin/v1/staff/me` | Perfil del empleado actual | ✅ | ✅ | ✅ | ✅ | Solo lectura de identidad y permisos propios. |
| **10** | `GET` | `/admin/v1/staff` | Listar catálogo de personal | ❌ | ❌ | ❌ | ✅ | Exclusivo `staff_admin`. |
| **11** | `POST` | `/admin/v1/staff/invitations` | Invitar nuevo empleado | ❌ | ❌ | ❌ | ✅ | Exclusivo `staff_admin`. Dominio corporativo. |
| **12** | `PATCH` | `/admin/v1/staff/{staff_id}` | Cambiar rol o desactivar cuenta | ❌ | ❌ | ❌ | ✅ | Exclusivo `staff_admin`. Prohibida autodesactivación. |
| **13** | `POST` | `/admin/v1/access-grants` | Solicitar concesión temporal | ✅ | ✅ | ✅ | ✅ | Requiere motivo válido (mín. 20 caracteres). |
| **14** | `GET` | `/admin/v1/access-grants` | Listar concesiones de acceso | Propias | Propias | Propias | ✅ Todas | Ámbito `todas` restringido a `staff_admin`. |
| **15** | `DELETE` | `/admin/v1/access-grants/{grant_id}` | Revocar concesión anticipada | Propias | Propias | Propias | ✅ Ajenas | Revocar concesión ajena exige `staff_admin` + motivo. |
| **16** | `GET` | `/admin/v1/business/overview` | Panel global (MRR, churn) | ❌ | ❌ | ✅ | ✅ | Métricas agregadas de vistas materializadas. |
| **17** | `GET` | `/admin/v1/business/customers` | Listado general de clientes | ✅* | ❌ | ✅* | ✅* | *Razón social enmascarada sin concesión activa. |
| **18** | `GET` | `/admin/v1/business/customers/{tenant_id}` | Ficha de cliente consolidada | ✅* | ❌ | ✅* | ✅* | *PII y usuarios ofuscados sin concesión activa. |
| **19** | `GET` | `/admin/v1/business/subscriptions` | Suscripciones y renovaciones | ❌ | ❌ | ✅ | ✅ | Fechas calculadas por aniversario de contrato. |
| **20** | `GET` | `/admin/v1/business/upgrade-requests` | Solicitudes de cambio de plan | ❌ | ❌ | ✅ | ✅ | Cola comercial de upgrades solicitados. |
| **21** | `GET` | `/admin/v1/business/usage/tokens` | Consumo de tokens y costes | ❌ | ❌ | ✅ | ✅ | Desglose por tiers (flash/pro/fable) y validación. |
| **22** | `POST` | `/admin/v1/business/reports` | Solicitar reporte asíncrono | ❌ | ❌ | ✅ | ✅ | Incluir PII (`incluir_identificables=true`) exige grant. |
| **23** | `GET` | `/admin/v1/business/reports/{report_id}` | Descarga de reporte generado | Propios | Propios | Propios | ✅ Todos | URL SAS temporal de Azure Blob Storage (15 min). |
| **24** | `GET` | `/admin/v1/ops/agents` | Telemetría de agentes y líneas | ❌ | ✅ | ❌ | ✅ | Distingue 'sin trabajo' de 'sin telemetría'. |
| **25** | `GET` | `/admin/v1/ops/queues` | Profundidad de colas y DLQ | ❌ | ✅ | ❌ | ✅ | Monitoreo de latencia y mensajes en tránsito. |
| **26** | `GET` | `/admin/v1/ops/models` | Latencia y disponibilidad LLM | ❌ | ✅ | ✅ | ✅ | Desglose por modelo, proveedor y escalados de tier. |
| **27** | `GET` | `/admin/v1/ops/sla` | Cumplimiento de acuerdos SLA | ❌ | ✅ | ✅ | ✅ | Cálculo con exclusión de pausas justificadas. |
| **28** | `GET` | `/admin/v1/ops/sla/cases/{job_id}` | Desglose de reloj de un caso | ❌ | ✅ | ✅ | ✅ | Detalle de tramos computados vs tramos en pausa. |
| **29** | `GET` | `/admin/v1/audit/staff-actions` | Registro de acciones del staff | Propias | Propias | Propias | ✅ Todas | Consulta de auditoría inmutable sellada por HMAC. |
| **30** | `POST` | `/admin/v1/audit/staff-actions/exports` | Exportar auditoría formal | ❌ | ❌ | ❌ | ✅ | Exclusivo `staff_admin`. Incluye prueba criptográfica. |
| **31** | `GET` | `/admin/v1/health` | Sonda de salud y frescura | Público | Público | Público | Público | Red privada; sin autenticación. |

---

## 5. Manejo de Violaciones de Autorización

Cuando un empleado autenticado intenta acceder a un endpoint cuyo perfil no lo autoriza:
1. El guardián `exigir_rol_staff` intercepta la solicitud antes de ejecutar cualquier lógica de negocio o consulta a base de datos.
2. Se eleva de forma inmediata la excepción con código HTTP `403 Forbidden`.
3. El middleware genera la respuesta estructurada bajo el sobre oficial de la plataforma:

```json
{
  "error": {
    "codigo": "ROL_STAFF_INSUFICIENTE",
    "mensaje": "Tu rol no permite esta operación.",
    "detalle": {
      "rol_actual": "staff_soporte",
      "roles_requeridos": ["staff_admin"]
    },
    "trace_id": "tr_01HZ98234ABCDEF12345678",
    "timestamp": "2026-10-08T20:00:00Z"
  }
}
