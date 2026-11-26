# Manual de Usuario y Documentación Técnica de la Consola de Administración (`kallicode-admin`)

- **Ticket:** `[KC-ADM-B6-11]` — Épica EAD6 (Plan E6 `KC-ADM-10-5` y `KC-ADM-12-4`)
- **Audiencia:** Personal interno de KalliCode (`staff_soporte`, `staff_operaciones`, `staff_negocio`, `staff_admin`) y equipo receptor de traspaso técnico.
- **Manual operativo / runbooks de guardia:** `docs/runbooks/admin_console_ops.md`

---

## 1. Índice de Guías de Usuario por Rol de Personal

| Rol (`STAFF_ROLES`) | Ámbito Principal | Pantallas SPA Habilitadas | Guía Dedicada |
|---|---|---|---|
| `staff_soporte` | Atención al cliente, listado y ficha 360° con solicitud temporal de revelación | `/business/customers`, `/business/customers/:tenant_id` (y alias `/customers`, `/customers/:tenant_id`) | [guia_soporte.md](guia_soporte.md) |
| `staff_operaciones` | Monitorización en vivo de fábrica, agentes, modelos LLM y reloj SLA | `/ops/agents`, `/ops/models`, `/ops/sla` | [guia_operaciones.md](guia_operaciones.md) |
| `staff_negocio` | Analítica ejecutiva, clientes, suscripciones/upgrades, FinOps tokens e informes | `/overview`, `/business/overview`, `/business/customers`, `/business/customers/:tenant_id`, `/business/subscriptions`, `/business/tokens` (alias `/subscriptions`, `/tokens`), más lectura de `/ops/models` y `/ops/sla` | [guia_negocio.md](guia_negocio.md) |
| `staff_admin` | Cobertura completa de las 7 pantallas SPA + gestión de personal, concesiones y auditoría forense vía API | Todas las pantallas SPA anteriores + operaciones API `/admin/v1/staff*`, `/admin/v1/access-grants*` y `/admin/v1/audit/staff-actions*` | [guia_admin.md](guia_admin.md) |

---

## 2. Arquitectura Técnica para Traspaso y Mantenimiento

### 2.1 Arquitectura Frontend SPA (`apps/web/`)
El frontend reside en [apps/web/package.json](../../apps/web/package.json) y sigue la jerarquía declarada en [App.tsx](../../apps/web/src/App.tsx):
`ErrorBoundary -> QueryClientProvider -> AuthProvider -> AppRouter` (envuelto por `I18nextProvider`).

- **Stack verificado:** React `18.3.1`, Vite `5.4.0`, React Router `6.28.0`, `@tanstack/react-query` `^5.59.0`, `i18next` (`es.json` / `en.json`), `Vitest` + `MSW` para pruebas locales.
- **Guardas y navegación ([AppRouter.tsx](../../apps/web/src/router/AppRouter.tsx), [Guardas.tsx](../../apps/web/src/router/Guardas.tsx), [AdminLayout.tsx](../../apps/web/src/componentes/AdminLayout.tsx)):**
  - Rutas públicas / de acceso: `/login` (`Login`), `/mfa` (`MfaVerify`), `/403` (`Error403`) y `*` (`Error404`).
  - `RutaAutenticada` exige sesión con 2FA completado; si `mfaPendiente` es verdadero redirige a `/mfa`, y en caso contrario a `/login`.
  - `RutaProtegidaPorRol` valida `usuario.role` frente a `rolesPermitidos` y renderiza `Error403` (o redirige a `/403`) cuando el rol carece de permiso.
  - Al entrar en `/`, `InicioRedireccion` envía a `staff_operaciones` a `/ops/agents` y al resto de roles a `/overview`.
- **Estilos, accesibilidad e idioma:**
  - Tokens semánticos oficiales definidos en [tokens.css](../../apps/web/src/estilos/tokens.css) (`--bg`, `--surface`, `--surface2`, `--text`, `--muted`, `--accent`, `--good`, `--warn`, `--bad`).
  - Diseño adaptable en `apps/web/src/estilos/responsive.css` (menú drawer móvil por debajo de `1025px`, cierre por tecla `Escape`, modales adaptativos y tablas con desplazamiento horizontal).
  - Cumplimiento WCAG 2.1 AA e internacionalización estricta ES/EN mediante `useTranslation()`.

### 2.2 Autenticación Obligatoria con Doble Factor (Argon2id + TOTP)
Implementada entre [auth.py](../../apps/api/src/admin_api/routers/auth.py), [security.py](../../apps/api/src/admin_api/security.py) y [auth.tsx](../../apps/web/src/estado/auth.tsx):

1. **Factor 1 — Correo corporativo y contraseña (Argon2id):**
   - El empleado envía credenciales a `POST /admin/v1/auth/login` (solo dominios permitidos en `KC_ADMIN_STAFF_EMAIL_DOMAINS`, por defecto `@kallicode.com`).
   - La contraseña se verifica mediante hash **Argon2id**. La API responde con `mfa_token` efímero, `mfa_inscrito` (`boolean`) y `expira_en`. Nunca emite el JWT de sesión en este paso.
2. **Factor 2 — TOTP obligatorio:**
   - Si `mfa_inscrito` es `false` (primera entrada tras aceptar invitación vía `POST /admin/v1/auth/invitations/accept`, o cuenta reactivada cuyo `totp_secret` se reinició a `NULL`), debe inscribir su autenticador con `POST /admin/v1/auth/mfa/enroll` (ventana acotada `mfa_totp_window = 1`, emisor `"Kallicode"`).
   - Con `mfa_inscrito = true`, `POST /admin/v1/auth/mfa/verify` valida el código TOTP (o código de recuperación de un solo uso) y emite el access token JWT (`typ="staff"`, `iss="kallicode-admin"`, `aud="admin-v1"`, `mfa=true`) junto con el refresh token.
3. **Persistencia segura e inactividad en la SPA:**
   - [auth.tsx](../../apps/web/src/estado/auth.tsx) guarda la sesión bajo la clave `kc_staff_session` (`CLAVE_SESION_STORAGE`) junto con `ultimoAcceso`.
   - Si transcurren más de **15 minutos** sin actividad (`TIEMPO_INACTIVIDAD_MS = 15 * 60 * 1000`), la sesión se elimina automáticamente, limpia la caché de TanStack Query (`limpiarQueryCache()`) y exige reautenticación.
   - El refresco silencioso usa `POST /admin/v1/auth/refresh` y el cierre explícito invoca `POST /admin/v1/auth/logout` (revocando tokens en PostgreSQL y denylist de Redis).

### 2.3 Puntos Delicados para Mantenimiento Futuro (Riesgo de Fuga Silenciosa Cross-Tenant)
En una consola multi-tenant administrativa, un error en estas tres piezas **no genera excepción ruidosa**, sino una exposición silenciosa de datos protegidos:

1. **Rol analítico de lectura `kallicode_admin_ro` (`KC_ADMIN_DATABASE_URL_RO`):**
   - Todas las consultas analíticas sobre datos de cliente usan `read_session` (`SET TRANSACTION READ ONLY`) y privilegios `GRANT SELECT` explícitos **columna a columna** definidos en `admin.access_inventory`.
   - **Prohibido** conceder `SELECT *` sobre tablas nuevas de `core.*`, unificar `KC_ADMIN_DATABASE_URL_APP` y `KC_ADMIN_DATABASE_URL_RO`, usar superusuarios o habilitar `BYPASSRLS`.
2. **Motor de enmascaramiento por defecto ([masking.py](../../apps/api/src/admin_api/masking.py)):**
   - Todo endpoint con atributos identificables devuelve razón social, correos, `tenant_id` identificable o metadatos enmascarados (`A•••• S.L.`) salvo concesión vigente validada por `alcance_suficiente()` en `admin.access_grants`.
   - Al añadir nuevas columnas o DTOs de salida en `business.py` u `ops.py`, es obligatorio pasar por las funciones de enmascarado antes de serializar la respuesta.
3. **Sellado de auditoría append-only ([audit.py](../../apps/api/src/admin_api/audit.py)):**
   - Cada consulta o revelación sobre datos de un cliente debe invocar `registrar_accion()`, escribiendo en `admin.staff_actions` (protegida por `trg_staff_actions_immutable` frente a `UPDATE` y `DELETE`) y enlazando el evento en la cadena SHA-256 central (`audit.audit_events` con `actor_tipo = 'staff'`).

---

## 3. Mecánica de Acceso Justificado y Temporal (Garantía de Compliance)

### 3.1 ¿Por qué los datos se muestran enmascarados por defecto?
La consola aplica el principio de mínimo privilegio y aislamiento multi-tenant: ningún empleado tiene acceso permanente en claro a la identidad comercial o expedientes técnicos de los clientes. Navegar por tablas ejecutivas o listados de soporte solo muestra identificadores disociados (`A•••• S.L.`, correos ocultos y listas de usuarios/integraciones bloqueadas) hasta que se justifica formalmente un caso concreto.

### 3.2 Paso a Paso para Solicitar una Concesión Temporal
Disponible desde los botones contextuales en `/business/customers`, `/business/customers/:tenant_id`, `/business/subscriptions` y `/business/tokens` mediante el componente [SolicitudConcesionModal.tsx](../../apps/web/src/componentes/SolicitudConcesionModal.tsx) (`POST /admin/v1/access-grants` en [grants.py](../../apps/api/src/admin_api/routers/grants.py)):

1. **Identificar el cliente (`tenant_id`):** pre-cargado automáticamente al abrir el modal desde una fila o ficha de cliente.
2. **Redactar el motivo obligatorio (`motivo`):** mínimo **20 caracteres** y máximo **500**. La API rechaza descripciones vacías o genéricas (como «revisión», «prueba», «soporte» o «consulta» detectadas por `_PATRONES_VACIOS`) y exige que contenga o acompañe una referencia verificable (`KC-###`, `SUP-###`, `#123`).
3. **Indicar referencia (`referencia`):** opcional si ya se incluyó el código en el motivo, pero **obligatoria** cuando el alcance solicitado es `contenido_codigo`.
4. **Seleccionar el alcance según jerarquía (`JERARQUIA` en [masking.py](../../apps/api/src/admin_api/masking.py)):**
   - `datos_negocio`: desbloquea razón social, dominio y datos contractuales/comerciales del cliente.
   - `expediente`: implica `datos_negocio` y añade usuarios de la organización, integraciones conectadas e historial de soporte/SLA.
   - `contenido_codigo`: implica ambos alcances anteriores más acceso puntual a contenido protegido; su duración máxima queda estrictamente limitada a **60 minutos** y requiere referencia de ticket verificable.
5. **Elegir duración (`duracion_min`) y respetar límites:**
   - Opciones de la SPA: `15`, `30`, `60`, `240` (por defecto) o `480` minutos.
   - Límite de **3 concesiones activas simultáneas** por empleado (`KC_ADMIN_GRANT_MAX_CONCURRENT = 3`).
   - **No existe prórroga:** cuando una concesión caduca automáticamente, se debe abrir una nueva solicitud justificando el trabajo pendiente.
6. **Efecto inmediato en la interfaz:** tras recibir HTTP `201`, la SPA invalida en TanStack Query las consultas `business-customers`, `business-customer-detail`, `business-subscriptions`, `business-upgrade-requests` y `business-usage-tokens`, revelando al instante los datos autorizados.

### 3.3 Transparencia Criptográfica hacia el Cliente
Cada lectura o revelación realizada al amparo de una concesión queda grabada con su sello SHA-256 en `admin.staff_actions` y vinculada a la cadena central de auditoría del cliente (`audit.audit_events`). El propio cliente puede auditar en cualquier momento quién accedió a sus datos, el motivo declarado y la ventana temporal desde su portal mediante `GET /api/v1/audit/staff-accesses`.

---

## 4. Catálogo de Indicadores, Origen de Datos y Frescura de las 7 Pantallas

### 4.1 Pantallas Operativas de la Consola

| # | Pantalla y Ruta SPA | Roles Autorizados | Origen del Dato | Controles Clave |
|---|---|---|---|---|
| 1 | **Resumen Ejecutivo** (`/overview`, `/business/overview`) | `staff_negocio`, `staff_admin` | Agregados SQL `admin.agg_*` (`kallicode_admin_ro`) vía `GET /admin/v1/business/overview` | Rango temporal (`mes_actual`, `mes_anterior`, `trimestre`, `ano`), comparativa (`periodo_anterior`, `mismo_periodo_ano_anterior`), 4 bloques KPI (MRR/ingresos, clientes por plan, LOC/tokens/coste, pipeline e2e p50) y badge de frescura |
| 2 | **Listado de Clientes** (`/business/customers`, `/customers`) y **Ficha 360°** (`/business/customers/:tenant_id`, `/customers/:tenant_id`) | `staff_soporte`, `staff_negocio`, `staff_admin` | BD `RO` + enmascarado condicional vía `GET /admin/v1/business/customers` y `GET /admin/v1/business/customers/{tenant_id}` | Filtros (`plan`, `estado`), búsqueda con debounce, ordenación, badge `enmascarado`, modal `SolicitudConcesionModal`, 6 bloques en ficha 360° y exportación (`ControlExportarReporte`) |
| 3 | **Suscripciones y Upgrades** (`/business/subscriptions`, `/subscriptions`) | `staff_negocio`, `staff_admin` | BD `RO` vía `GET /admin/v1/business/subscriptions` y `GET /admin/v1/business/upgrade-requests` | Radar de renovaciones (`<= 15` y `<= 30` días), estados (`activa`, `periodo_gracia`, `suspendida`, `finalizada`), cola de upgrades ordenada por antigüedad (`antiguedad_h`, flag `urgente`) y botón contextual de revelación |
| 4 | **Consumo de Tokens (FinOps)** (`/business/tokens`, `/tokens`) | `staff_negocio`, `staff_admin` | Agregados SQL vía `GET /admin/v1/business/usage/tokens` | Agrupación (`cliente`, `tier`, `dia`), segregación estricta `flash` / `pro` / `fable`, `% cuota`, cuadre con facturación y exportación asíncrona (`POST /admin/v1/business/reports`) |
| 5 | **Agentes y Colas en Vivo** (`/ops/agents`) | `staff_operaciones`, `staff_admin` | Dual: líneas `core.production_lines` en BD `RO` + telemetría E2 (`GET /admin/v1/ops/agents` y `/admin/v1/ops/queues`) | Ventanas (`5m`, `1h`, `24h`), 6 etapas canónicas (`triage`, `design`, `build`, `qa`, `security`, `deploy`), estado de colas/DLQ, alertas operativas y `ControlesLiveRefresh` |
| 6 | **Modelos LLM y Dependencias** (`/ops/models`) | `staff_operaciones`, `staff_negocio`, `staff_admin` | Telemetría E2 (`GET /admin/v1/ops/models`) + sonda `GET /admin/v1/health` | Ventanas (`1h`, `24h`, `7d`, `30d`), disponibilidad (`UMBRAL_DISPONIBILIDAD_1H = 99.0%`), latencia p50/p95, tasa de error, escalados (`flash_a_pro`, `pro_a_fable`, `a_humano`), desglose `flash`/`pro`/`fable` y salud de servicios |
| 7 | **Cumplimiento SLA** (`/ops/sla`) | `staff_operaciones`, `staff_negocio`, `staff_admin` | Agregados SQL `admin.sla_cases` y `admin.agg_sla_compliance` vía `GET /admin/v1/ops/sla` | Filtros por ciclo, plan y solo en riesgo/incumplidos, KPIs (`cumplimiento_pct`, `p95_h`, `sin_definicion`), modal explicativo `DetalleRelojSLA` (`GET /admin/v1/ops/sla/cases/{job_id}`) y exportación |

### 4.2 Badges de Frescura y Comportamiento de `ControlesLiveRefresh`
- **Badges de frescura (`frescura`):** las vistas alimentadas por agregados SQL calculan la antigüedad respecto a la última materialización (`admin_workers`). En `BizOverview`, valores `<= 6 horas` (`LIMITE_FRESCURA_MS`) muestran insignia `good` y valores `> 6 horas` muestran insignia `warn` solicitando atención operativa (véase `RB-01`).
- **Indisponibilidad de telemetría (Equipo 2):** en `/ops/agents` y `/ops/models`, cuando hay señal pero cero actividad se muestra `telemetria.disponible: true` con contadores en `0`; si falta señal en ventana se muestra `null` (nunca `0`); si el servicio E2 cae o excede antigüedad máxima, el endpoint responde `HTTP 503 TELEMETRIA_NO_DISPONIBLE`.
- **Controles de refresco en vivo ([ControlesLiveRefresh.tsx](../../apps/web/src/componentes/ControlesLiveRefresh.tsx) + [useLiveRefresh.ts](../../apps/web/src/hooks/useLiveRefresh.ts)):**
  - Selector de cadencia: `15 s` (`15_000 ms`, por defecto), `30 s`, `60 s` y `Manual` (`0 ms`).
  - **Pausa automática por visibilidad/foco:** al cambiar de pestaña (`document.hidden === true`) o perder el foco de ventana, muestra el badge amarillo de pausa en segundo plano y detiene el polling hasta recuperar la visibilidad.
  - **Presupuesto RL-4 (`60 req/min`):** cada vista computa `peticionesPorCiclo` (`2` en `OpsAgents` al consultar `/agents` y `/queues`; `1` en el resto) e impide superar las 60 consultas/minuto por empleado incluso ante pulsaciones repetidas del refresco manual.
