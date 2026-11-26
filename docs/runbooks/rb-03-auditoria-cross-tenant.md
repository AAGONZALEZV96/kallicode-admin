# Runbook RB-03: Detección e Investigación de Patrones Anómalos de Acceso Cross-Tenant

- **Manual Maestro:** [admin_console_ops.md](admin_console_ops.md)
- **Alcance:** Auditoría de lecturas cross-tenant en `admin.staff_actions` y en la cadena central del tenant (`audit.audit_events`, `audit.chain_heads`), verificación SHA-256 e integridad end-to-end.

---

## 1. Señales de Alerta y Detección Temprana

1. **Métricas Prometheus (`GET /admin/v1/metrics`):**
   - Incremento anómalo en `admin_staff_actions_total` para `action="read"`, `action="reveal"` o `action="report"`.
2. **Anomalías en auditoría y concesiones:**
   - Empleado acumulando repetidamente el límite de `KC_ADMIN_GRANT_MAX_CONCURRENT` (`3`) concesiones activas o elevando lecturas sobre múltiples `tenant_id` fuera de tickets asignados.
   - Campo `verificado: false` en cualquier respuesta de `GET /admin/v1/audit/staff-actions` o en el portal del cliente (`GET /api/v1/audit/staff-accesses`).

---

## 2. Diagnóstico e Investigación (`staff_admin` + ADM2)

1. Consultar las acciones del personal sospechoso con `staff_admin`:
   ```bash
   curl -sS "https://admin.internal.kallicode.com/admin/v1/audit/staff-actions?ambito=todas&staff_id=${STAFF_ID}&desde=${DESDE}&hasta=${HASTA}" \
     -H "Authorization: Bearer ${ADMIN_TOKEN}"
   ```
   Revisar especialmente:
   - `motivo` declarado y código de ticket asociado;
   - `lecturas` acumuladas por cada `grant_id`;
   - `tenant_id` afectados y `endpoint` invocado;
   - bandera booleana `verificado`.
2. Revisar concesiones asociadas mediante `GET /admin/v1/access-grants?ambito=todas&staff_id=<id>`.
3. Verificar la **integridad criptográfica de la cadena local** (`admin.staff_actions`, protegida contra `UPDATE`/`DELETE` por el trigger `trg_staff_actions_immutable`):
   ```sql
   SELECT * FROM admin.verify_staff_action_chain();
   ```
   *Cero filas devueltas indica cadena íntegra.*
4. Verificar la **integridad de la cadena central del tenant** (`audit.audit_events` + `audit.chain_heads`, eventos con `actor_tipo = 'staff'`):
   ```sql
   SELECT tenant_id, ultimo_sello, eventos
   FROM audit.chain_heads
   WHERE tenant_id = '<tenant_id>';

   SELECT * FROM audit.verify_chain('<tenant_id>', '<desde>', '<hasta>');
   ```
   Confirmar igualmente la consulta equivalente en lectura desde `read_session` (`kallicode_admin_ro`) o mediante `verificar_cadena_central_tenant()` en `admin_api.audit`.

---

## 3. Protocolo de Contención y Preservación de Evidencia

1. **Si se confirma acceso no justificado o anomalía de comportamiento:**
   - Ejecutar inmediatamente el Runbook **[RB-02](rb-02-ciclo-vida-staff.md)**: revocar concesiones activas (`DELETE /admin/v1/access-grants/{grant_id}`), desactivar al empleado (`PATCH /admin/v1/staff/{staff_id}`) y cortar sesiones en Redis.
2. **Exportación formal de evidencias forenses** (`POST /admin/v1/audit/staff-actions/exports`, rol `staff_admin`):
   ```bash
   curl -sS -X POST "https://admin.internal.kallicode.com/admin/v1/audit/staff-actions/exports" \
     -H "Authorization: Bearer ${ADMIN_TOKEN}" \
     -H "Content-Type: application/json" \
     -d '{"desde":"2026-11-01","hasta":"2026-11-26","staff_id":"st_objetivo","formato":"csv"}'
   ```
   *(El worker `generar_informes` generará el fichero en `KC_ADMIN_REPORT_CONTAINER` sobre `KC_BLOB_ACCOUNT_URL` incluyendo los sellos y resultados de verificación).*
3. **Prohibición estricta:** Nunca intentar `ALTER TABLE` ni deshabilitar `trg_staff_actions_immutable` en producción o staging para "corregir" registros; `admin.staff_actions` es estrictamente *append-only*.

---

## 4. Verificación y Escalado

- Ejecutar `make no-fuga` en entorno validado o `SELECT * FROM admin.validate_read_role();` (`0` filas esperadas) para descartar fugas de columnas.
- Notificar de inmediato a **Seguridad / Equipo 5** y al **Product Owner** cuando exista impacto confirmado sobre datos de cliente visibles en `GET /api/v1/audit/staff-accesses`.
