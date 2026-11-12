# Informe de Auditoría y Revisión de Negocio: Consola Comercial y Validación Formal del Hito M5

- **Documento:** `docs/informes/revision_negocio.md`
- **Ticket:** `[KC-ADM-B4-07]` — Revisión de Negocio de las 4 Pantallas Comerciales y Validación M5
- **Épica:** EAD4 — Consola de Negocio
- **Fecha de Auditoría:** 11 de Noviembre de 2026
- **Equipo Responsable:** Equipo E6 — Consola de Administración KalliCode (`kallicode-admin`)
- **Auditores Técnicos:** ADM3 (Frontend Lead) & ADM4 (Data Consistency & Quality Auditor)

---

## 1. Resumen Ejecutivo y Declaración de Conformidad M5

El presente informe constituye el acta formal de auditoría técnica, funcional y de seguridad de la **Consola de Negocio** de KalliCode (`apps/web` y `/admin/v1` en `apps/api`), desarrollada en el marco del **Hito M5: Operatividad de la Consola de Administración (Negocio & Facturación)** (§5.3 E6 y §18.16–§18.23).

### Declaración de Certificación Formal
> **CERTIFICACIÓN FORMAL:** El Equipo E6 certifica que las cuatro pantallas comerciales de la consola de administración (`biz-overview`, `biz-customers`, `biz-subs` y `biz-tokens`) satisfacen de manera estricta y verificable el 100% de los requisitos funcionales, contratos OpenAPI `/admin/v1`, políticas de aislamiento multitenant y las cuatro condiciones obligatorias del Hito M5 (§5.3). La Dirección General y el equipo de Finanzas/Operaciones disponen de plena capacidad operativa sobre los datos de negocio sin necesidad de ejecutar consultas manuales SQL.

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
| **Cadencia y Frescura** | Polling dinámico con advertencia si frescura > 6 horas | Paginado bajo demanda, invalidación reactiva por React Query | Paginado con 2 pestañas concurrentes (Renovaciones / Upgrades) | Agregados mensuales/diarios con selector de periodo y agrupación |
| **Roles Autorizados** | `staff_negocio`, `staff_admin` | `staff_soporte`, `staff_negocio`, `staff_admin` | `staff_negocio`, `staff_admin` | `staff_negocio`, `staff_admin` |
| **Roles Denegados (403)** | `staff_soporte`, `staff_operaciones` | `staff_operaciones` | `staff_soporte`, `staff_operaciones` | `staff_soporte`, `staff_operaciones` |
| **Política de Enmascaramiento** | Datos numéricos agregados (sin PII directa) | Razón social enmascarada (`A•••• S.L.`), emails protegidos por defecto | Razón social enmascarada (`A•••• S.L.`) por defecto en ambos paneles | Razón social enmascarada (`A•••• S.L.`) por defecto en tabla analítica |
| **Mecanismo de Revelación** | No aplica (datos agregados) | Modal `SolicitudConcesionModal.tsx` (`POST /admin/v1/access-grants`) | Modal `SolicitudConcesionModal.tsx` (`POST /admin/v1/access-grants`) | Modal `SolicitudConcesionModal.tsx` (`POST /admin/v1/access-grants`) |
| **Prevención SQLi** | Parámetros fuertemente tipados Pydantic | `ALLOWLIST_CLIENTES` | `ALLOWLIST_SUSCRIPCIONES`, `ALLOWLIST_UPGRADE_REQUESTS` | `ALLOWLIST_USAGE_TOKENS`, `ALLOWLIST_USAGE_TOKENS_TIER`, `ALLOWLIST_USAGE_TOKENS_DIA` |
| **Suite de Pruebas** | `BizOverview.test.tsx` (7 tests) | `BizCustomers.test.tsx` (11 tests) <br> `CustomerDetail.test.tsx` (10 tests) | `BizSubscriptions.test.tsx` (11 tests) | `BizTokens.test.tsx` (25 tests) |

---

## 3. Evidencia Reproducible de las 4 Comprobaciones del Hito M5 (§5.3 E6)

### Comprobación M5.1: Panel General de Negocio (`biz-overview`)
- **Requisito Formal:** Validar que `biz-overview` muestre clientes activos, MRR, consumo de plataforma y tendencia mensual procedentes de agregados reales en PostgreSQL, capacitando a Dirección para consultar métricas ejecutivas sin requerir consultas SQL directas.
- **Evidencia Técnica:**
  - El componente `BizOverview.tsx` consume `GET /admin/v1/business/overview`, el cual realiza lecturas optimizadas sobre `admin.agg_customer_state`, `admin.agg_usage_cycle` y `admin.agg_pipeline_daily`.
  - Métricas certificadas:
    - **Clientes:** Desglose exacto (`activos`, `nuevos`, `perdidos`, distribución por plan `starter`, `growth`, `enterprise`).
    - **Ingresos recurrentes (MRR):** Cifra consolidada en euros, porcentaje de variación intermensual y tendencia gráfica.
    - **Consumo de plataforma:** Total de líneas de código (LOC) generadas, consumo total de tokens y coste estimado de inferencia LLM.
    - **Eficiencia del Pipeline:** Tasa de escalado a humano, tiempo P50 de entrega (horas) y volumen de tickets completados.
  - **Indicador de Frescura Horaria:** Implementación de la etiqueta de frescura horaria y la advertencia visual `admin.business.frescura_alta` cuando el lapso transcurrido desde la última consolidación analítica excede 6 horas.
- **Resultado:** **CONFORME AL 100%**. Certificado en `tests/test_endpoints_smoke.py` y `apps/web/src/vistas/__tests__/BizOverview.test.tsx`.

---

### Comprobación M5.2: Ficha 360° y Privacidad por Defecto (`biz-customers`)
- **Requisito Formal:** Validar que `biz-customers` y su ficha detallada `CustomerDetail.tsx` consoliden plan contratado, estado, líneas contratadas, cuota y actividad reciente en una vista unificada; verificando el enmascaramiento por defecto (`A•••• S.L.`) y el flujo justificado de revelación (`admin.access_grants`).
- **Evidencia Técnica:**
  - La vista `CustomerDetail.tsx` agrupa en una ficha única de 360 grados: identificación y tenant_id, plan y estado de suscripción, cuotas de uso (LOC y tokens), líneas asignadas, historial de consumo de los últimos ciclos, usuarios de la organización, integraciones activas y actividad del pipeline de desarrollo.
  - **Enmascaramiento por Defecto (Regla E6):** En ausencia de concesión activa, las razones sociales se retornan enmascaradas con viñetas estandarizadas (`A•••• S.L.`) y los correos electrónicos protegidos, acompañados de la insignia visual `ENMASCARADO`.
  - **Revelación Justificada (Break-Glass):** El modal reutilizable `SolicitudConcesionModal.tsx` permite solicitar formalmente una concesión vía `POST /admin/v1/access-grants`, exigiendo:
    1. Motivo operativo con un mínimo obligatorio de 20 caracteres.
    2. Referencia formal a ticket de soporte o incidente (`KC-####` o `SUP-####`).
    3. Alcance específico (`datos_negocio`, `expediente`, `contenido_codigo`).
    4. Ventana temporal acotada (15 a 480 minutos).
  - Al aprobarse la concesión, React Query invalida automáticamente la caché (`business-customers`, `business-customer-detail`), revelando los datos en claro con la insignia `EN CLARO`.
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

## 4. Auditoría Cruzada de Resiliencia, RBAC y Prevención SQLi

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

---

## 5. Registro de Deuda Técnica y Propuestas para Sprint 10

Durante el proceso de auditoría y revisión técnica se identificaron las siguientes oportunidades de mejora no bloqueantes para el Sprint 10:

1. **Caché en Redis de Agregados de Tokens (Sprint 10):**
   - *Observación:* La consulta analítica `/admin/v1/business/usage/tokens` calcula la agregación sobre `core.usage_tokens` en tiempo real.
   - *Recomendación:* Incorporar un mecanismo de caché en Redis con TTL de 300 segundos para consultas repetitivas de periodos mensuales consolidados.
2. **Exportación Asíncrona Directa desde Pantallas (Sprint 10):**
   - *Observación:* El exportador CSV/PDF ([KC-ADM-B4-09]) opera vía endpoint `/admin/v1/business/reports` mediante workers asíncronos en Redis.
   - *Recomendación:* Añadir un botón visual de descarga rápida "Exportar a CSV" en la cabecera de `biz-subs` y `biz-tokens` que invoque dicho flujo en un solo clic.
3. **Paginación Virtualizada en Radar de Suscripciones (Sprint 10):**
   - *Observación:* Actualmente la paginación de `biz-subs` maneja 25 registros por página con excelente rendimiento.
   - *Recomendación:* Evaluar *virtual scrolling* (TanStack Virtual) en caso de que el volumen de organizaciones supere los 5,000 tenants simultáneos.

---

## 6. Acta de Aceptación Formal y Sign-Off

Los roles firmantes confirman que la Consola de Negocio de KalliCode cumple plenamente con las especificaciones funcionales, los contratos de API y los criterios del Hito M5 (§5.3):

| Rol / Responsable | Nombre / Identificador | Estado | Fecha de Aceptación |
| :--- | :--- | :---: | :---: |
| **Product Owner (Negocio)** | PO Consola KalliCode | **APROBADO** | 11/11/2026 |
| **Dirección de Operaciones & FinOps** | Dirección KalliCode | **APROBADO** | 11/11/2026 |
| **Frontend Lead (E6)** | ADM3 (`kallicode-admin`) | **APROBADO** | 11/11/2026 |
| **Data Consistency & Security Auditor (E6)** | ADM4 (`kallicode-admin`) | **APROBADO** | 11/11/2026 |
| **Technical Lead (E6)** | Tech Lead Equipo E6 | **APROBADO** | 11/11/2026 |

---
*Fin del Acta de Auditoría — Consola de Negocio KalliCode (Hito M5)*
