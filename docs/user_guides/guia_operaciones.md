# Guía de Usuario: Operaciones (`staff_operaciones`)

- **Manual Maestro:** [admin_console_ops.md](file:///home/aagonzalezv/CAPSTONE/kallicode-admin/docs/runbooks/admin_console_ops.md) y [admin_manual.md](file:///home/aagonzalezv/CAPSTONE/kallicode-admin/docs/user_guides/admin_manual.md)
- **Propósito del rol:** Supervisión continua en tiempo real de la fábrica de software (agentes, colas, líneas de producción), observabilidad de modelos LLM y control de cumplimiento SLA.

---

## 1. Pantallas Autorizadas y Flujo Inicial

Al completar el acceso 2FA (`/login` -> `/mfa`), `InicioRedireccion` en [AppRouter.tsx](file:///home/aagonzalezv/CAPSTONE/kallicode-admin/apps/web/src/router/AppRouter.tsx) redirige automáticamente al rol `staff_operaciones` a `/ops/agents`:

| Vista | Ruta SPA | Permiso | Notas de Acceso |
|---|---|---|---|
| Estado de Agentes y Colas | `/ops/agents` | Permitido | Pantalla de entrada por defecto |
| Modelos LLM y Servicios Core | `/ops/models` | Permitido | Incluye salud de dependencias (`GET /admin/v1/health`) |
| Cumplimiento de SLA | `/ops/sla` | Permitido | Enmascarado aplicado por defecto en clientes |
| Vistas de Negocio y Clientes (`/overview`, `/business/*`) | — | Bloqueado | Redirige / renderiza `Error403` (`/403`) |

---

## 2. Operativa de las 3 Pantallas de Operaciones

### 2.1 Fábrica en Vivo: Agentes, Líneas y Colas (`/ops/agents`)
Implementada en [OpsAgents.tsx](file:///home/aagonzalezv/CAPSTONE/kallicode-admin/apps/web/src/vistas/OpsAgents.tsx), consulta de forma coordinada:
- `GET /admin/v1/ops/agents?ventana=...` (`5m`, `1h`, `24h`)
- `GET /admin/v1/ops/queues?incluir_dlq=...`

**Qué supervisar:**
1. **Líneas de producción (`core.production_lines`, leídas en BD `RO`):** líneas `activas`, en `mantenimiento` y `libres`.
2. **6 etapas canónicas del pipeline (`ETAPAS_CANONICAS`):** `triage`, `design`, `build`, `qa`, `security` y `deploy` (agentes totales, ocupados, caídos, jobs completados y duración p95).
3. **Colas y DLQ (`dead-letter queue`):** profundidad actual de cola y mensajes fallidos retenidos en DLQ.
4. **Distinción «Sin trabajo» vs «Sin telemetría»:**
   - Si no hay jobs activos pero Equipo 2 reporta latidos recientes (`telemetria.disponible: true`), los contadores aparecen en **`0`** (situación normal).
   - Si no existen latidos en la ventana solicitada (`telemetria.disponible: false`), los contadores dependientes de telemetría muestran valor nulo (**`null`**, nunca `0` falso).
   - Si el servicio de telemetría de Equipo 2 no responde o caduca, la API responde `HTTP 503 TELEMETRIA_NO_DISPONIBLE`.

### 2.2 Modelos LLM, Escalados y Salud Core (`/ops/models`)
Implementada en [OpsModels.tsx](file:///home/aagonzalezv/CAPSTONE/kallicode-admin/apps/web/src/vistas/OpsModels.tsx), combina `GET /admin/v1/ops/models` y `GET /admin/v1/health`:
1. **Ventanas de análisis:** `1h`, `24h`, `7d` y `30d`.
2. **KPIs por proveedor/modelo:** disponibilidad porcentual (alerta bajo `UMBRAL_DISPONIBILIDAD_1H = 99.0%`), latencia `p50` y `p95` en ms y tasa de error (%).
3. **Segregación estricta de tiers LLM:** los modelos, tokens y costes desglosan obligatoriamente los tres niveles **`flash`**, **`pro`** y **`fable`** por separado (nunca agrupando `fable` dentro de `pro`).
4. **Escalados LLM:** contadores de promoción automática `flash_a_pro`, `pro_a_fable` y `a_humano`.
5. **Salud de dependencias (`/admin/v1/health`):** estado visual de `postgres`, `lectura_analitica`, `cache`, `telemetria` y `agregados`.

### 2.3 Cumplimiento SLA y Explicabilidad de Reloj (`/ops/sla`)
Implementada en [OpsSLA.tsx](file:///home/aagonzalezv/CAPSTONE/kallicode-admin/apps/web/src/vistas/OpsSLA.tsx), consulta los agregados en BD `RO` (`GET /admin/v1/ops/sla`):
1. **Filtros operativos:** por ciclo, plan (`starter`, `growth`, `enterprise`) y casilla para aislar casos `en_riesgo` o `incumplidos`.
2. **Desglose por plan y casos críticos:** observa `cumplimiento_pct`, `tiempo_medio_h`, `p95_h` y advertencias si existieran planes en `sin_definicion`. Los nombres de cliente aparecen enmascarados salvo concesión vigente del operador.
3. **Explicabilidad cronológica (`DetalleRelojSLA`):** al hacer clic en un caso, la SPA llama a `GET /admin/v1/ops/sla/cases/{job_id}` y abre [DetalleRelojSLA.tsx](file:///home/aagonzalezv/CAPSTONE/kallicode-admin/apps/web/src/componentes/DetalleRelojSLA.tsx), mostrando:
   - Ecuación transparente: `Tiempo Bruto = Tiempo Computado + Pausas Justificadas`.
   - Línea de tiempo tramo a tramo diferenciando actividad computable y pausas tipificadas (`espera_firma_cliente`, `escalado_humano`, `ventana_mantenimiento`, `indisponibilidad_proveedor_llm`, `otro`).
4. **Exportación:** puedes generar informes SLA (`csv`, `xlsx`, `pdf`) con `ControlExportarReporte`.

---

## 3. Uso Eficiente del Refresco en Vivo (`ControlesLiveRefresh`)

Todas las vistas `/ops/*` integran [ControlesLiveRefresh.tsx](file:///home/aagonzalezv/CAPSTONE/kallicode-admin/apps/web/src/componentes/ControlesLiveRefresh.tsx):
- **Frecuencias seleccionables:** `15 s` (por defecto), `30 s`, `60 s` y `Manual`.
- **Ahorro de recursos automático:** al cambiar a otra pestaña o minimizar el navegador, el hook `useLiveRefresh` detecta `document.hidden` / pérdida de foco y pasa al estado amarillo **Pausado en segundo plano** automáticamente.
- **Presupuesto RL-4 (`60 req/min`):** en `/ops/agents` cada ciclo emite 2 peticiones (`agents` + `queues`, `peticionesPorCiclo = 2`). Si disparas múltiples actualizaciones manuales seguidas, el controlador protege el límite por empleado para evitar respuestas `429`.
- **Escalamiento ante fallos:** si aparece `503 TELEMETRIA_NO_DISPONIBLE` o retraso alto en agregados SLA, consulta los runbooks **RB-01** y **RB-04** desde [admin_console_ops.md](file:///home/aagonzalezv/CAPSTONE/kallicode-admin/docs/runbooks/admin_console_ops.md).
