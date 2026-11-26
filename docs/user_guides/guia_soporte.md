# Guía de Usuario: Soporte (`staff_soporte`)

- **Manual Maestro:** [admin_manual.md](admin_manual.md)
- **Propósito del rol:** Atención al cliente, diagnóstico de incidencias sobre cuentas concretas y gestión de revelaciones justificadas y temporales bajo cumplimiento RGPD.

---

## 1. Pantallas Autorizadas y Navegación

Al iniciar sesión e introducir el código **TOTP** en `/mfa`, el sistema te autentica con el rol `staff_soporte` y habilita en la barra de navegación superior ([AdminLayout.tsx](../../apps/web/src/componentes/AdminLayout.tsx)) el acceso exclusivo al módulo de clientes:

| Vista | Ruta SPA | Alias Soportado | Permiso |
|---|---|---|---|
| Listado paginado de clientes | `/business/customers` | `/customers` | Permitido |
| Ficha detallada 360° de cliente | `/business/customers/:tenant_id` | `/customers/:tenant_id` | Permitido |
| Resto de pantallas (`/overview`, `/business/subscriptions`, `/business/tokens`, `/ops/agents`, `/ops/models`, `/ops/sla`) | — | — | Bloqueado (`403` / vista `Error403`) |

> **Nota sobre redirección inicial:** al navegar a `/` con sesión `staff_soporte`, si accedes directamente a `/business/customers` entrarás al directorio completo de clientes; intentar abrir rutas de negocio global o `/ops/*` mostrará la pantalla `/403` (`Error403`).

---

## 2. Flujo Operativo Paso a Paso

### Paso 1 — Localizar al Cliente en `/business/customers`
Consulta el endpoint `GET /admin/v1/business/customers` desde la tabla de clientes ([BizCustomers.tsx](../../apps/web/src/vistas/BizCustomers.tsx)):
1. **Filtrar y buscar:** usa los selectores de **Plan** (`starter`, `growth`, `enterprise`), **Estado** (`activa`, `periodo_gracia`, `suspendida`, `finalizada`) y la caja de búsqueda por texto (`q`) con sincronización en URL.
2. **Interpretar los datos enmascarados por defecto:** verás la columna `razon_social` protegida (por ejemplo `A•••• S.L.`) junto al badge `enmascarado`. Esto confirma que aún no hay una concesión activa para ese `tenant_id`.
3. **Abrir la ficha 360°:** haz clic en la fila o enlace del cliente para navegar a `/business/customers/:tenant_id`.

### Paso 2 — Analizar la Ficha 360° (`CustomerDetail`)
La ficha ([CustomerDetail.tsx](../../apps/web/src/vistas/CustomerDetail.tsx)) consulta `GET /admin/v1/business/customers/{tenant_id}` y presenta 6 bloques ejecutivos:
1. **Identificación y Suscripción:** `tenant_id`, razón social, dominio, fecha de alta, plan contratado, estado, fecha de renovación y solicitudes pendientes.
2. **Líneas de Producción:** contratadas vs activas y utilización media del ciclo.
3. **Consumo del Ciclo e Histórico:** LOC, tokens, porcentaje de cuota consumida y tendencia de los últimos 6 ciclos.
4. **Usuarios de la Organización:** listado de cuentas del cliente (enmascaradas/bloqueadas mientras no exista concesión con alcance suficiente).
5. **Integraciones Conectadas:** repositorios, Jira, CI/CD y bases de datos (protegidas por defecto sin concesión).
6. **Actividad de Pipeline y Grafo CodeMapping:** cobertura, nodos, aristas y tiempo medio end-to-end.

### Paso 3 — Solicitar Concesión Temporal y Justificada (`POST /admin/v1/access-grants`)
Si el caso de soporte requiere ver la razón social real, usuarios o integraciones conectadas:
1. Pulsa el botón contextual de **Solicitar acceso / Revelar datos** para abrir [SolicitudConcesionModal.tsx](../../apps/web/src/componentes/SolicitudConcesionModal.tsx).
2. Completa el formulario respetando las validaciones de cumplimiento:
   - **Motivo (`motivo`):** escribe una explicación concreta de al menos **20 caracteres** (hasta `500`), evitando palabras genéricas («revisión», «prueba», «soporte»).
   - **Referencia de ticket (`referencia`):** introduce el código verificable de incidencia (por ejemplo `SUP-1042` o `KC-812`) o inclúyelo dentro del motivo.
   - **Alcance (`alcance`):** elige el mínimo necesario según `JERARQUIA`:
     - `datos_negocio`: datos identificativos y contractuales básicos.
     - `expediente`: añade usuarios de la organización, integraciones conectadas e historial de soporte/SLA.
     - `contenido_codigo`: alcance superior restringido a un máximo de **60 minutos** con referencia obligatoria.
   - **Duración (`duracion_min`):** selecciona `15`, `30`, `60`, `240` (por defecto) o `480` minutos (`<= 60` para `contenido_codigo`).
3. Confirma la solicitud. Tras el código `201`, la SPA invalida la caché de TanStack Query y revela los bloques habilitados dentro de `/business/customers/:tenant_id`.

### Paso 4 — Buenas Prácticas y Cierre
- Recuerda que tienes un máximo de **3 concesiones activas simultáneas** (`KC_ADMIN_GRANT_MAX_CONCURRENT = 3`).
- Si necesitas consultar tus concesiones vigentes puedes revisar tu perfil (`GET /admin/v1/staff/me`) o cerrar manualmente una concesión propia que ya no utilices (`DELETE /admin/v1/access-grants/{grant_id}`).
- Cada revelación ejecutada queda auditada con hash inmutable en `admin.staff_actions` y visible para el cliente en su portal mediante `GET /api/v1/audit/staff-accesses`.
