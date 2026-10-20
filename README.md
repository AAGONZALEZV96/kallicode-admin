# kallicode-admin · Consola interna de administración

Servicio de la consola interna de KalliCode: `/admin/v1`, 31 endpoints, capítulo 18
del documento «Kallicode - Diseño Backend API v1.1». Es el entregable del equipo
**E6 · KC-ADM**.

## Lo que hay que entender antes de tocar este repositorio

Esta consola es **la única excepción declarada al aislamiento por inquilino** de
KalliCode. Todo el resto de la plataforma garantiza que los datos de un cliente son
inaccesibles desde el contexto de otro, y lo garantiza en el motor de base de datos
con *row-level security* forzada. La consola necesita ver a varios clientes a la vez
para poder dar soporte y facturar, así que necesariamente sale de esa garantía.

La excepción es aceptable solo porque descansa en **cuatro reglas inseparables**.
Quitar una cualquiera de las cuatro convierte la consola en un agujero:

1. **Rol de lectura acotado.** `kallicode_admin_ro` no tiene `BYPASSRLS`. Tiene
   `GRANT SELECT` columna a columna sobre las ~95 columnas del inventario aprobado
   (`admin.access_inventory`) y nada más. El código fuente de los clientes no está
   en ese inventario.
2. **Enmascarado por defecto y concesiones justificadas.** Los datos identificables
   salen enmascarados siempre. Revelarlos exige una concesión con motivo escrito,
   referencia a un caso y vencimiento; el acceso al contenido de código no pasa de
   60 minutos.
3. **Sellado en la cadena del cliente.** Cada lectura y cada concesión se registran
   en `admin.staff_actions`, tabla append-only con cadena de sellos.
4. **Visibilidad para el cliente.** Ese registro se expone en el portal del cliente
   (§11.6). El cliente ve quién de KalliCode accedió a sus datos, cuándo y por qué.

Si vas a añadir un endpoint, la pregunta no es «¿funciona?» sino «¿cuál de las
cuatro reglas afecta?».

## Estructura

```
db/                        migraciones (aplicar en orden)
  001_admin_schema.sql       esquema admin, auditoría encadenada, particiones
  002_read_role.sql          los dos roles, inventario de acceso, validate_read_role()
  003_business_aggregates.sql agregados vía SECURITY DEFINER de un tercer rol
  004_sla.sql                objetivos, pausas y cálculo del reloj de servicio
apps/api/src/admin_api/    servicio FastAPI (7 routers, 31 endpoints)
apps/workers/src/          tres trabajos con elección de líder
tests/                     la suite (ver más abajo)
```

## Arranque local

```bash
pip install -e ".[dev]"
cp .env.example .env                 # rellenar los dos DSN y el secreto de firma
psql "$KC_ADMIN_DATABASE_URL_APP" -f db/001_admin_schema.sql   # y 002, 003, 004
uvicorn admin_api.main:app --port 8010
python -m admin_workers.main
```

Las dos cadenas de conexión son distintas a propósito: `..._APP` escribe en el
esquema `admin` y no alcanza las tablas de cliente; `..._RO` lee las tablas de
cliente y no puede escribir nada. La configuración rechaza el arranque si alguna de
las dos apunta al superusuario.

## La suite

```bash
pytest -m "not integracion"     # unitarias, segundos, sin base de datos
pytest                          # completa; levanta PostgreSQL 16 con testcontainers
KC_ADMIN_TEST_DSN=postgresql://... pytest     # reutiliza una base ya levantada
```

Las pruebas de integración necesitan también el esquema de la plataforma, que se
espera en `../kallicode-backend/db`. Sin él se omiten en lugar de fallar.

| Fichero | Qué defiende |
|---|---|
| `test_authorization_matrix.py` | 31 endpoints × 4 roles, negativa exhaustiva. Falla si aparece un endpoint sin declarar. |
| `test_no_leak.py` | Los privilegios reales del rol de lectura coinciden con el inventario, en las dos direcciones. |
| `test_masking.py` | Ningún campo identificable sobrevive sin concesión; la jerarquía de alcances no se salta. |
| `test_grants.py` | Ciclo completo, motivos genéricos rechazados, techo de duración, límite de simultáneas, caducidad automática. |
| `test_staff_audit.py` | Append-only, cadena encadenada, detección de una supresión con el eslabón recompuesto. |
| `test_auth_flow.py` | Indistinguibilidad de los fallos de acceso, reutilización de desafíos y de tokens de refresco. |
| `test_endpoints_smoke.py` | Un camino feliz por pantalla, y honestidad del dato ausente (503, nunca un cero). |
| `test_pagination.py` | El orden se traduce desde una lista blanca; nada de la entrada llega al SQL. |

La cobertura mínima es del 80 % global. Los módulos de autorización, enmascarado y
auditoría se mantienen por encima del 95 %: no son los más grandes, son los que
producen incidentes de datos cuando fallan.

**Por qué la suite usa PostgreSQL real y no un doble.** Las propiedades que
importan aquí viven en el motor: `NOBYPASSRLS`, los `GRANT` por columna, el índice
parcial único de las concesiones, la restricción de 60 minutos, el disparador
append-only y la función de verificación de la cadena. Un doble en memoria las daría
todas por buenas. La auditoría de la plataforma encontró 154 defectos y los cinco
más graves eran exactamente de esta clase.

## Decisiones que conviene no revisar sin leer antes el plan de E6

- **Sin `BYPASSRLS`, nunca.** La alternativa cómoda al inventario de columnas.
- **Agregados en tablas con funciones `SECURITY DEFINER`**, no vistas
  materializadas: refrescar una vista materializada exige ser su propietario, y eso
  rompería la separación entre el rol que lee y el que escribe.
- **Realm de identidad propio** con contraseña y TOTP, emisor y audiencia distintos
  de la API de cliente, y `typ=staff` en el token.
- **El dato ausente se dice.** Un agregado viejo o una telemetría caída devuelven
  503 con código propio. Un panel de ceros es peor que un error.

## Pendiente

- Ratificar los precios de plan sembrados de forma provisional en
  `003_business_aggregates.sql` (900 / 2.900 / 9.500 EUR): `core.plans` no tiene
  columna de precio.
- Ratificar los objetivos de servicio provisionales de `004_sla.sql` (72 / 24 / 8 h).
- `core.organizations` no tiene columna `dominio`, aunque el contrato de §18.18 la
  menciona: decidir si se añade al modelo o se retira del contrato.
