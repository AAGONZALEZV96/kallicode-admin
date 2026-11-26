# Runbook RB-01: Fallo o Retraso en Refresco de Vistas Materializadas y Agregados

- **Manual Maestro:** [admin_console_ops.md](admin_console_ops.md)
- **Alcance:** Tablas `admin.agg_*`, `admin.sla_cases`, `admin.agg_sla_compliance`, tabla de control `admin.aggregate_state` y trabajos `refrescar_agregados` / `evaluar_sla` en `admin_workers`.

---

## 1. Síntomas y Alertas de Detección

1. **Sonda `GET /admin/v1/health`**:
   - Campo `agregados_frescura_s` por encima de `KC_ADMIN_AGGREGATE_MAX_AGE_S` (`21600` s / 6 h) → `estado: "degradado"`.
   - Campo `dependencias.agregados` en `false` o antigüedad superior a `KC_ADMIN_AGGREGATE_STALE_S` (`86400` s / 24 h) → HTTP `503` con código **`AGREGADO_NO_DISPONIBLE`** en endpoints de negocio y en `GET /admin/v1/ops/sla`.
2. **Métricas Prometheus (`GET /admin/v1/metrics` o `/metrics`)**:
   - `admin_aggregates_freshness_seconds` (`vista="global"`) en incremento continuo (> `21600`).
   - Incremento en `admin_dependency_failures_total{dependency="agregados"}`.
3. **Logs estructurados del worker (`admin_workers`)**:
   - `admin.business.frescura_alta` (nivel `WARNING`).
   - `admin.agregado.fallidos` (nivel `CRITICAL`).

---

## 2. Diagnóstico (Solo Lectura)

1. Consultar la sonda de salud desde red privada o VPN:
   ```bash
   curl -sS https://admin.internal.kallicode.com/admin/v1/health
   ```
2. Verificar en PostgreSQL el estado individual de cada agregado en `admin.aggregate_state`:
   ```sql
   SELECT agregado, status, refreshed_at,
          extract(epoch FROM (now() - refreshed_at))::int AS antiguedad_s,
          duration_ms, rows_total, error
   FROM admin.aggregate_state
   ORDER BY refreshed_at ASC NULLS FIRST;
   ```
3. Confirmar que el worker `python -m admin_workers.main` está activo y sin bloqueos largos en PostgreSQL (`KC_ADMIN_REFRESH_INTERVAL_S=900`, `SLA_EVALUATION_INTERVAL_S=300`, coordinación multi-réplica mediante `pg_try_advisory_lock` en `admin_workers.lider`).
4. Verificar que no existen errores de permisos ni alteraciones sobre `kallicode_admin_agg` / `kallicode_admin_ro`:
   ```sql
   SELECT * FROM admin.validate_read_role();
   ```

---

## 3. Acción Correctiva (Recálculo Manual `SECURITY DEFINER`)

> **Importante:** Las funciones `admin.refresh_*` pertenecen al rol `kallicode_admin_agg` (`NOLOGIN`, `SECURITY DEFINER`) y solo pueden invocarse con `kallicode_admin_app` o cuenta administrativa autorizada en mantenimiento, **nunca** con `kallicode_admin_ro`.

1. Si algún agregado de negocio (`customer_state`, `monthly_business`, `usage_cycle`, `tokens_daily`, `pipeline_daily`, `upgrade_requests`) quedó en estado `'fallido'` o obsoleto:
   ```sql
   SELECT * FROM admin.refresh_all_business_aggregates();
   ```
   *(Alternativa retrocompatible: `SELECT * FROM admin.refresh_all();`)*.
2. Si `sla_cases` o `agg_sla_compliance` superaron la ventana esperada, forzar recálculo de los últimos 95 días:
   ```sql
   SELECT admin.refresh_sla(95, true);
   ```
3. Si el recálculo manual arroja un error SQL en un agregado específico (por ejemplo cambio de esquema en `core.*`), revisar la columna `error` en `admin.aggregate_state` y escalar inmediatamente a ADM2.
4. Si el contenedor del worker estaba detenido o atascado, reiniciar el proceso `python -m admin_workers.main` (o el Container App `ca-kc-admin-<env>-workers`).

---

## 4. Verificación Post-Incidente

1. Confirmar `status = 'ok'` y `error IS NULL` en todas las filas de `admin.aggregate_state`.
2. Verificar en `GET /admin/v1/health` que `estado == "ok"`, `dependencias.agregados == true` y `agregados_frescura_s < 60`.
3. Confirmar HTTP `200` en `GET /admin/v1/business/overview` y `GET /admin/v1/ops/sla`, y descenso de `admin_aggregates_freshness_seconds` en `GET /admin/v1/metrics`.

---

## 5. Escalado

- Si `admin.refresh_all_business_aggregates()` vuelve a fallar o reporta `deadlock_detected` / timeout persistente → Escalar a **ADM2 (Backend & Datos)** adjuntando la salida de `admin.aggregate_state` y `pg_stat_activity`.
