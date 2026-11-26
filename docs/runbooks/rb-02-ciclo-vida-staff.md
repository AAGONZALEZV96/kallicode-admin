# Runbook RB-02: Ciclo de Vida y Revocación de Emergencia de Personal (`staff`)

- **Manual Maestro:** [admin_console_ops.md](admin_console_ops.md)
- **Alcance:** Alta por invitación, cambio de rol, revocación inmediata de sesiones JWT en Redis y PostgreSQL, revocación de concesiones activas (`admin.access_grants`) y desactivación de cuentas (`staff_admin`).

---

## 1. Alta por Invitación y Cambio de Rol (`staff_admin`)

1. **Invitar nuevo empleado** (`POST /admin/v1/staff/invitations`):
   - Requiere sesión activa con rol `staff_admin`.
   - El correo debe pertenecer al dominio corporativo `KC_ADMIN_STAFF_EMAIL_DOMAINS` (`kallicode.com`) y el rol debe ser uno de: `staff_soporte`, `staff_operaciones`, `staff_negocio`, `staff_admin`.
   - La invitación caduca según `KC_ADMIN_INVITATION_TTL_DAYS` (`7` días) y obliga al empleado a aceptar (`POST /admin/v1/auth/invitations/accept`) e inscribir TOTP (`POST /admin/v1/auth/mfa/enroll`).
2. **Cambiar rol de un empleado existente** (`PATCH /admin/v1/staff/{staff_id}`):
   - No se permite modificar la propia cuenta ni degradar al último `staff_admin` activo (`409 CONFLICTO_ESTADO`).
   - Al actualizar `rol`, la API revoca automáticamente los refresh tokens vigentes en `admin.staff_refresh_tokens` (`revoked_reason = 'cambio_de_rol'`) para obligar a emitir tokens nuevos con el rol actualizado.

---

## 2. Procedimiento de Revocación de Emergencia (Contención Inmediata)

Ejecutar ante sospecha de cuenta comprometida, baja inmediata de personal o uso indebido de concesiones:

### Paso 1 — Desactivar cuenta en `admin.staff` (`PATCH /admin/v1/staff/{staff_id}`)
```bash
curl -sS -X PATCH "https://admin.internal.kallicode.com/admin/v1/staff/${STAFF_ID}" \
  -H "Authorization: Bearer ${ADMIN_TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{"estado":"deactivated","motivo":"Revocacion de emergencia por incidente de seguridad"}'
```
Efectos automáticos verificados en [staff.py](../../apps/api/src/admin_api/routers/staff.py#L290-L399):
- Actualiza `admin.staff.status = 'deactivated'` (`staff_actual()` rechaza toda petición posterior del empleado con HTTP `403` código **`STAFF_DESACTIVADO`**).
- Revoca todos sus refresh tokens vigentes en `admin.staff_refresh_tokens` (`revoked_reason = 'desactivado'`).
- Revoca automáticamente todas sus concesiones activas en `admin.access_grants` (`revoked_reason = 'personal desactivado'`).
- Registra evento `staff_managed` en `admin.staff_actions` y log crítico `staff.desactivado`.

### Paso 2 — Cortar en Redis cualquier Access Token JWT emitido antes de la revocación
- Cada access token (`KC_ADMIN_STAFF_ACCESS_TOKEN_TTL_MIN = 15` min) valida en `staff_actual()` ([deps.py](../../apps/api/src/admin_api/deps.py#L135-L159)):
  1. Presencia en lista de denegación por `jti`: clave **`admin:denylist:{jti}`**.
  2. Marca de revocación global por empleado: clave **`admin:staff:{staff_id}:revoked_at`** (`iat <= revoked_at` → HTTP `401` **`TOKEN_INVALIDO`**).
  3. Estado vigente en `admin.staff` (`status != 'active'` → HTTP `403` **`STAFF_DESACTIVADO`**).
- El propio empleado (o un script de respuesta con sesión válida) puede invocar `POST /admin/v1/auth/logout` con `{"todas_las_sesiones": true}` para escribir inmediatamente ambas claves en Redis (`KC_REDIS_URL`). Si se requiere invalidación masiva directa en Redis sin esperar los 15 minutos ni depender de nueva consulta DB, establecer `SET admin:staff:<staff_id>:revoked_at <unix_epoch> EX 28800` sobre `KC_REDIS_URL`.

### Paso 3 — Revocar puntualmente concesiones activas ajenas (`DELETE /admin/v1/access-grants/{grant_id}`)
Cuando no corresponda desactivar al empleado pero deba retirarse de inmediato su acceso a un cliente:
1. Listar concesiones vigentes del empleado (`staff_admin`):
   ```bash
   curl -sS "https://admin.internal.kallicode.com/admin/v1/access-grants?ambito=todas&staff_id=${STAFF_ID}" \
     -H "Authorization: Bearer ${ADMIN_TOKEN}"
   ```
2. Revocar la concesión indicando motivo obligatorio (`motivo` ≥ 10 caracteres):
   ```bash
   curl -sS -X DELETE "https://admin.internal.kallicode.com/admin/v1/access-grants/${GRANT_ID}" \
     -H "Authorization: Bearer ${ADMIN_TOKEN}" \
     -H "Content-Type: application/json" \
     -d '{"motivo":"Cierre anticipado de acceso tras revision de seguridad"}'
   ```
   *(Registra acción `grant_revoked` en `admin.staff_actions` y log `admin.grant.revocado`).*

---

## 3. Verificación Post-Incidente

1. Consultar `GET /admin/v1/staff` confirmando `status = 'deactivated'` para la cuenta objetivo.
2. Confirmar que `GET /admin/v1/access-grants?ambito=todas&staff_id=<id>&estado=activas` devuelve `0` concesiones activas.
3. Verificar en `GET /admin/v1/audit/staff-actions?ambito=todas` el registro de `staff_managed` y/o `grant_revoked`.
4. Si la cuenta se reactiva posteriormente (`estado: "active"`), el empleado deberá reinscribir su TOTP obligatoriamente (`totp_secret` se limpia a `NULL` al reactivar).

---

## 4. Escalado

- Si el empleado revocado realizó consultas sospechosas a clientes antes de la desactivación → Ejecutar inmediatamente **RB-03** y escalar a **Seguridad / Equipo 5**.
