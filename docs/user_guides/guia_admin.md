# Guía de Usuario: Administración de Consola (`staff_admin`)

- **Manual Maestro:** [admin_manual.md](file:///home/aagonzalezv/CAPSTONE/kallicode-admin/docs/user_guides/admin_manual.md)
- **Manual Operativo y Runbooks:** [admin_console_ops.md](file:///home/aagonzalezv/CAPSTONE/kallicode-admin/docs/runbooks/admin_console_ops.md)
- **Propósito del rol:** Supervisión global sobre las 7 pantallas operativas de negocio y operaciones, más administración exclusiva del ciclo de vida del personal interno, revocación de concesiones ajenas y auditoría forense cross-tenant.

---

## 1. Cobertura en la Interfaz SPA

En [AppRouter.tsx](file:///home/aagonzalezv/CAPSTONE/kallicode-admin/apps/web/src/router/AppRouter.tsx) y [AdminLayout.tsx](file:///home/aagonzalezv/CAPSTONE/kallicode-admin/apps/web/src/componentes/AdminLayout.tsx), el rol `staff_admin` hereda acceso de lectura y navegación sobre las **7 pantallas operativas** (más la ficha 360°):
- **Negocio (`/overview` por defecto al entrar):** `/overview`, `/business/overview`, `/business/customers`, `/business/customers/:tenant_id`, `/business/subscriptions`, `/business/tokens` (y alias `/customers`, `/customers/:tenant_id`, `/subscriptions`, `/tokens`).
- **Operaciones:** `/ops/agents`, `/ops/models`, `/ops/sla`.

Para el detalle funcional de cada pantalla consulta las guías correspondientes: [guia_soporte.md](file:///home/aagonzalezv/CAPSTONE/kallicode-admin/docs/user_guides/guia_soporte.md), [guia_operaciones.md](file:///home/aagonzalezv/CAPSTONE/kallicode-admin/docs/user_guides/guia_operaciones.md) y [guia_negocio.md](file:///home/aagonzalezv/CAPSTONE/kallicode-admin/docs/user_guides/guia_negocio.md).

> **Transparencia de arquitectura actual:** `staff_admin` tampoco posee acceso en claro permanente a datos de cliente. Si necesitas desenmascarar una ficha o listado en la SPA, debes solicitar una concesión temporal en `SolicitudConcesionModal` (`POST /admin/v1/access-grants`) exactamente igual que el resto del personal.

---

## 2. Operaciones Exclusivas de `staff_admin` vía API REST (`/admin/v1`)

En la versión actual de la SPA ([AppRouter.tsx](file:///home/aagonzalezv/CAPSTONE/kallicode-admin/apps/web/src/router/AppRouter.tsx)), las funciones de administración de personal, control global de concesiones y auditoría de acciones (`audit-actions`) se operan directamente contra los endpoints autenticados y protegidos por RBAC (`staff_admin`) del backend FastAPI ([staff.py](file:///home/aagonzalezv/CAPSTONE/kallicode-admin/apps/api/src/admin_api/routers/staff.py), [grants.py](file:///home/aagonzalezv/CAPSTONE/kallicode-admin/apps/api/src/admin_api/routers/grants.py) y [admin_audit.py](file:///home/aagonzalezv/CAPSTONE/kallicode-admin/apps/api/src/admin_api/routers/admin_audit.py)):

### 2.1 Gestión del Ciclo de Vida del Personal (`/admin/v1/staff*`)
1. **Invitar nuevo miembro de personal (`POST /admin/v1/staff/invitations`):**
   - No existe registro público ni autoservicio.
   - Solo admite correos corporativos válidos según `KC_ADMIN_STAFF_EMAIL_DOMAINS` (`@kallicode.com`) y un rol de `STAFF_ROLES` (`staff_soporte`, `staff_operaciones`, `staff_negocio`, `staff_admin`).
   - El invitado activa su cuenta en `POST /admin/v1/auth/invitations/accept` e inscribe obligatoriamente TOTP antes de operar.
2. **Auditar inventario de cuentas internas (`GET /admin/v1/staff`):**
   - Devuelve rol, estado, si tiene MFA inscrito (`mfa_inscrito`), fecha de último acceso y contador de concesiones activas para detectar cuentas dormidas o acumulación excesiva de permisos.
3. **Cambiar rol o desactivar cuenta (`PATCH /admin/v1/staff/{staff_id}`):**
   - Exige `motivo` (`>= 10` caracteres) y protege invariantes de seguridad: no permite auto-degradarse ni dejar al sistema sin ningún `staff_admin` activo (`409 CONFLICTO_ESTADO`).
   - Al cambiar el `rol`, revoca automáticamente los refresh tokens vigentes (`revoked_reason = 'cambio_de_rol'`).
   - Al establecer `estado: "deactivated"`, deshabilita acceso inmediato (`STAFF_DESACTIVADO`), invalida sesiones y **revoca de inmediato todas sus concesiones activas** en `admin.access_grants`.

### 2.2 Supervisión y Revocación de Concesiones Ajenas (`/admin/v1/access-grants*`)
1. **Consultar concesiones globales (`GET /admin/v1/access-grants?ambito=todas`):**
   - Solo `staff_admin` puede usar `ambito=todas` para inspeccionar las concesiones vigentes o históricas de todo el personal (otros roles quedan restringidos a `ambito=propias`).
2. **Revocar una concesión de terceros (`DELETE /admin/v1/access-grants/{grant_id}`):**
   - Cualquier empleado puede cerrar sus propias concesiones; únicamente `staff_admin` puede revocar concesiones de otro empleado especificando un motivo (`>= 10` caracteres), dejando traza `grant_revoked` en `admin.staff_actions`.

### 2.3 Auditoría Forense de Acciones del Personal (`/admin/v1/audit/staff-actions*`)
1. **Inspeccionar lecturas y revelaciones (`GET /admin/v1/audit/staff-actions`):**
   - Permite filtrar por `staff_id`, `tenant_id`, ventana temporal (`desde`, `hasta`, máx. `365` días) y acción (`grant_created`, `grant_revoked`, `read`, `reveal`, `report`, `staff_managed`, `admin_query`).
   - Devuelve el motivo íntegro, `lecturas` por concesión y la bandera criptográfica **`verificado`** (si aparece en `false`, activar inmediatamente el runbook **RB-03**).
2. **Exportar evidencias forenses (`POST /admin/v1/audit/staff-actions/exports`):**
   - Genera un fichero `csv` en segundo plano con todos los eventos, sellos y estado de verificación para auditorías internas o respuestas ante incidentes.
   - Para procedimientos completos de contención, revocación masiva en Redis y verificación SQL de cadenas SHA-256, sigue **RB-02** y **RB-03** en [admin_console_ops.md](file:///home/aagonzalezv/CAPSTONE/kallicode-admin/docs/runbooks/admin_console_ops.md).
