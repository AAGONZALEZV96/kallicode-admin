# ADR-001: Arquitectura de Consola Admin, Aplicación Propia y Despliegue en Red Privada

- **Estado:** Aceptado
- **Fecha:** Octubre 2026
- **Decisores:** ADM1 (Lead Full-Stack), ADM2 (Backend & Datos), Product Owner
- **Ticket Asociado:** [KC-ADM-B1-04] (Épica EAD1)
- **Área:** Consola de Administración (`kallicode-admin`)

---

## 1. Contexto y Planteamiento del Problema

La plataforma KalliCode opera bajo un modelo de aislamiento multi-tenant estricto forzado en la capa de persistencia mediante Row-Level Security (RLS) en PostgreSQL 16. La API pública (`/api/v1`) servida por `kallicode-backend` atiende el portal de clientes bajo un ingress público común expuesto a Internet.

Sin embargo, las funciones de soporte técnico a incidencias, monitoreo operativo de la fábrica de software y análisis de métricas de facturación (MRR, consumo de tokens, churn) requieren de forma indispensable **visibilidad cross-tenant** sobre múltiples clientes de manera simultánea.

### La Brecha de Seguridad ADM-G10:
El diseño inicial del backend planteaba montar los endpoints de administración y la API interna de telemetría en el mismo proceso y puerto HTTP que la API pública del portal de clientes. Este enfoque introducía una vulnerabilidad crítica:
1. **Exposición en Superficie Pública**: Colocar la superficie más sensible del sistema (capaz de consultar datos de múltiples inquilinos) detrás del mismo ingress público aumenta exponencialmente el riesgo ante vulnerabilidades de elusión de autenticación, inyecciones de cabeceras o errores de enrutamiento.
2. **Confusión de Identidad y Sustitución de Tokens (*Token Confusion / Privilege Escalation*)**: Compartir el catálogo de usuarios (`core.users`) y el mismo emisor de JWT entre clientes y empleados posibilitaba que un token emitido para un usuario del portal intentara consumir rutas de administración.
3. **Contaminación de Privilegios de Base de Datos**: Ejecutar la consola bajo el mismo pool de conexiones del backend forzaría el uso de permisos excesivos (`BYPASSRLS` o superusuario) para atravesar el aislamiento de inquilinos, destruyendo las garantías criptográficas y de base de datos de la plataforma.

---

## 2. Factores Decisivos (Drivers Arquitectónicos)

Para resolver la brecha ADM-G10, el Architecture Board estableció los siguientes factores rectores:
- **Seguridad en Profundidad y Menor Privilegio**: La capacidad de lectura cross-tenant debe estar blindada a nivel de red, proceso, identidad y motor de persistencia.
- **Superficie de Exposición Cero (Zero Public Ingress)**: Ningún endpoint de administración debe ser alcanzable directa o indirectamente desde Internet.
- **Aislamiento de Identidad**: El personal de KalliCode no debe figurar en tablas de clientes ni compartir el ciclo de vida de sesiones de clientes.
- **Persistencia Segregada sin `BYPASSRLS`**: Negativa innegociable a conceder privilegios de superadministrador o elusión global de RLS a la aplicación de consola.
- **Trazabilidad Inmutable y Auditoría Append-Only**: Todo acceso a datos de clientes debe sellarse criptográficamente en una cadena de hash inmutable visible para el propio cliente.

---

## 3. Opciones Consideradas

### Opción 1: Extender `kallicode-backend` compartiendo Ingress Público
Consistía en agregar el prefijo `/admin/v1` en la misma aplicación FastAPI de `kallicode-backend`, controlando el acceso exclusivamente mediante middleware y roles en la tabla de usuarios existente.
- *Ventajas*: Menor sobrecarga de infraestructura inicial; un solo repositorio y pipeline de despliegue.
- *Desventajas*:
  - Viola directamente el principio de menor superficie de ataque al exponer endpoints cross-tenant a Internet.
  - Riesgo inaceptable de fugas si falla una guarda de ruta en el router.
  - Obliga a relajar las políticas RLS en la conexión principal de base de datos.
- *Veredicto*: **Rechazada rotundamente.**

### Opción 2: Servicio y Frontend Propios Desplegados en Red Privada con Realm Staff Exclusivo (Elegida)
Crear un monorepo independiente (`kallicode-admin`) con su propia imagen de contenedor, configuración aislada, red privada corporativa con cero ingress público, catálogo de identidad propio (`admin.staff`) y doble cadena de conexión a PostgreSQL.
- *Ventajas*:
  - Superficie pública nula: la API no existe en los balanceadores ni en el ingress público.
  - Separación total de dominios de fallo e identidades.
  - Cumplimiento innegociable de las cuatro reglas de oro del equipo E6.
- *Desventajas*:
  - Mayor complejidad de infraestructura y despliegue.
  - Necesidad de sincronizar contratos y esquemas de prueba (`core_stub.sql`).
- *Veredicto*: **Aceptada por unanimidad.**

---

## 4. Decisión Adoptada y Justificación Técnica

Se adopta formalmente la **Opción 2**, articulada en cuatro decisiones arquitectónicas obligatorias:

```
┌────────────────────────────────────────────────────────┐
│                   RED PÚBLICA (INTERNET)               │
│  [Portal Cliente] ──(HTTPS)──> [Ingress Público]       │
│                                       │                │
│                                       ▼                │
│                            [kallicode-backend]         │
│                            (/api/v1 · core.users)      │
└───────────────────────────────────────┬────────────────┘
                                        │ (RLS Forzado)
                                        ▼
┌────────────────────────────────────────────────────────┐
│               POSTGRESQL 16 (KALLICODE_DB)             │
│   Esquema core.* (Datos Cliente con RLS estricto)      │
│   Esquema admin.* (Esquema aislado de Consola)         │
└───────────────────────────────────────▲────────────────┘
                                        │
           ┌────────────────────────────┴───────────────────────────┐
           │ Pool RO: kallicode_admin_ro  │ Pool APP: kallicode_admin_app │
           │ (NOBYPASSRLS - Solo Lectura)│ (DML sobre esquema admin)│
┌──────────┴──────────────────────────────┴─────────────────────────┴────┐
│                    RED PRIVADA CORPORATIVA (VPN / BASTION)             │
│                                                                        │
│   [Consola Web Admin] ──(HTTP Local / Loopback 127.0.0.1:8010)──>      │
│                          [FastAPI kallicode-admin]                     │
│                          (/admin/v1 · admin.staff)                     │
│                                                                        │
│                 CERO INGRESS PÚBLICO EN TODOS LOS ENTORNOS             │
└────────────────────────────────────────────────────────────────────────┘
```

### 4.1. Despliegue en Red Privada (Cero Ingress Público)
- La aplicación `kallicode-admin` se ejecuta exclusivamente dentro de la red privada corporativa (VNet/VPC interna).
- En entornos locales, la API y la consola web se vinculan únicamente a loopback (`127.0.0.1:8010` y `127.0.0.1:5173`).
- Queda terminantemente prohibido publicar reglas de Ingress, Application Gateway o balanceadores públicos hacia `/admin/v1`.
- El acceso por parte del personal requiere autenticación previa en la VPN corporativa o Bastion con control de acceso por dispositivo gestionado.

### 4.2. Proceso y Contenedores Aislados
- La Consola de Administración reside en un repositorio monorepo propio (`kallicode-admin`), produciendo sus propios artefactos Docker (`Dockerfile.api`, `Dockerfile.web`).
- La API FastAPI (`apps/api/`) y los workers en segundo plano (`apps/workers/`) operan en procesos independientes respecto a `kallicode-backend`.
- El ciclo de vida (`lifespan`) de la aplicación administra sus propios pools de conexiones asíncronas y clientes Redis, verificando la validez del modelo de acceso antes de admitir cualquier petición HTTP (`dbmod.verificar_arranque()`).

### 4.3. Realm de Identidad Staff Exclusivo
- El personal de KalliCode no existe en la tabla `core.users`. Toda cuenta de personal reside en la tabla global `admin.staff` (sin columna `tenant_id`).
- Todo JWT emitido por la API de administración incluye obligatoriamente los siguientes claims validados criptográficamente:
  - `typ="staff"`: Diferenciador innegociable de tipo de token.
  - `iss="kallicode-admin"` y `aud="admin-v1"`: Emisor y audiencia exclusivos de la consola.
  - `sub`: Identificador de personal con prefijo semántico `st_<ulid>`.
  - `rol`: Uno de los 4 roles canónicos (`staff_soporte`, `staff_operaciones`, `staff_negocio`, `staff_admin`).
  - `mfa`: Marca temporal de superación del segundo factor TOTP obligatorio.
- Inactividad máxima de 30 minutos; caducidad de access token en 15 minutos; rotación obligatoria de refresh tokens; y denylist instantánea en Redis mediante `jti`.
- Un token de cliente presentado en `/admin/v1` (o viceversa) es rechazado inmediatamente con HTTP 401 estructurado, aun cuando ambos compartiesen material de clave.

### 4.4. Modelo de Conexión Dual a Base de Datos (Sin `BYPASSRLS`)
Para consultar la base de datos sin comprometer la seguridad ni utilizar cuentas privilegiadas, la API opera obligatoriamente con dos cadenas de conexión y pools separados:
1. **DML sobre Esquema `admin` (`KC_ADMIN_DATABASE_URL_APP`)**:
   - Rol: `kallicode_admin_app`.
   - Permisos: Lectura y escritura en el esquema `admin` (gestión de personal, sesiones, registro de auditoría `admin.staff_actions`, concesiones `admin.access_grants`).
   - Sin acceso a tablas de clientes en `core.*`.
2. **Lectura Analítica Cross-Tenant (`KC_ADMIN_DATABASE_URL_RO`)**:
   - Rol: `kallicode_admin_ro`.
   - Permisos: `NOBYPASSRLS`. Concesión estricta `GRANT SELECT` columna a columna sobre las columnas registradas en `admin.access_inventory`.
   - Sin permisos de escritura (`UPDATE`, `INSERT`, `DELETE`) en ningún esquema.
   - Acceso al contenido de código fuente restringido a un máximo de 60 minutos bajo concesión explícita y temporal.
3. **Prohibición de Superusuario**:
   - La configuración de la API valida en el arranque que ninguna de las dos URLs pertenezca al usuario `postgres` o roles con atributos de superadministrador; de lo contrario, el proceso aborta inmediatamente.

---

## 5. Consecuencias y Mitigación de Riesgos

### Consecuencias Positivas:
- **Mitigación Total de ADM-G10**: Eliminación de la superficie de ataque público para operaciones cross-tenant.
- **Defensa en Profundidad**: Si una credencial de cliente se ve comprometida, no puede interactuar con `/admin/v1`.
- **Auditoría Forense Inmutable**: Cada consulta o revelación de datos queda sellada en la cadena hash SHA-256 de `admin.staff_actions` y es visible para el cliente desde su propio portal (§11.6).
- **Enmascaramiento por Defecto**: Datos sensibles (razón social, PII) retornan ofuscados salvo que exista una concesión activa y temporal con motivo fundado.

### Consecuencias Negativas y Complejidad Aceptada:
- **Gestión de Infraestructura Separada**: Mayor esfuerzo de orquestación (red privada, DNS interno, túneles VPN).
- **Doble Pool de Conexiones**: Mayor consumo de conexiones de base de datos en PostgreSQL, mitigado mediante límites de pool estrictos (`pool_size=5` para app, `pool_size=10` para analítica).
- **Sincronización de Contratos**: Necesidad de mantener contratos YAML congelados (`docs/openapi-admin-v1.yaml`) y stubs de prueba (`tests/fixtures/core_stub.sql`).

---

## 6. Referencias y Trazabilidad

- **Documento Rector**: *Kallicode - Diseño Backend API v1.1*, Capítulo 18: «Superficie de Administración /admin/v1».
- **Reglas del Agente**: `AGENTS.md` (Equipo E6 · Consola de Administración).
- **Catálogo de Brechas**: Brecha `ADM-G10` (Exposición pública de interfaces administrativas).
- **Tickets Relacionados del Bloque 1**:
  - `[KC-ADM-B1-06]`: Migración 001_admin_schema.sql (Auditoría encadenada e inmutabilidad).
  - `[KC-ADM-B1-07]`: Realm de Identidad de Personal (Staff Auth) con 2FA TOTP obligatorio.
  - `[KC-ADM-B1-08]`: Contrato OpenAPI `/admin/v1` Congelado en Versión v1.0 (OpenAPI 3.0.3).
  - `[KC-ADM-B1-09]`: Catálogo de Roles de Staff y Matriz de Permisos.
  - `[KC-ADM-B1-10]`: Tokens de Personal Distinguibles (`typ=staff`) y Separación de Emisor/Audiencia.
