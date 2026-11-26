# Backlog de Fase 2 y Deuda Técnica Aceptada Post-GA (`kallicode-admin`)

- **Ticket Asociado:** `[KC-ADM-B6-14]` — Validación de Aceptación de Usuario (UAT) y Sign-Off de Release MVP (Hito M6)
- **Acta de Sign-Off:** [uat_signoff_m6.md](informes/uat_signoff_m6.md)
- **Criterio de Clasificación:** Ninguno de los elementos listados compromete el aislamiento cross-tenant, la seguridad de red privada, el enmascaramiento por defecto ni la integridad criptográfica SHA-256 certificada en [informe_final_integridad_m6.md](seguridad/informe_final_integridad_m6.md).

---

## 1. Extensiones Funcionales Diferidas a Fase 2

| Código Fase 2 | Funcionalidad Diferida | Estado Actual en Release M6 (`v1.0.0`) | Evolución Planificada para Fase 2 | Prioridad |
|---|---|---|---|---|
| **KC-ADM-F2-01** | **Pantallas visuales en la SPA (`apps/web/`) para gestión de personal y visor de auditoría forense** | Operativas al 100% en el backend FastAPI bajo RBAC `staff_admin` (`/admin/v1/staff*`, `/admin/v1/access-grants*`, `/admin/v1/audit/staff-actions*`) y documentadas en [guia_admin.md](user_guides/guia_admin.md) y [rb-02-ciclo-vida-staff.md](runbooks/rb-02-ciclo-vida-staff.md). | Incorporar rutas visuales `/staff` y `/audit` en [AppRouter.tsx](../apps/web/src/router/AppRouter.tsx) reutilizando los endpoints congelados en [openapi-admin-v1.yaml](openapi-admin-v1.yaml). | Media |
| **KC-ADM-F2-02** | **Visor interactivo del grafo de dependencias (`CodeMapping`) en `CustomerDetail`** | La ficha 360° ([CustomerDetail.tsx](../apps/web/src/vistas/CustomerDetail.tsx)) muestra los KPIs agregados del grafo (cobertura, nodos, aristas y tiempo medio e2e). | Añadir visualización interactiva de topología bajo concesión activa con alcance `expediente`. | Media |
| **KC-ADM-F2-03** | **Integración automatizada con sistemas externos de tickets (`SUP-*` / `KC-*`)** | `SolicitudConcesionModal` y [grants.py](../apps/api/src/admin_api/routers/grants.py) validan sintaxis y longitud del motivo (`>= 20` caracteres + patrón de referencia). | Verificación en tiempo real contra la API del sistema de soporte y revocación automática de la concesión al cerrarse el ticket. | Baja |
| **KC-ADM-F2-04** | **Conexión productiva permanente con el colector de telemetría de Equipo 2** | Contrato HTTP validado en [telemetry.py](../apps/api/src/admin_api/telemetry.py) con `_TelemetryCircuitBreaker` y degradación limpia `503 TELEMETRIA_NO_DISPONIBLE`. | Activar el enlace VNet definitivo en cuanto Equipo 2 concluya el despliegue del servicio receptor en los entornos compartidos. | Alta (Dependencia E2) |
| **KC-ADM-F2-05** | **Reglas declarativas de Alertmanager / Grafana sobre `/metrics`** | Las 5 familias Prometheus (`ADMIN_METRICS_REGISTRY`) están instrumentadas y documentadas en [admin_console_ops.md](runbooks/admin_console_ops.md). | Publicar dashboards como código y alertas automáticas basadas en `admin_aggregates_freshness_seconds` y `admin_dependency_failures_total`. | Media |
| **KC-ADM-F2-06** | **Sincronización dinámica de catálogo tarifario y precios multi-divisa desde `core.plans`** | Para el Release GA (`v1.0.0`), los precios de suscripción (`900` / `2.900` / `9.500` EUR en `admin.plan_prices`, `003_business_aggregates.sql`) y tarifas por tier (`admin.token_rates`) están ratificados en [decisiones-negocio.md](decisiones-negocio.md). | Cuando el motor de facturación central incorpore precios versionados o descuentos personalizados en `core.*`, sincronizar `admin.plan_prices` sin romper los agregados históricos de MRR. | Baja (Dependencia Core) |
| **KC-ADM-F2-07** | **Objetivos de SLA personalizados por contrato (`custom enterprise SLA`)** | En GA rigen los objetivos por plan ratificados en [decisiones-negocio.md](decisiones-negocio.md) y sembrados en `admin.sla_targets` (`004_sla.sql`: `72h` Starter, `24h` Growth, `8h` Enterprise, riesgo al `80%`). | Permitir overrides opcionales por `tenant_id` en `admin.sla_targets` para acuerdos Enterprise con anexos de nivel de servicio específicos. | Baja |
| **KC-ADM-F2-08** | **Columna nativa `dominio` verificada por DNS en `core.organizations` (§18.18)** | En GA se cumple el contrato OpenAPI §18.18 sin modificar el DDL central mediante derivación determinista en `admin_api` (fallback: email admin `core.users` -> `core.connections` -> slug organización), según [decisiones-negocio.md](decisiones-negocio.md). | Coordinar con `kallicode-backend` la inclusión opcional de `core.organizations.dominio` verificada en onboarding y su registro en `admin.access_inventory`. | Baja (Dependencia Core) |

---

## 2. Condiciones de Gobernanza para su Implementación

1. Cualquier ampliación de endpoints para Fase 2 deberá respetar la [Política de Congelación y Versionado de Contrato](politica_contrato_admin.md): cambios aditivos opcionales podrán entrar en `/admin/v1`, mientras que cualquier cambio incompatible requerirá `/admin/v2` y al menos un sprint completo de convivencia.
2. Toda nueva columna de `core.*` que llegara a requerirse en Fase 2 deberá registrarse previamente en `admin.access_inventory` y superar las 6 reglas de `admin.validate_read_role()` y `make no-fuga`.
