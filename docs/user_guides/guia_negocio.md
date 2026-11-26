# Guía de Usuario: Negocio y FinOps (`staff_negocio`)

- **Manual Maestro:** [admin_manual.md](file:///home/aagonzalezv/CAPSTONE/kallicode-admin/docs/user_guides/admin_manual.md)
- **Propósito del rol:** Seguimiento comercial y financiero (MRR, altas/bajas, renovaciones, upgrades, consumo LLM FinOps), exportación de informes y visibilidad ejecutiva de modelos LLM y SLA.

---

## 1. Pantallas Autorizadas

Tras autenticarse (`/login` -> `/mfa`), el rol `staff_negocio` accede por defecto a `/overview` (`InicioRedireccion` en [AppRouter.tsx](file:///home/aagonzalezv/CAPSTONE/kallicode-admin/apps/web/src/router/AppRouter.tsx)) con permisos sobre 6 de las 7 pantallas operativas (quedan restringidas únicamente `/ops/agents` y las operaciones administrativas exclusivas de `staff_admin`):

| Vista | Ruta SPA | Alias Soportado | Permiso |
|---|---|---|---|
| Panel General de Negocio | `/overview` | `/business/overview` | Permitido |
| Listado y Ficha 360° de Clientes | `/business/customers`, `/business/customers/:tenant_id` | `/customers`, `/customers/:tenant_id` | Permitido |
| Suscripciones y Upgrades | `/business/subscriptions` | `/subscriptions` | Permitido |
| Consumo de Tokens y FinOps | `/business/tokens` | `/tokens` | Permitido |
| Modelos LLM y Costes por Tier | `/ops/models` | — | Permitido (lectura compartida) |
| Cumplimiento SLA | `/ops/sla` | — | Permitido (lectura compartida) |
| Agentes en Vivo (`/ops/agents`) | — | — | Bloqueado (`403` / vista `Error403`) |

---

## 2. Recorrido por Vistas y Flujos de Negocio

### 2.1 Panel Ejecutivo (`/overview`)
Implementado en [BizOverview.tsx](file:///home/aagonzalezv/CAPSTONE/kallicode-admin/apps/web/src/vistas/BizOverview.tsx) (`GET /admin/v1/business/overview`):
- **Controles de análisis:** selecciona **Periodo** (`mes_actual`, `mes_anterior`, `trimestre`, `ano`) y **Comparar con** (`periodo_anterior`, `mismo_periodo_ano_anterior`).
- **4 bloques KPI consolidados:**
  1. **Ingreso Recurrente Mensual (MRR)** e ingresos en EUR con variación porcentual.
  2. **Clientes Activos:** total, altas, bajas/perdidos y distribución por plan (`starter`, `growth`, `enterprise`).
  3. **Consumo Agregado:** líneas de código (`LOC`), volumen total de tokens y coste comercial estimado.
  4. **Rendimiento del Pipeline:** tickets entregados, tiempo e2e `p50` (horas) y porcentaje de escalado humano.
- **Validación de frescura:** revisa siempre el badge junto al título. Si aparece en amarillo (`> 6 h`), los datos agregados llevan más de seis horas sin recalcular y conviene reportar a guardia de operaciones (**RB-01**).

### 2.2 Directorio de Clientes y Ficha 360° (`/business/customers` y `/business/customers/:tenant_id`)
Consulta clientes (`GET /admin/v1/business/customers`) con filtros por plan y estado, y accede al histórico de 6 ciclos e información contractual en [CustomerDetail.tsx](file:///home/aagonzalezv/CAPSTONE/kallicode-admin/apps/web/src/vistas/CustomerDetail.tsx) (`GET /admin/v1/business/customers/{tenant_id}`). Los datos identificables permanecen enmascarados salvo que solicites una concesión temporal justificada mediante `SolicitudConcesionModal` (`POST /admin/v1/access-grants`).

### 2.3 Ciclo de Suscripciones y Upgrades (`/business/subscriptions`)
Implementado en [BizSubscriptions.tsx](file:///home/aagonzalezv/CAPSTONE/kallicode-admin/apps/web/src/vistas/BizSubscriptions.tsx) mediante dos paneles sincronizados:
1. **Radar de Renovaciones (`GET /admin/v1/business/subscriptions`):** filtra por estado (`activa`, `periodo_gracia`, `suspendida`, `finalizada`), plan y ventana de renovación próxima, destacando alertas visuales a `<= 15` y `<= 30` días e importe mensual (`importe_mes`).
2. **Cola de Solicitudes de Upgrade (`GET /admin/v1/business/upgrade-requests`):** prioriza las peticiones más antiguas primero (`antiguedad_h`, badge `urgente`) mostrando `plan_actual -> plan_deseado` y cuota de uso actual (`cuota_uso_pct`).
- Ambas tablas incorporan badge explícito de enmascarado y acceso directo al modal de concesión (`POST /admin/v1/access-grants`) cuando sea necesario contactar o revisar un cliente concreto.

### 2.4 FinOps: Consumo de Tokens y Reconciliación (`/business/tokens`)
Implementado en [BizTokens.tsx](file:///home/aagonzalezv/CAPSTONE/kallicode-admin/apps/web/src/vistas/BizTokens.tsx) (`GET /admin/v1/business/usage/tokens`):
- **Agrupaciones disponibles:** agrupa resultados por **`cliente`**, **`tier`** o **`dia`**, filtrando por periodo, plan/tier y búsqueda debounced (`q`).
- **Métricas FinOps:** total consolidado de tokens (`tokens_in`, `tokens_out`, `tokens_total`), coste consolidado EUR, porcentaje medio respecto a cuota asignada y columna **`cuadra_con_facturacion`** para reconciliación contable.
- **Separación de tiers LLM:** al igual que `/ops/models`, desglosa estrictamente **`flash`**, **`pro`** y **`fable`** sin mezclar costes ni volúmenes de `fable` dentro de `pro`.

### 2.5 Exportación Asíncrona de Informes (`ControlExportarReporte`)
Desde `/business/customers`, `/business/tokens` y `/ops/sla`, el botón de exportación ([ControlExportarReporte.tsx](file:///home/aagonzalezv/CAPSTONE/kallicode-admin/apps/web/src/componentes/ControlExportarReporte.tsx)):
1. Permite elegir formato (`csv`, `xlsx` o `pdf`), rango de fechas y filtros aplicables.
2. Envía la solicitud asíncrona a `POST /admin/v1/business/reports` (registrando la acción `report` en `admin.staff_actions`).
3. Realiza polling sobre `GET /admin/v1/business/reports/{report_id}` hasta completar la generación en background por el worker y habilitar la descarga verificada con su `hash_sha256`.
