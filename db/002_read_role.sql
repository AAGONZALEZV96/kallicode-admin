-- =============================================================================
-- KalliCode · Consola de Administración
-- Migración 002 — rol de lectura cross-tenant acotado por políticas
--
-- Resuelve la brecha ADM-G03. Es el fichero más delicado del subproyecto y el
-- único cuyo error no produce un fallo visible sino una fuga silenciosa: una
-- política mal escrita no rompe nada, solo devuelve más de lo que debía.
--
-- Principio: NO hay BYPASSRLS. Un rol con elusión de seguridad a nivel de fila
-- es un permiso binario y sin matices —quien lo tiene lo ve todo, siempre,
-- sobre cualquier tabla y cualquier columna— y trasladaría la garantía de
-- aislamiento desde la base de datos hasta la corrección del código de la
-- consola, que es justo lo que el diseño original se negaba a asumir.
--
-- El modelo es: rol sin elusión + política explícita por tabla + GRANT por
-- COLUMNA. Lo que no está concedido no se puede leer, y la lista de columnas
-- concedidas queda inventariada en admin.access_inventory para que la suite de
-- no-fuga pueda comprobar que lo accesible coincide con lo aprobado.
--
-- Requisitos previos: 001_admin_schema.sql y el esquema core de la plataforma.
-- La contraseña de los roles se fija fuera de este script, desde la bóveda.
-- =============================================================================

BEGIN;

-- -----------------------------------------------------------------------------
-- Dos roles con responsabilidades separadas
-- -----------------------------------------------------------------------------
DO $$
BEGIN
    -- Escribe únicamente en el esquema admin. No lee datos de cliente.
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'kallicode_admin_app') THEN
        CREATE ROLE kallicode_admin_app LOGIN NOBYPASSRLS;
    END IF;
    -- Solo lectura cross-tenant, acotada por política y por columna.
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'kallicode_admin_ro') THEN
        CREATE ROLE kallicode_admin_ro LOGIN NOBYPASSRLS;
    END IF;
END $$;

-- Salvaguarda: si alguien concede elusión de RLS a estos roles, este script
-- vuelve a quitarla en cada aplicación y la validación del final lo detecta.
ALTER ROLE kallicode_admin_app NOBYPASSRLS NOSUPERUSER NOCREATEDB NOCREATEROLE;
ALTER ROLE kallicode_admin_ro  NOBYPASSRLS NOSUPERUSER NOCREATEDB NOCREATEROLE;

COMMENT ON ROLE kallicode_admin_app IS
  'API de administración: DML sobre el esquema admin. Sin acceso a datos de cliente.';
COMMENT ON ROLE kallicode_admin_ro IS
  'Pool de lectura analítica de la consola. Lectura cross-tenant acotada por '
  'política y por columna. Nunca BYPASSRLS.';

-- -----------------------------------------------------------------------------
-- Inventario de acceso: la lista aprobada, versionada con el propio DDL
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS admin.access_inventory (
    table_name  text NOT NULL,
    column_name text NOT NULL,
    screens     text NOT NULL,          -- pantallas que lo necesitan
    pii         boolean NOT NULL,       -- exige concesión de acceso vigente
    rationale   text NOT NULL,
    PRIMARY KEY (table_name, column_name)
);

COMMENT ON TABLE admin.access_inventory IS
  'Lista aprobada de columnas que la consola puede leer. Toda ampliación exige '
  'justificación escrita y aprobación del gremio de datos. La suite de no-fuga '
  'compara esta tabla con los privilegios reales y falla si divergen.';

TRUNCATE admin.access_inventory;
INSERT INTO admin.access_inventory (table_name, column_name, screens, pii, rationale) VALUES
 -- organizaciones: identidad del cliente
 ('core.organizations','id','todas',false,'Clave de agrupación de todos los agregados.'),
 ('core.organizations','nombre','biz-customers',true,'Razón social. Identifica al cliente: enmascarada sin concesión.'),
 ('core.organizations','despliegue','biz-customers',false,'Modalidad de despliegue; relevante para soporte.'),
 ('core.organizations','fabrica_activa','biz-customers,biz-overview',false,'Indica si el cliente ha completado el onboarding.'),
 ('core.organizations','creado_en','biz-overview,biz-customers',false,'Fecha de alta: clientes nuevos por periodo.'),
 ('core.organizations','eliminado_en','biz-overview,biz-customers',false,'Borrado lógico: excluir de activos.'),
 ('core.organizations','idioma','biz-customers',false,'Idioma de la organización; contexto de soporte.'),
 -- planes y suscripciones
 ('core.plans','codigo','todas',false,'Plan vigente.'),
 ('core.plans','nombre','biz-overview,biz-subs',false,'Nombre comercial del plan.'),
 ('core.plans','lineas','biz-customers,biz-subs',false,'Líneas contratadas del plan.'),
 ('core.plans','loc_mes','biz-customers,biz-tokens',false,'Cuota mensual: base del porcentaje de uso.'),
 ('core.plans','max_usuarios','biz-customers',false,'Cupo de usuarios del plan.'),
 ('core.subscriptions','tenant_id','todas',false,'Clave de agrupación.'),
 ('core.subscriptions','plan_codigo','todas',false,'Plan vigente del cliente.'),
 ('core.subscriptions','estado','biz-overview,biz-customers,biz-subs',false,'Estado comercial.'),
 ('core.subscriptions','inicia_el','biz-subs',false,'Aniversario de contratación: base de la renovación.'),
 ('core.subscriptions','renueva_el','biz-subs,biz-overview',false,'Próxima renovación.'),
 ('core.subscriptions','finaliza_el','biz-subs',false,'Fin de la suscripción.'),
 ('core.upgrade_requests','id','biz-subs',false,'Solicitud de cambio de plan.'),
 ('core.upgrade_requests','tenant_id','biz-subs',false,'Cliente solicitante.'),
 ('core.upgrade_requests','plan_deseado','biz-subs',false,'Plan solicitado.'),
 ('core.upgrade_requests','comentario','biz-subs',true,'Texto libre del cliente: puede contener datos internos suyos.'),
 ('core.upgrade_requests','urgente','biz-subs',false,'Prioriza la cola comercial.'),
 ('core.upgrade_requests','estado','biz-subs',false,'Estado de la solicitud.'),
 ('core.upgrade_requests','creado_en','biz-subs',false,'Antigüedad de la solicitud.'),
 -- consumo
 ('core.usage_cycles','tenant_id','biz-tokens,biz-customers',false,'Clave de agrupación.'),
 ('core.usage_cycles','ciclo','biz-tokens,biz-customers',false,'Ciclo de facturación.'),
 ('core.usage_cycles','loc_consumidas','biz-tokens,biz-customers',false,'Consumo de líneas del ciclo.'),
 ('core.usage_cycles','umbral','biz-tokens',false,'Umbral del plan en el ciclo.'),
 ('core.usage_tokens','tenant_id','biz-tokens,ops-models',false,'Clave de agrupación.'),
 ('core.usage_tokens','tier','biz-tokens,ops-models',false,'Tier del modelo: fable se reporta aparte.'),
 ('core.usage_tokens','modelo','biz-tokens,ops-models',false,'Modelo concreto.'),
 ('core.usage_tokens','etapa','ops-models',false,'Etapa del pipeline.'),
 ('core.usage_tokens','invocaciones','ops-models',false,'Número de llamadas.'),
 ('core.usage_tokens','tokens_in','biz-tokens,ops-models',false,'Tokens de entrada.'),
 ('core.usage_tokens','tokens_out','biz-tokens,ops-models',false,'Tokens de salida.'),
 ('core.usage_tokens','duracion_ms','ops-models',false,'Latencia observada.'),
 ('core.usage_tokens','creado_en','biz-tokens,ops-models',false,'Ventana temporal.'),
 ('core.usage_loc','tenant_id','biz-tokens',false,'Clave de agrupación.'),
 ('core.usage_loc','ciclo','biz-tokens',false,'Ciclo.'),
 ('core.usage_loc','tipo','biz-tokens',false,'Entrega o ajuste comercial.'),
 ('core.usage_loc','netas','biz-tokens',false,'Líneas netas del PR entregado.'),
 ('core.usage_loc','creado_en','biz-tokens',false,'Ventana temporal.'),
 -- usuarios del cliente: identificables
 ('core.users','tenant_id','biz-customers',false,'Clave de agrupación.'),
 ('core.users','nombre','biz-customers',true,'Nombre de una persona: enmascarado sin concesión.'),
 ('core.users','rol','biz-customers',false,'Rol dentro de la organización.'),
 ('core.users','estado','biz-customers',false,'Activo o desactivado.'),
 ('core.users','ultimo_acceso','biz-customers',false,'Señal de actividad de la cuenta.'),
 -- integraciones: sin secretos ni configuración
 ('core.connections','tenant_id','biz-customers',false,'Clave de agrupación.'),
 ('core.connections','categoria','biz-customers',false,'Categoría de la integración.'),
 ('core.connections','proveedor','biz-customers',false,'Proveedor conectado.'),
 ('core.connections','nombre','biz-customers',true,'Nombre dado por el cliente: puede revelar su organización interna.'),
 ('core.connections','estado','biz-customers',false,'Estado de la conexión.'),
 ('core.connections','ultimo_test','biz-customers',false,'Última verificación con éxito.'),
 -- líneas, jobs y tickets: metadatos, nunca contenido
 ('core.production_lines','tenant_id','ops-agents,biz-customers',false,'Clave de agrupación.'),
 ('core.production_lines','numero','ops-agents,biz-customers',false,'Número de línea.'),
 ('core.production_lines','estado','ops-agents,biz-customers',false,'Libre, ocupada o en mantenimiento.'),
 ('core.jobs','tenant_id','ops-agents,ops-sla',false,'Clave de agrupación.'),
 ('core.jobs','id','ops-sla',false,'Caso para el desglose del reloj.'),
 ('core.jobs','ticket_id','ops-sla',false,'Ticket asociado.'),
 ('core.jobs','estado','ops-agents,ops-sla',false,'Estado de la máquina del pipeline.'),
 ('core.jobs','linea','ops-agents',false,'Línea ocupada.'),
 ('core.jobs','iteraciones','ops-sla',false,'Iteraciones consumidas.'),
 ('core.jobs','creado_en','ops-agents,ops-sla',false,'Inicio del caso.'),
 ('core.jobs','terminado_en','ops-agents,ops-sla',false,'Fin del caso.'),
 ('core.tickets','tenant_id','biz-overview,ops-sla',false,'Clave de agrupación.'),
 ('core.tickets','id','ops-sla',false,'Identificador interno.'),
 ('core.tickets','numero','ops-sla',true,'Correlativo visible del cliente: identifica su trabajo.'),
 ('core.tickets','tipo','biz-overview',false,'Bug, mejora o funcionalidad.'),
 ('core.tickets','etapa','biz-overview,ops-sla',false,'Etapa del pipeline.'),
 ('core.tickets','gate_pendiente','ops-sla',false,'Gate en espera: causa de pausa del reloj.'),
 ('core.tickets','creado_en','biz-overview,ops-sla',false,'Inicio del caso.'),
 ('core.tickets','cerrado_en','biz-overview,ops-sla',false,'Cierre del caso.'),
 -- transiciones y firmas: tiempos, no contenido
 ('core.job_transitions','tenant_id','ops-agents,ops-sla',false,'Clave de agrupación.'),
 ('core.job_transitions','job_id','ops-agents,ops-sla',false,'Caso.'),
 ('core.job_transitions','de_estado','ops-agents,ops-sla',false,'Estado de origen.'),
 ('core.job_transitions','a_estado','ops-agents,ops-sla',false,'Estado de destino.'),
 ('core.job_transitions','creado_en','ops-agents,ops-sla',false,'Momento de la transición: base del reloj de SLA.'),
 ('core.gate_signatures','tenant_id','ops-sla',false,'Clave de agrupación.'),
 ('core.gate_signatures','ticket_id','ops-sla',false,'Ticket firmado.'),
 ('core.gate_signatures','gate','ops-sla',false,'Gate firmado.'),
 ('core.gate_signatures','accion','ops-sla',false,'Aprobado o cambios pedidos.'),
 ('core.gate_signatures','creado_en','ops-sla',false,'Momento de la firma: fin de la pausa del reloj.'),
 -- pasos LLM: métricas, nunca las referencias de entrada y salida
 ('core.llm_steps','tenant_id','ops-models',false,'Clave de agrupación.'),
 ('core.llm_steps','etapa','ops-models',false,'Etapa del pipeline.'),
 ('core.llm_steps','paso','ops-models',false,'Paso del catálogo de plantillas.'),
 ('core.llm_steps','modelo','ops-models',false,'Modelo invocado.'),
 ('core.llm_steps','tier','ops-models',false,'Tier: flash, pro o fable.'),
 ('core.llm_steps','confianza','ops-models',false,'Confianza declarada por el modelo.'),
 ('core.llm_steps','validacion','ops-models',false,'Resultado de la validación de esquema.'),
 ('core.llm_steps','reintentos','ops-models',false,'Reintentos consumidos: base de la tasa de escalado.'),
 ('core.llm_steps','tokens_in','ops-models',false,'Tokens de entrada.'),
 ('core.llm_steps','tokens_out','ops-models',false,'Tokens de salida.'),
 ('core.llm_steps','duracion_ms','ops-models',false,'Latencia por proveedor.'),
 ('core.llm_steps','creado_en','ops-models',false,'Ventana temporal.'),
 -- onboarding: solo el recuento y la fase, nunca el contenido del documento
 ('core.onboarding_documents','tenant_id','biz-customers',false,'Clave de agrupación.'),
 ('core.onboarding_documents','tipo_documento','biz-customers',false,'Tipo de documento aportado.'),
 ('core.onboarding_documents','estado','biz-customers',false,'Estado del procesamiento.'),
 ('core.onboarding_documents','creado_en','biz-customers',false,'Fecha de aportación.');

-- -----------------------------------------------------------------------------
-- Concesión de privilegios: por columna, derivada del inventario
-- -----------------------------------------------------------------------------
GRANT USAGE ON SCHEMA core, audit, admin TO kallicode_admin_ro;
GRANT USAGE ON SCHEMA admin TO kallicode_admin_app;

-- El rol de aplicación escribe en su propio esquema y nada más.
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA admin TO kallicode_admin_app;
-- ... salvo el registro de auditoría, que es append-only (los triggers de
-- 001 lo impiden igualmente; esto lo hace explícito también en privilegios).
REVOKE UPDATE, DELETE, TRUNCATE ON admin.staff_actions FROM kallicode_admin_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA admin TO kallicode_admin_app;
-- Necesita comprobar que un tenant existe al crear una concesión (§18.13).
GRANT SELECT (id) ON core.organizations TO kallicode_admin_app;

-- El rol de lectura recibe SELECT columna a columna, generado del inventario.
DO $$
DECLARE
    r record;
BEGIN
    FOR r IN SELECT table_name, string_agg(quote_ident(column_name), ', ') AS cols
             FROM admin.access_inventory GROUP BY table_name
    LOOP
        EXECUTE format('GRANT SELECT (%s) ON %s TO kallicode_admin_ro',
                       r.cols, r.table_name);
    END LOOP;
END $$;

-- El propio esquema admin: lectura para las pantallas de auditoría y concesiones.
GRANT SELECT ON admin.staff, admin.access_grants, admin.staff_actions,
                admin.reports, admin.access_inventory TO kallicode_admin_ro;

-- -----------------------------------------------------------------------------
-- Políticas de lectura cross-tenant
--
-- Las tablas de core tienen FORCE ROW LEVEL SECURITY con política
-- `tenant_id = core.current_tenant()`. Aquí se añade una política adicional
-- que aplica SOLO al rol de lectura de la consola y solo para SELECT. Las
-- políticas permisivas se combinan con OR, así que esto no debilita el
-- aislamiento de kallicode_app: sigue viendo únicamente su tenant.
--
-- La lista de tablas es explícita a propósito. Una tabla que no figure aquí no
-- es legible por la consola aunque tenga privilegio de columna.
-- -----------------------------------------------------------------------------
DO $$
DECLARE
    t text;
    tablas text[] := ARRAY[
        'core.organizations', 'core.subscriptions', 'core.upgrade_requests',
        'core.usage_cycles', 'core.usage_tokens', 'core.usage_loc',
        'core.users', 'core.connections', 'core.production_lines',
        'core.jobs', 'core.tickets', 'core.job_transitions',
        'core.gate_signatures', 'core.llm_steps', 'core.onboarding_documents'
    ];
BEGIN
    FOREACH t IN ARRAY tablas LOOP
        EXECUTE format('DROP POLICY IF EXISTS admin_ro_select ON %s', t);
        EXECUTE format(
            'CREATE POLICY admin_ro_select ON %s FOR SELECT '
            'TO kallicode_admin_ro USING (true)', t);
    END LOOP;
END $$;

-- core.plans es global y no lleva RLS; basta el privilegio de columna.

-- -----------------------------------------------------------------------------
-- Validación: se ejecuta al aplicar y en la puerta de integración continua
-- -----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION admin.validate_read_role()
RETURNS TABLE (check_id text, detail text) AS $$
-- IMPORTANTE: esta funcion se invoca al arrancar la API con el rol kallicode_admin_app,
-- que NO es el que concede los privilegios. Las vistas information_schema.*_privileges
-- solo muestran privilegios concedidos A o POR un rol del que el invocador es miembro,
-- asi que desde kallicode_admin_app no ven los privilegios de kallicode_admin_ro:
-- V4 marcaba todo el inventario como "no concedido" y V2/V3/V5 devolvian siempre cero
-- filas (falso negativo: la barrera no detectaba nada). Aqui se usan
-- has_*_privilege() y aclexplode(), que consultan el catalogo y dan el mismo resultado
-- para cualquier invocador, incluidos los privilegios heredados y los de PUBLIC.
BEGIN
    -- V1: ningun rol de la consola puede eludir la seguridad a nivel de fila
    RETURN QUERY
    SELECT 'V1_sin_bypassrls'::text, rolname::text FROM pg_roles
    WHERE rolname IN ('kallicode_admin_app', 'kallicode_admin_ro')
      AND (rolbypassrls OR rolsuper);

    -- V2: el rol de lectura no tiene ningun privilegio de escritura
    RETURN QUERY
    SELECT 'V2_solo_lectura'::text, n.nspname || '.' || c.relname || ':' || p.priv
    FROM pg_class c
    JOIN pg_namespace n ON n.oid = c.relnamespace
    CROSS JOIN (VALUES ('INSERT'), ('UPDATE'), ('DELETE'), ('TRUNCATE')) AS p(priv)
    WHERE c.relkind IN ('r', 'p')
      AND n.nspname NOT IN ('pg_catalog', 'information_schema')
      AND n.nspname NOT LIKE 'pg\_toast%'
      AND CASE WHEN p.priv IN ('INSERT', 'UPDATE')
               THEN has_any_column_privilege('kallicode_admin_ro', c.oid, p.priv)
               ELSE has_table_privilege('kallicode_admin_ro', c.oid, p.priv) END;

    -- V3: no hay columna accesible fuera del inventario aprobado
    RETURN QUERY
    SELECT 'V3_fuera_de_inventario'::text,
           n.nspname || '.' || c.relname || '.' || a.attname
    FROM pg_attribute a
    JOIN pg_class c ON c.oid = a.attrelid
    JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname = 'core'
      AND c.relkind IN ('r', 'p', 'v', 'm', 'f')
      AND a.attnum > 0 AND NOT a.attisdropped
      AND has_column_privilege('kallicode_admin_ro', c.oid, a.attnum, 'SELECT')
      AND NOT EXISTS (
            SELECT 1 FROM admin.access_inventory ai
            WHERE ai.table_name = n.nspname || '.' || c.relname
              AND ai.column_name = a.attname);

    -- V4: toda columna del inventario esta efectivamente concedida
    RETURN QUERY
    SELECT 'V4_inventario_no_concedido'::text, ai.table_name || '.' || ai.column_name
    FROM admin.access_inventory ai
    WHERE ai.table_name LIKE 'core.%'
      AND NOT coalesce((
            SELECT has_column_privilege('kallicode_admin_ro', c.oid, a.attnum, 'SELECT')
            FROM pg_class c
            JOIN pg_namespace n ON n.oid = c.relnamespace
            JOIN pg_attribute a ON a.attrelid = c.oid
            WHERE n.nspname || '.' || c.relname = ai.table_name
              AND a.attname = ai.column_name AND NOT a.attisdropped), false);

    -- V5: el registro de acciones del personal no admite mutacion
    RETURN QUERY
    SELECT 'V5_auditoria_append_only'::text,
           (CASE WHEN x.grantee = 0 THEN 'PUBLIC' ELSE x.grantee::regrole::text END)
           || ':' || x.privilege_type
    FROM pg_class c
    JOIN pg_namespace n ON n.oid = c.relnamespace
    CROSS JOIN LATERAL aclexplode(c.relacl) AS x
    WHERE n.nspname = 'admin' AND c.relname = 'staff_actions'
      AND x.privilege_type IN ('UPDATE', 'DELETE', 'TRUNCATE')
      AND (CASE WHEN x.grantee = 0 THEN 'PUBLIC' ELSE x.grantee::regrole::text END)
          NOT IN ('postgres', 'kallicode_admin');

    -- V6: la cadena de acciones del personal es integra
    RETURN QUERY
    SELECT 'V6_cadena_integra'::text, motivo FROM admin.verify_staff_action_chain();
END $$ LANGUAGE plpgsql;

COMMENT ON FUNCTION admin.validate_read_role IS
  'Seis comprobaciones del modelo de acceso. Cero filas es correcto. Se ejecuta '
  'al aplicar la migración y en cada Pull Request, también tras cada migración '
  'de la plataforma, porque una tabla nueva en core podría abrir acceso sin que '
  'nadie lo revise.';

DO $$
DECLARE
    fallos int;
    d text;
BEGIN
    SELECT count(*), string_agg(check_id || ' -> ' || detail, '; ')
      INTO fallos, d FROM admin.validate_read_role();
    IF fallos > 0 THEN
        RAISE EXCEPTION 'Validación del modelo de acceso fallida (% fallos): %',
            fallos, d;
    END IF;
END $$;

COMMIT;
