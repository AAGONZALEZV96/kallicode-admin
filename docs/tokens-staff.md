# Tokens de Personal Distinguibles (`typ=staff`) y Separación Criptográfica de Realms

- **Documento:** `docs/tokens-staff.md`
- **Superficie de Exposición:** `/admin/v1` (Red Privada - Zero Ingress Público)
- **Ámbito:** Identidad, Autenticación y Criptografía de Sesión de Personal (`admin.staff`)

---

## 1. Separación Criptográfica de Realms

La Consola Admin de KalliCode no comparte identidad ni sesiones con el Portal de Clientes. Para evitar vectores de confusión de tokens (*token substitution attacks*), la plataforma aplica separación estricta mediante claims estándar en los encabezados y payloads de los JWT:

| Atributo | Portal de Clientes (`/api/v1`) | Consola Admin (`/admin/v1`) |
| :--- | :--- | :--- |
| **Catálogo de Identidad** | `core.users` (sujeto a tenant y RLS) | `admin.staff` (catálogo global interno) |
| **Tipo de Token (`typ`)** | `"user"` / `"portal"` | `"staff"` |
| **Emisor (`iss`)** | `"kallicode-portal-realm"` | `"kallicode-admin-realm"` |
| **Audiencia (`aud`)** | `"kallicode-portal-api"` | `"kallicode-admin-api"` |
| **Tiempo de Expiración (`exp`)** | 30 minutos | 15 minutos |
| **Segundo Factor (`mfa`)** | No obligatorio en todas las sesiones | Obligatorio (marca temporal en claim `mfa`) |

---

## 2. Claims Obligatorios en JWT de Staff

Todo token emitido por el servicio de autenticación de personal (`apps/api/src/admin_api/security.py`) debe contener los siguientes claims:

| Claim | Nombre | Tipo | Propósito y Validación |
| :--- | :--- | :--- | :--- |
| `sub` | Subject | `string` | Identificador único del empleado con prefijo semántico (`st_<ulid>`). |
| `iss` | Issuer | `string` | Emisor corporativo de administración. |
| `aud` | Audience | `string` | Audiencia corporativa de la API de administración. |
| `typ` | Type | `string` | Tipo de token: `"staff"`. |
| `rol` | Role | `string` | Uno de los roles de staff: `staff_soporte`, `staff_operaciones`, `staff_negocio`, `staff_admin`. |
| `mfa` | MFA Verified At | `integer` | Timestamp UNIX en UTC que acredita la verificación del segundo factor (TOTP). |
| `jti` | JWT ID | `string` | Identificador UUIDv4 único de un solo uso para revocación en Redis. |
| `iat` | Issued At | `integer` | Momento de emisión del token en formato UNIX UTC. |
| `exp` | Expiration Time | `integer` | Momento de expiración (máximo 15 minutos desde `iat`). |

---

## 3. Ejemplo de Payload JWT de Personal

```json
{
  "sub": "st_01HZABCDEF1234567890ABCDEF",
  "iss": "kallicode-admin",
  "aud": "kallicode-admin",
  "typ": "staff",
  "rol": "staff_soporte",
  "mfa": 1791500000,
  "jti": "b3e0c0df2e6d4c1b9b3e1f2a3c4d5e6f",
  "iat": 1791500000,
  "exp": 1791500900
}
```
## 4. Principios de Validación Criptográfica (`validar_tocken_staff`)
La función validar_token_staff(token) aplica las siguientes fases en orden estricto:

```
[Token JWT]
    │
    ▼
1. Decodificación y Firma RS256 con Clave Pública
    │  (Falla: ExpiredSignatureError / InvalidTokenError -> 401 NO_AUTENTICADO)
    ▼
2. Validación de Emisor y Audiencia
    │  (iss == "kallicode-admin-realm", aud == "kallicode-admin-api")
    │  (Falla: InvalidIssuerError / InvalidAudienceError -> 401 NO_AUTENTICADO)
    ▼
3. Presencia de Claims Obligatorios
    │  (require: ["sub", "rol", "typ", "mfa", "iss", "aud", "exp", "iat", "jti"])
    │  (Falla: MissingRequiredClaimError -> 401 NO_AUTENTICADO)
    ▼
4. Validación de Tipo y Sujeto
    │  (typ == "staff", sub no vacío)
    │  (Falla -> 401 NO_AUTENTICADO)
    ▼
5. Verificación de Rol en Catálogo
    │  (rol in ["staff_soporte", "staff_operaciones", "staff_negocio", "staff_admin"])
    │  (Falla -> 403 ROL_STAFF_INSUFICIENTE)
    ▼
[Retorno de Objeto StaffTokenData]
```
## 5. Respuestas de Error Estándar
Cualquier discrepancia se traduce en una respuesta estructurada bajo el estándar de la plataforma:

**Error 401: Token Inválido, Expirado o Realm Erróneo:**
```json
{
  "error": {
    "codigo": "NO_AUTENTICADO",
    "mensaje": "Emisor o tipo de token no válido para la consola de administración.",
    "detalle": null,
    "trace_id": "tr_01HZABCDEF1234567890ABCDEF",
    "timestamp": "2026-10-08T20:53:00Z"
  }
}
```
**Error 403: Rol Fuera de Catálogo**
```json
{
  "error": {
    "codigo": "ROL_STAFF_INSUFICIENTE",
    "mensaje": "Rol de personal no reconocido en el catálogo.",
    "detalle": null,
    "trace_id": "tr_01HZABCDEF1234567890ABCDEF",
    "timestamp": "2026-10-08T20:53:00Z"
  }
}
```