# Tokens de Personal Distinguibles (`typ=staff`) y Separación Criptográfica de Realms

- **Documento:** `docs/tokens-staff.md`
- **Ticket:** KC-ADM-B1-10
- **Superficie de Exposición:** `/admin/v1` (Red Privada - Zero Ingress Público)
- **Ámbito:** Identidad, Autenticación y Criptografía de Sesión de Personal (`admin.staff`)

---

## 1. Separación Criptográfica de Realms

La Consola Admin de KalliCode no comparte identidad ni sesiones con el Portal de Clientes. Para evitar vectores de confusión o sustitución de tokens (*token substitution attacks*), la plataforma aplica separación estricta mediante claims estándar en los encabezados y payloads de los JWT:

| Atributo | Portal de Clientes (`/api/v1`) | Consola Admin (`/admin/v1`) |
| :--- | :--- | :--- |
| **Catálogo de Identidad** | `core.users` (sujeto a tenant y RLS) | `admin.staff` (catálogo global interno) |
| **Tipo de Token (`typ`)** | `"user"` / `"portal"` | `"staff"` |
| **Emisor (`iss`)** | `"kallicode-portal"` | `"kallicode-admin"` |
| **Audiencia (`aud`)** | `"portal-v1"` | `"admin-v1"` |
| **Tiempo de Expiración (`exp`)** | 30 minutos | 15 minutos |
| **Segundo Factor (`mfa`)** | No obligatorio en todas las sesiones | Obligatorio (marca temporal en claim `mfa`) |

---

## 2. Claims Obligatorios en JWT de Staff

Todo token emitido por el servicio de autenticación de personal (`apps/api/src/admin_api/security.py`) debe contener sin excepción los siguientes claims:

| Claim | Nombre | Tipo | Propósito y Validación |
| :--- | :--- | :--- | :--- |
| `sub` | Subject | `string` | Identificador único del empleado con prefijo semántico (`st_<ulid>`). |
| `iss` | Issuer | `string` | Emisor corporativo de administración: `"kallicode-admin"`. |
| `aud` | Audience | `string` | Audiencia corporativa de la API de administración: `"admin-v1"`. |
| `typ` | Type | `string` | Tipo de token innegociable: `"staff"`. |
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
  "aud": "admin-v1",
  "typ": "staff",
  "rol": "staff_soporte",
  "mfa": 1791500000,
  "jti": "b3e0c0df2e6d4c1b9b3e1f2a3c4d5e6f",
  "iat": 1791500000,
  "exp": 1791500900
}
```

---

## 4. Principios de Validación Criptográfica (`validar_token_staff`)

La función `validar_token_staff(token)` y la dependencia homónima en `deps.py` aplican las siguientes fases en orden estricto:

```
[Token JWT]
    │
    ▼
1. Decodificación y Firma Criptográfica
    │  (Falla: ExpiredSignatureError / InvalidTokenError -> HTTP 401 estructurado)
    ▼
2. Validación Estricta de Emisor y Audiencia
    │  (iss == "kallicode-admin", aud == "admin-v1")
    │  (Falla: InvalidIssuerError / InvalidAudienceError -> HTTP 401 estructurado)
    ▼
3. Presencia de Claims Obligatorios
    │  (require: ["sub", "rol", "typ", "mfa", "iss", "aud", "exp", "iat", "jti"])
    │  (Falla: MissingRequiredClaimError -> HTTP 401 estructurado)
    ▼
4. Validación Semántica de Tipo y Sujeto
    │  (typ == "staff", sub empieza con "st_")
    │  (Falla -> HTTP 401 estructurado)
    ▼
5. Verificación de Rol en Catálogo
    │  (rol in ["staff_soporte", "staff_operaciones", "staff_negocio", "staff_admin"])
    │  (Falla -> HTTP 401 estructurado / 403 ROL_STAFF_INSUFICIENTE)
    ▼
6. Verificación de Revocación en Redis
    │  (jti en denylist o iat <= revoked_at -> HTTP 401 estructurado)
    ▼
[Retorno de Claims Validados]
```

---

## 5. Respuestas de Error Estándar (`ErrorStandard`)

Cualquier discrepancia se traduce en una respuesta estructurada bajo el estándar de la plataforma (nunca texto plano):

**Error 401: Token Inválido, Expirado o Realm Erróneo:**
```json
{
  "error": {
    "codigo": "TOKEN_INVALIDO",
    "mensaje": "Emisor o tipo de token no válido para la consola de administración.",
    "detalle": null,
    "trace_id": "tr_01HZABCDEF1234567890ABCDEF",
    "timestamp": "2026-10-25T20:20:00Z"
  }
}
```

**Error 403: Violación de Autorización o Rol Fuera de Matriz:**
```json
{
  "error": {
    "codigo": "ROL_STAFF_INSUFICIENTE",
    "mensaje": "Tu rol no permite esta operación.",
    "detalle": null,
    "trace_id": "tr_01HZABCDEF1234567890ABCDEF",
    "timestamp": "2026-10-25T20:20:00Z"
  }
}
```
