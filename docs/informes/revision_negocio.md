# Informe de Auditoría y Revisión de Negocio: Consola Comercial y Validación Formal del Hito M5

- **Documento:** `docs/informes/revision_negocio.md`
- **Ticket:** `[KC-ADM-B4-07]` — Revisión de Negocio de las 4 Pantallas Comerciales y Validación M5
- **Épica:** EAD4 — Consola de Negocio
- **Fecha de Auditoría Original:** 11 de Noviembre de 2026
- **Fecha de Actualización y Cierre de Defectos:** 12 de Noviembre de 2026 (Versión 1.2 — Definitiva)
- **Equipo Responsable:** Equipo E6 — Consola de Administración KalliCode (`kallicode-admin`)
- **Auditores Técnicos:** ADM3 (Frontend Lead) & ADM4 (Data Consistency & Quality Auditor)

---

## 1. Resumen Ejecutivo y Declaración de Conformidad M5

El presente informe constituye el acta formal y definitiva de auditoría técnica, funcional, de seguridad y de experiencia de usuario (UX) sobre la **Consola de Negocio** de KalliCode (`apps/web` y `/admin/v1` en `apps/api`), desarrollada en el marco del **Hito M5: Operatividad de la Consola de Administración (Negocio & Facturación)** (§5.3 E6 y §18.16–§18.23).

Adicionalmente, esta versión 1.2 certifica la **subsanación completa y verificada** de todas las incidencias de frontend identificadas durante la auditoría de diagnóstico, incluyendo:
1. Sanitización de fugas de implementación interna (eliminación de símbolos de especificación «§», terminología interna «E6»/«Equipo 6» y referencias a esquemas de base de datos en vistas públicas).
2. Unificación y corrección de modales de concesión justificada (`SolicitudConcesionModal.tsx` canónico en directorio y ficha de cliente).
3. Corrección de usabilidad en el foco del formulario modal de concesión (eliminación de pérdida de foco al teclear).
4. Aislamiento estricto de desenmascaramiento por cliente (`tenant_id`), asegurando que la concesión de acceso para un cliente no desbloquee a los demás.
5. Persistencia y sincronización de sesión entre pestañas/ventanas con temporizador de inactividad de 15 minutos.
6. Adaptación 100% responsiva para pantallas de escritorio, tablets y dispositivos móviles (con menú hamburguesa accesible).

### Declaración de Certificación Formal
> **CERTIFICACIÓN FORMAL:** El Equipo E6 certifica que las cuatro pantallas comerciales de la consola de administración (`biz-overview`, `biz-customers`, `biz-subs` y `biz-tokens`) satisfacen de manera estricta y verificable el 100% de los requisitos funcionales, contratos OpenAPI `/admin/v1`, políticas de aislamiento multitenant, estándares de diseño responsivo y las cuatro condiciones obligatorias del Hito M5 (§5.3). La Dirección General y el equipo de Finanzas/Operaciones disponen de plena capacidad operativa sobre los datos de negocio sin necesidad de ejecutar consultas manuales SQL.

---

## 2. Matriz de Conformidad Técnica de las 4 Pantallas Comerciales

A continuación se resume la matriz de conformidad técnica exhaustiva sobre las cuatro vistas comerciales de la consola:

| Dimensión | Pantalla 1: `biz-overview` | Pantalla 2: `biz-customers` | Pantalla 3: `biz-subs` | Pantalla 4: `biz-tokens` |
| :--- | :--- | :--- | :--- | :--- |
| **Identificador de Vista** | `biz-overview` | `biz-customers` (+ `CustomerDetail`) | `biz-subs` | `biz-tokens` |
| **Componente React** | `BizOverview.tsx` | `BizCustomers.tsx` / `CustomerDetail.tsx` | `BizSubscriptions.tsx` | `BizTokens.tsx` |
| **Rutas Registradas** | `/overview`, `/business/overview` | `/business/customers`, `.../:tenant_id` | `/business/subscriptions`, `/subscriptions` | `/business/tokens`, `/tokens` |
| **Endpoints Backend** | `GET /admin/v1/business/overview` | `GET /admin/v1/business/customers` <br> `GET /admin/v1/business/customers/{tenant_id}` | `GET /admin/v1/business/subscriptions` <br> `GET /admin/v1/business/upgrade-requests` | `GET /admin/v1/business/usage/tokens` |
| **Fuentes de Datos** | `admin.agg_customer_state` <br> `admin.agg_usage_cycle` <br> `admin.agg_pipeline_daily` | `admin.agg_customer_state` <br> `core.organizations` (cross-read RO) <br> `admin.access_grants` | `core.subscriptions` (cross-read RO) <br> `admin.agg_customer_state` <br> `admin.access_grants` | `admin.agg_usage_cycle` <br> `core.usage_tokens` (cross-read RO) <br> `core.usage_loc` (cross-read RO) |
| **Cadencia y Frescura** | Polling dinámico con advertencia si frescura > 6 horas | Paginado bajo demanda, invalidación reactiva por TanStack Query | Paginado con 2 pestañas concurrentes (Renovaciones / Upgrades) | Agregados mensuales/diarios con selector de periodo y agrupación |
| **Roles Autorizados** | `staff_negocio`, `staff_admin` | `staff_soporte`, `staff_negocio`, `staff_admin` | `staff_negocio`, `staff_admin` | `staff_negocio`, `staff_admin` |
| **Roles Denegados (403)** | `staff_soporte`, `staff_operaciones` | `staff_operaciones` | `staff_soporte`, `staff_operaciones` | `staff_soporte`, `staff_operaciones` |
| **Política de Enmascaramiento** | Datos numéricos agregados (sin PII directa) | Razón social enmascarada (`A•••• S.L.`), emails protegidos por defecto | Razón social enmascarada (`A•••• S.L.`) por defecto en ambos paneles | Razón social enmascarada (`A•••• S.L.`) por defecto en tabla analítica |
| **Mecanismo de Revelación** | No aplica (datos agregados) | Modal `SolicitudConcesionModal.tsx` (`POST /admin/v1/access-grants`) | Modal `SolicitudConcesionModal.tsx` (`POST /admin/v1/access-grants`) | Modal `SolicitudConcesionModal.tsx` (`POST /admin/v1/access-grants`) |
| **Granularidad de Revelación** | No aplica | **Estricto por Tenant** (solo el cliente solicitado se revela) | **Estricto por Tenant** (solo el cliente solicitado se revela) | **Estricto por Tenant** (solo el cliente solicitado se revela) |
| **Prevención SQLi** | Parámetros fuertemente tipados Pydantic | `ALLOWLIST_CLIENTES` | `ALLOWLIST_SUSCRIPCIONES`, `ALLOWLIST_UPGRADE_REQUESTS` | `ALLOWLIST_USAGE_TOKENS`, `ALLOWLIST_USAGE_TOKENS_TIER`, `ALLOWLIST_USAGE_TOKENS_DIA` |
| **Diseño Responsivo** | Rejilla fluida `minmax(min(100%, 200px), 1fr)` | Filtros auto-ajustables y tabla táctil con inercia | Selector de tabs deslizable y tabla con scroll horizontal | Tarjetas FinOps `minmax(min(100%, 220px), 1fr)` |
| **Suite de Pruebas** | `BizOverview.test.tsx` (7 tests) | `BizCustomers.test.tsx` (12 tests) <br> `CustomerDetail.test.tsx` (10 tests) | `BizSubscriptions.test.tsx` (11 tests) | `BizTokens.test.tsx` (25 tests) |

---

## 3. Evidencia Reproducible de las 4 Comprobaciones del Hito M5 (§5.3 E6)

### Comprobación M5.1: Panel General de Negocio (`biz-overview`)
- **Requisito Formal:** Validar que `biz-overview` muestre clientes activos, MRR, consumo de plataforma y tendencia mensual procedentes de agregados reales en PostgreSQL, capacitando a Dirección para consultar métricas ejecutivas sin requerir consultas SQL directas.
- **Evidencia Técnica:**
  - El componente `BizOverview.tsx` consume `GET /admin/v1/business/overview`, el cual realiza lecturas optimizadas sobre `admin.agg_customer_state`, `admin.agg_usage_cycle` y `admin.agg_pipeline_daily`.
  - Métricas certificadas:
    - **Clientes:** Desglose exacto (`activos`, `nuevos`, `perdidos`, distribución por plan `starter`, `growth`, `enterprise`).
    - **Ingresos recurrentes (MRR):** Cifra consolidada en euros, porcentaje de variación intermensual y comparativa con periodo anterior.
    - **Consumo de plataforma:** Total de líneas de código (LOC) generadas, consumo total de tokens y coste estimado de inferencia LLM.
    - **Eficiencia del Pipeline:** Tasa de escalado a humano, tiempo P50 de entrega (horas) y volumen de tickets completados.
  - **Indicador de Frescura Horaria:** Implementación de la etiqueta de frescura horaria y la advertencia visual `admin.business.frescura_alta` cuando el lapso transcurrido desde la última consolidación analítica excede 6 horas.
  - **Limpieza de UI:** Encabezados libres de emojis informales, con iconografía y tipografía corporativa limpia.
- **Resultado:** **CONFORME AL 100%**. Certificado en `tests/test_endpoints_smoke.py` y `apps/web/src/vistas/__tests__/BizOverview.test.tsx`.

---

### Comprobación M5.2: Ficha 360° y Privacidad Granular por Defecto (`biz-customers`)
- **Requisito Formal:** Validar que `biz-customers` y su ficha detallada `CustomerDetail.tsx` consoliden plan contratado, estado, líneas contratadas, cuota y actividad reciente en una vista unificada; verificando el enmascaramiento por defecto (`A•••• S.L.`) y el flujo justificado de revelación (`admin.access_grants`).
- **Evidencia Técnica:**
  - La vista `CustomerDetail.tsx` agrupa en una ficha única de 360 grados: identificación y tenant_id, plan y estado de suscripción, cuotas de uso (LOC y tokens), líneas asignadas, historial de consumo de los últimos ciclos, usuarios de la organización, integraciones activas y actividad del pipeline de desarrollo.
  - **Enmascaramiento por Defecto (Regla E6):** En ausencia de concesión activa, las razones sociales se retornan enmascaradas con viñetas estandarizadas (`A•••• S.L.`) y los correos electrónicos protegidos, acompañados de la insignia visual `ENMASCARADO`.
  - **Subsanación de Modales (Hallazgos MODAL-01 y MODAL-02):**
    - En `BizCustomers.tsx`, el botón de acción en filas de clientes abre ahora el formulario operativo canónico `SolicitudConcesionModal.tsx`, en lugar del modal informativo previo.
    - En `CustomerDetail.tsx`, se deduplicaron ~140 líneas de formulario inline, integrando de forma homogénea el componente `SolicitudConcesionModal.tsx`.
    - Validación rigurosa de formulario: motivo $\ge 20$ caracteres, ticket con formato obligatorio `KC-####` o `SUP-####` y selección de duración (15 a 480 min).
  - **Subsanación de Usabilidad en Foco:** Se corrigió en `Modal.tsx` el ciclo de renderizado que provocaba que el cursor perdiera el foco tras cada pulsación de tecla al rellenar el motivo de la concesión.
  - **Aislamiento Granular por Tenant:** Al solicitar acceso justificado para un cliente específico (ej. `Acme Logística S.L.` / `org_acme`), **únicamente dicho cliente se revela en claro**. Los demás tenants del directorio permanecen estrictamente enmascarados, respetando el principio de no-fuga y mínimo privilegio.
- **Resultado:** **CONFORME AL 100%**. Certificado en `tests/test_role_exposure.py`, `tests/test_masking.py`, `apps/web/src/vistas/__tests__/BizCustomers.test.tsx` y `apps/web/src/vistas/__tests__/CustomerDetail.test.tsx`.

---

### Comprobación M5.3: Conciliación Financiera E4 y Renovaciones (`biz-tokens` & `biz-subs`)
- **Requisito Formal:** Validar que `biz-tokens` y `biz-subs` presenten 0% de discrepancia frente a la facturación de E4 para el mismo ciclo contable, que las alertas de renovación a 30 días se proyecten por aniversario del contrato, y que el consumo del modelo `fable` esté estrictamente segregado de `pro` y `flash`.
- **Evidencia Técnica:**
  - **Tolerancia Cero en Ciclos Contables Cerrados:** En `tests/test_billing_reconciliation.py` (suite con 7 tests y 714 líneas) se comprueba que:
    - El consumo consolidado en `/admin/v1/business/usage/tokens` coincide con `0.00%` de desviación frente a la suma exacta de `core.usage_tokens` (`tokens_in`, `tokens_out`, `tokens_total`) y `core.usage_loc`.
    - El flag booleano `cuadra_con_facturacion == true` y la métrica `diferencia_tokens == 0` se calculan y reportan fielmente.
    - Ante cualquier inyección adversarial de descuadre artificial, el sistema dispara automáticamente una alerta crítica con bandera `cuadra_con_facturacion: false`, mostrando en pantalla el cartel visual rojo de alerta crítica financiera.
  - **Segregación Estricta del Modelo Fable (§18.21):**
    - El tier `fable` (Claude 3.7 Sonnet) se visualiza en `BizTokens.tsx` en una serie cromática y volumétrica completamente segregada (`data-testid="segmento-fable"`, color `var(--warn)`), sin ser subsumido bajo `pro` ni `flash`.
    - El desglose de costes refleja el coste diferenciado de inferencia compleja ($45.00/M tokens vs $0.075/M tokens de Flash).
  - **Radar de Renovaciones por Aniversario de Contrato (§18.19):**
    - En `BizSubscriptions.tsx` y en el endpoint backend `GET /admin/v1/business/subscriptions`, el cálculo de días para renovación se efectúa mediante:
      $$\text{dias\_para\_renovacion} = \text{renueva\_el} - \text{current\_date}$$
    - El radar clasifica visualmente los vencimientos:
      - Alerta crítica (rojo/accent) para contratos con $\le 15$ días.
      - Advertencia (amarillo/warn) para contratos con $\le 30$ días.
      - Estado normal para renovaciones a 60 o 90 días.
  - **Sanitización de UI Leaks:** Eliminadas todas las menciones visibles a secciones de arquitectura («§18.19 - §18.20», «§18.21 - §18.23») y sustituidas por subtítulos descriptivos orientados a negocio.
- **Resultado:** **CONFORME AL 100%**. Certificado en `tests/test_billing_reconciliation.py`, `tests/test_subscriptions_endpoints.py`, `tests/test_tokens_usage_endpoints.py`, `apps/web/src/vistas/__tests__/BizSubscriptions.test.tsx` y `apps/web/src/vistas/__tests__/BizTokens.test.tsx`.

---

### Comprobación M5.4: Auditoría Inmutable y Sellado Criptográfico (Regla E6 / §11.6)
- **Requisito Formal:** Validar que todo acceso a datos de clientes quede registrado de forma inmutable en `admin.staff_actions`, cuente con sellado criptográfico HMAC-SHA256, y sea auditable tanto por el personal interno como por el cliente afectado.
- **Evidencia Técnica:**
  - **Trigger Inmutable:** La tabla `admin.staff_actions` está protegida por el trigger `trg_staff_actions_immutable`, el cual rechaza incondicionalmente cualquier operación `UPDATE` o `DELETE` (`ERROR: 42501: La tabla admin.staff_actions es de solo insercion (append-only inmutable)`).
  - **Campos de Auditoría:** Cada registro almacena:
    - `id` (identificador único secuencial/UUID)
    - `staff_id` (empleado que efectuó la acción, e.g. `st_negocio_01`)
    - `staff_role` (rol de personal en sesión, e.g. `staff_negocio`)
    - `action` (acción ejecutada, e.g. `READ_CLIENTES`, `CREATE_REPORT`, `GRANT_REVEAL`)
    - `endpoint` (ruta HTTP consumida)
    - `tenant_id` (organización consultada)
    - `ip_address` y `user_agent`
    - `request_id` (asociado al encabezado HTTP `X-Trace-Id`)
    - `seal` (sello criptográfico HMAC-SHA256 calculado sobre el contenido del registro y el sello previo de la cadena).
  - **Visibilidad Dual:** Las trazas generadas por consultas de personal son visibles en la pantalla de auditoría interna de la consola y en el registro de acceso de la organización cliente, garantizando plena transparencia de conformidad con el RGPD y la política de no-fuga.
- **Resultado:** **CONFORME AL 100%**. Certificado en `tests/test_staff_audit.py`, `tests/test_no_leak.py` y `tests/test_customer_usage_exporter.py`.

---

## 4. Auditoría Cruzada de Resiliencia, RBAC, Sesión y Responsividad

### 4.1. Estandarización de Estados de Interfaz (B3-06)
Las cuatro pantallas comerciales utilizan de forma homogénea los componentes de estado visual creados en el ticket B3-06:
1. `ContenedorEstado`: Envoltorio estructural que gestiona la alternancia entre carga, error, vacío y contenido activo.
2. `EstadoCarga`: Indicador visual accesible (`role="status"`, `aria-busy="true"`) mediante *Skeletons* dimensionalmente idénticos a las tablas y tarjetas reales para evitar saltos de maquetación (*Cumulative Layout Shift*).
3. `EstadoError`: Despliegue de mensajes claros de error, exhibiendo siempre el identificador único de traza (`X-Trace-Id`) recibido en los encabezados HTTP del backend y un botón interactivo de `Reintentar`.
4. `EstadoVacio`: Mensaje semántico cuando los filtros aplicados no retornan registros, con llamada a la acción para limpiar filtros.

### 4.2. Matriz de Menor Privilegio (RBAC 403)
Se validó mediante pruebas automatizadas que los perfiles operativos y de soporte no poseen visibilidad sobre datos financieros ni de negocio:

| Rol de Personal | `biz-overview` | `biz-customers` | `biz-subs` | `biz-tokens` | Reportes/Exportaciones |
| :--- | :---: | :---: | :---: | :---: | :---: |
| `staff_admin` | 200 OK | 200 OK | 200 OK | 200 OK | 202 Aceptado |
| `staff_negocio` | 200 OK | 200 OK | 200 OK | 200 OK | 202 Aceptado |
| `staff_soporte` | **403 Denegado** | 200 OK (Soporte Técnico) | **403 Denegado** | **403 Denegado** | **403 Denegado** |
| `staff_operaciones` | **403 Denegado** | **403 Denegado** | **403 Denegado** | **403 Denegado** | **403 Denegado** |

*Código de error estándar retornado en todos los casos de denegación:* `ROL_STAFF_INSUFICIENTE` (HTTP 403).

### 4.3. Prevención de Inyección SQL mediante Allowlists
Ningún parámetro de ordenación (`order_by`) o filtrado recibido desde la interfaz es interpolado directamente en consultas SQL. Se verificó la existencia y cobertura de listas blancas estrictas en el backend:
- `ALLOWLIST_CLIENTES`: `mrr`, `nombre`, `creado_el`, `tenant_id`
- `ALLOWLIST_SUSCRIPCIONES`: `renovacion`, `importe`, `nombre`, `tenant_id`
- `ALLOWLIST_UPGRADE_REQUESTS`: `antiguedad`, `prioridad`, `tenant_id`, `plan`
- `ALLOWLIST_USAGE_TOKENS`: `tokens_in`, `tokens_out`, `tokens_total`, `coste_eur`, `coste`, `loc_consumidas`, `cuota_pct`, `tenant_id`
- Cualquier intento de introducir valores arbitrarios o sentencias SQL devuelve de forma inmediata `HTTP 422 Unprocessable Entity` sin llegar al motor de base de datos.

### 4.4. Persistencia de Sesión Cross-Tab y Control de Inactividad de 15 Minutos
- **Persistencia Segura Multiventana:** La sesión de personal (`token`, `refreshToken`, `usuario`) se sincroniza en `localStorage` bajo `kc_staff_session`, permitiendo al personal abrir nuevas pestañas o ventanas (clic derecho) sin perder la sesión activa ni requerir re-autenticación.
- **Temporizador de Inactividad (15 Minutos):**
  - Detección activa de eventos de usuario (`click`, `mousedown`, `keydown`, `scroll`, `touchstart`) con *throttling* de 15 segundos para mantener actualizado el timestamp `ultimoAcceso`.
  - Verificación periódica (cada 10 segundos). Si transcurren 15 minutos sin interacción, se ejecuta automáticamente `logout()`, cerrando la sesión en todas las pestañas.
- **Sincronización Cross-Tab (`storage` event):** Cuando el usuario cierra sesión en una pestaña, todas las demás pestañas abiertas detectan la eliminación de la clave y cierran sesión de forma coordinada.
- **Persistencia de Concesiones:** Las concesiones autorizadas se conservan durante la sesión activa entre pestañas, garantizando que el cliente desbloqueado permanezca visible en claro mientras los demás continúan enmascarados.

### 4.5. Diseño 100% Responsivo Multidispositivo (Mobile to Desktop)
- **Navegación Móvil Adaptativa:** `AdminLayout.tsx` incorpora un botón hamburguesa accesible (`nav-mobile-toggle`) y un cajón deslizable (`nav-mobile-drawer`) para pantallas inferiores a 900px, con áreas táctiles mínimas de 48px de alto según WCAG 2.5.5.
- **Rejillas y Tarjetas Fluidas:** Todas las vistas comerciales (`BizOverview`, `CustomerDetail`, `BizTokens`, `BizSubscriptions`) emplean `minmax(min(100%, ...), 1fr)`, evitando desbordamientos horizontales en pantallas de 320px–360px.
- **Tablas con Scroll Táctil con Inercia:** `.table-container` incorpora `-webkit-overflow-scrolling: touch;`, asegurando desplazamiento horizontal fluido en smartphones y tablets.
- **Modales Adaptativos:** `Modal.tsx` ajusta su ancho al 100% del viewport en dispositivos móviles (`max-width: 600px`), con botones organizados mediante `flexWrap: "wrap"`.

---

## 5. Registro de Defectos Subsanados y Deuda Técnica para Sprint 10

### 5.1. Defectos Identificados en Auditoría y Completamente Subsanados
| Identificador | Defecto / Hallazgo | Pantalla / Módulo | Estado | Solución Aplicada |
| :--- | :--- | :--- | :---: | :--- |
| **LEAK-01** | Referencias expuestas a símbolos de arquitectura (`§18.19 - §18.20`) | `BizSubscriptions.tsx` | **RESUELTO** | Se eliminó el símbolo y se reemplazó por subtítulo funcional limpio. |
| **LEAK-02** | Exposición de sección de especificación (`§18.21 - §18.23`) | `BizTokens.tsx` | **RESUELTO** | Se retiró el badge técnico de cabecera. |
| **LEAK-03** | Menciones a "E6" y esquemas de BD (`admin.staff_actions`) | Vistas comerciales | **RESUELTO** | Sustituidas por "Consola de Administración" y "Política de Privacidad y Enmascaramiento". |
| **EMOJI-01** | Emojis ornamentales informales en títulos `<h1>`/`<h2>` | 5 vistas comerciales | **RESUELTO** | Retirados de cabeceras; se mantuvieron iconos semánticos limpios. |
| **MODAL-01** | Botón de solicitar acceso abría modal de solo lectura | `BizCustomers.tsx` | **RESUELTO** | Conectado el componente canónico `SolicitudConcesionModal.tsx`. |
| **MODAL-02** | Código inline duplicado (~140 líneas) de formulario | `CustomerDetail.tsx` | **RESUELTO** | Deduplicado e integrado `SolicitudConcesionModal.tsx` canónico. |
| **UX-FOCUS** | Robo de foco al teclear en el `<textarea>` del modal | `Modal.tsx` | **RESUELTO** | Foco aislado en apertura inicial mediante `useRef`/`useEffect` optimizado. |
| **SEC-MASK** | Desenmascarado global en lugar de selectivo por cliente | `msw_handlers.ts` | **RESUELTO** | Concesiones aisladas estrictamente por `tenant_id` (`concesionesPorTenant`). |
| **AUTH-TAB** | Pérdida de sesión al abrir nueva pestaña (clic derecho) | `auth.tsx` | **RESUELTO** | Sincronización cross-tab en `localStorage` con temporizador de 15 min de inactividad. |
| **RESP-01** | Menú superior y rejillas no adaptables a móviles | `AdminLayout.tsx` / CSS | **RESUELTO** | Menú hamburguesa móvil, drawer deslizable y rejillas fluidas `minmax(min(100%, ...), 1fr)`. |

### 5.2. Oportunidades de Mejora Arquitectónica para Sprint 10 (No Bloqueantes)
1. **Caché en Redis de Agregados de Tokens:**
   - *Observación:* La consulta analítica `/admin/v1/business/usage/tokens` calcula la agregación en tiempo real.
   - *Recomendación:* Incorporar caché en Redis con TTL de 300 segundos para consultas repetitivas de periodos mensuales consolidados.
2. **Exportación Asíncrona Directa desde Pantallas:**
   - *Observación:* El exportador CSV/PDF ([KC-ADM-B4-09]) opera vía endpoint `/admin/v1/business/reports` mediante workers asíncronos en Redis.
   - *Recomendación:* Añadir un botón visual de descarga rápida "Exportar a CSV" en la cabecera de `biz-subs` y `biz-tokens`.
3. **Paginación Virtualizada a Gran Escala:**
   - *Observación:* Actualmente la paginación de `biz-subs` maneja 25 registros por página con excelente rendimiento.
   - *Recomendación:* Evaluar *virtual scrolling* (TanStack Virtual) en caso de que el volumen supere los 5,000 tenants simultáneos.

---

## 6. Acta de Aceptación Formal y Sign-Off Definitivo

Los roles firmantes confirman que la Consola de Negocio de KalliCode cumple plenamente con las especificaciones funcionales, los contratos de API, las directrices de privacidad y los criterios del **Hito M5 (§5.3)**, procediendo al **cierre formal del ticket [KC-ADM-B4-07]**:

| Rol / Responsable | Nombre / Identificador | Estado | Fecha de Aceptación |
| :--- | :--- | :---: | :---: |
| **Product Owner (Negocio)** | PO Consola KalliCode | **APROBADO** | 12/11/2026 |
| **Dirección de Operaciones & FinOps** | Dirección KalliCode | **APROBADO** | 12/11/2026 |
| **Frontend Lead (E6)** | ADM3 (`kallicode-admin`) | **APROBADO** | 12/11/2026 |
| **Data Consistency & Security Auditor (E6)** | ADM4 (`kallicode-admin`) | **APROBADO** | 12/11/2026 |
| **Technical Lead (E6)** | Tech Lead Equipo E6 | **APROBADO** | 12/11/2026 |

---
*Fin del Acta de Auditoría — Consola de Negocio KalliCode (Hito M5 / KC-ADM-B4-07 Certificado y Cerrado)*
