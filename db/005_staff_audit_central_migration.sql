-- =============================================================================
-- KalliCode · Consola de Administración
-- Migración 005 — Conector e integración de auditoría de staff en la cadena
--                 central del tenant (KC-ADM-B6-06, hallazgo ADM-G04)
--
-- Propósito:
--   1. Habilitar en audit.audit_events el tipo de actor 'staff' cuando exista
--      el esquema central de auditoría de la plataforma.
--   2. Conceder privilegios mínimos append-only a kallicode_admin_app (solo
--      SELECT/INSERT en audit.audit_events, jamás UPDATE/DELETE/TRUNCATE) y
--      solo lectura por columna a kallicode_admin_ro, sin BYPASSRLS.
--   3. Añadir políticas RLS explícitas (con cláusula TO) para ambos roles de
--      la consola, impidiendo que kallicode_admin_app inserte eventos de otros
--      tipos de actor distintos a 'staff'.
--   4. Migrar de forma idempotente el histórico de admin.staff_actions con
--      tenant_id informado hacia audit.audit_events preservando trazabilidad
--      y orden cronológico (occurred_at, id), sin mutar admin.staff_actions.
-- =============================================================================

BEGIN;

DO $$
DECLARE
    r record;
    v_tiene_procedencia boolean := false;
    v_resumen text;
    v_datos jsonb;
    v_ip inet;
    v_tenant_prev text;
BEGIN
    IF to_regclass('audit.audit_events') IS NULL
       OR to_regclass('audit.chain_heads') IS NULL THEN
        RAISE NOTICE 'audit.audit_events o audit.chain_heads no están presentes; se omite conector central.';
        RETURN;
    END IF;

    -- -------------------------------------------------------------------------
    -- 1. Ampliar ae_actor_chk para admitir actor_tipo = 'staff'
    -- -------------------------------------------------------------------------
    ALTER TABLE audit.audit_events DROP CONSTRAINT IF EXISTS ae_actor_chk;
    ALTER TABLE audit.audit_events
        ADD CONSTRAINT ae_actor_chk
        CHECK (actor_tipo IN ('humano', 'agente', 'sistema', 'staff'));

    -- -------------------------------------------------------------------------
    -- 2. Privilegios mínimos y append-only estricto para roles de la consola
    -- -------------------------------------------------------------------------
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'kallicode_admin_app') THEN
        GRANT USAGE ON SCHEMA audit TO kallicode_admin_app;
        GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA audit TO kallicode_admin_app;
        GRANT SELECT, INSERT ON audit.audit_events TO kallicode_admin_app;
        REVOKE UPDATE, DELETE, TRUNCATE ON audit.audit_events FROM kallicode_admin_app;
        GRANT SELECT, INSERT, UPDATE ON audit.chain_heads TO kallicode_admin_app;
        REVOKE DELETE, TRUNCATE ON audit.chain_heads FROM kallicode_admin_app;

        IF to_regprocedure('audit.verify_chain(text,timestamptz,timestamptz)') IS NOT NULL THEN
            GRANT EXECUTE ON FUNCTION audit.verify_chain(text, timestamptz, timestamptz)
                TO kallicode_admin_app;
        END IF;
    END IF;

    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'kallicode_admin_ro') THEN
        GRANT USAGE ON SCHEMA audit TO kallicode_admin_ro;
        REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON audit.audit_events FROM kallicode_admin_ro;
        REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON audit.chain_heads FROM kallicode_admin_ro;
        -- Concesión explícita por columna (nunca GRANT SELECT ON tabla completa)
        GRANT SELECT (
            id, tenant_id, ticket_id, job_id, etapa, actor_tipo, actor_id,
            evento, resumen, datos, sello_previo, sello, creado_en
        ) ON audit.audit_events TO kallicode_admin_ro;
        GRANT SELECT (tenant_id, ultimo_sello, eventos) ON audit.chain_heads TO kallicode_admin_ro;

        IF to_regprocedure('audit.verify_chain(text,timestamptz,timestamptz)') IS NOT NULL THEN
            GRANT EXECUTE ON FUNCTION audit.verify_chain(text, timestamptz, timestamptz)
                TO kallicode_admin_ro;
        END IF;
    END IF;

    REVOKE UPDATE, DELETE, TRUNCATE ON audit.audit_events FROM PUBLIC;

    -- -------------------------------------------------------------------------
    -- 3. Políticas RLS explícitas para la consola (siempre con cláusula TO)
    -- -------------------------------------------------------------------------
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'kallicode_admin_app') THEN
        DROP POLICY IF EXISTS admin_app_audit_select ON audit.audit_events;
        CREATE POLICY admin_app_audit_select ON audit.audit_events
            FOR SELECT TO kallicode_admin_app USING (true);

        DROP POLICY IF EXISTS admin_app_audit_insert ON audit.audit_events;
        CREATE POLICY admin_app_audit_insert ON audit.audit_events
            FOR INSERT TO kallicode_admin_app WITH CHECK (actor_tipo = 'staff');

        DROP POLICY IF EXISTS admin_app_chain_heads_select ON audit.chain_heads;
        CREATE POLICY admin_app_chain_heads_select ON audit.chain_heads
            FOR SELECT TO kallicode_admin_app USING (true);

        DROP POLICY IF EXISTS admin_app_chain_heads_insert ON audit.chain_heads;
        CREATE POLICY admin_app_chain_heads_insert ON audit.chain_heads
            FOR INSERT TO kallicode_admin_app WITH CHECK (true);

        DROP POLICY IF EXISTS admin_app_chain_heads_update ON audit.chain_heads;
        CREATE POLICY admin_app_chain_heads_update ON audit.chain_heads
            FOR UPDATE TO kallicode_admin_app USING (true) WITH CHECK (true);
    END IF;

    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'kallicode_admin_ro') THEN
        DROP POLICY IF EXISTS admin_ro_audit_select ON audit.audit_events;
        CREATE POLICY admin_ro_audit_select ON audit.audit_events
            FOR SELECT TO kallicode_admin_ro USING (true);

        DROP POLICY IF EXISTS admin_ro_chain_heads_select ON audit.chain_heads;
        CREATE POLICY admin_ro_chain_heads_select ON audit.chain_heads
            FOR SELECT TO kallicode_admin_ro USING (true);
    END IF;

    -- -------------------------------------------------------------------------
    -- 4. Migración histórica idempotente de admin.staff_actions -> audit.audit_events
    --    (sin mutar ni eliminar registros en admin.staff_actions)
    -- -------------------------------------------------------------------------
    SELECT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'audit'
          AND table_name = 'audit_events'
          AND column_name = 'ip'
    ) INTO v_tiene_procedencia;

    v_tenant_prev := current_setting('app.tenant_id', true);

    FOR r IN
        SELECT sa.id, sa.occurred_at, sa.staff_id, sa.staff_role, sa.action,
               sa.tenant_id, sa.grant_id, sa.scope, sa.reason, sa.resource,
               sa.endpoint, sa.ip, sa.user_agent, sa.request_id, sa.payload, sa.seal
        FROM admin.staff_actions sa
        WHERE sa.tenant_id IS NOT NULL
          AND NOT EXISTS (
              SELECT 1 FROM audit.audit_events ae
              WHERE ae.tenant_id = sa.tenant_id
                AND ae.actor_tipo = 'staff'
                AND ae.datos->>'staff_action_id' = sa.id::text
                AND ae.datos->>'staff_action_seal' = sa.seal
          )
        ORDER BY sa.occurred_at ASC, sa.id ASC
    LOOP
        PERFORM set_config('app.tenant_id', r.tenant_id, true);

        v_resumen := format(
            'Acceso de personal (%s): %s',
            r.staff_role,
            coalesce(nullif(trim(r.reason), ''), r.action)
        );
        v_datos := jsonb_build_object(
            'schema_version', '1.0',
            'actor', jsonb_build_object(
                'typ', 'staff',
                'staff_id', r.staff_id,
                'rol', r.staff_role
            ),
            'action', r.action,
            'scope', r.scope,
            'grant_id', r.grant_id,
            'reason', r.reason,
            'resource', coalesce(nullif(r.resource, ''), 'customer:' || r.tenant_id),
            'endpoint', r.endpoint,
            'request_id', r.request_id,
            'occurred_at', to_char(r.occurred_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"'),
            'staff_action_id', r.id,
            'staff_action_seal', r.seal,
            'migrated_from_staff_actions', true,
            'metadata', coalesce(r.payload, '{}'::jsonb)
        );

        IF v_tiene_procedencia THEN
            v_ip := NULL;
            IF r.ip IS NOT NULL AND r.ip <> '' THEN
                BEGIN
                    v_ip := r.ip::inet;
                EXCEPTION WHEN OTHERS THEN
                    v_ip := NULL;
                END;
            END IF;

            INSERT INTO audit.audit_events (
                tenant_id, actor_tipo, actor_id, evento, resumen, datos,
                ip, user_agent, request_id, sello_previo, sello
            ) VALUES (
                r.tenant_id, 'staff', r.staff_id, 'staff_' || r.action, v_resumen, v_datos,
                v_ip, r.user_agent, r.request_id, '', repeat('0', 64)
            );
        ELSE
            INSERT INTO audit.audit_events (
                tenant_id, actor_tipo, actor_id, evento, resumen, datos,
                sello_previo, sello
            ) VALUES (
                r.tenant_id, 'staff', r.staff_id, 'staff_' || r.action, v_resumen, v_datos,
                '', repeat('0', 64)
            );
        END IF;
    END LOOP;

    PERFORM set_config('app.tenant_id', coalesce(v_tenant_prev, ''), true);
END $$;

-- Validación final del modelo de acceso (0 fallos esperados)
DO $$
DECLARE
    fallos int;
    d text;
BEGIN
    IF to_regprocedure('admin.validate_read_role()') IS NOT NULL THEN
        SELECT count(*), string_agg(check_id || ' -> ' || detail, '; ')
          INTO fallos, d FROM admin.validate_read_role();
        IF fallos > 0 THEN
            RAISE EXCEPTION 'Validación del modelo de acceso fallida tras 005 (% fallos): %',
                fallos, d;
        END IF;
    END IF;
END $$;

COMMIT;
