-- =============================================================================
-- KalliCode · Consola de Administración · esquema `admin`
-- Migración 001 — identidad de personal, concesiones de acceso y auditoría
--
-- Resuelve las brechas ADM-G02 (no existe identidad de personal) y ADM-G04
-- (las acciones del personal no quedan auditadas).
--
-- Nota de diseño sobre RLS: las tablas de este esquema NO llevan tenant_id ni
-- política de seguridad a nivel de fila, y eso es deliberado. No son datos de
-- cliente: son datos de la plataforma sobre su propio personal. El disparador
-- de DDL que E5 instala recorre core, vec, audit y cm; `admin` queda fuera a
-- propósito y así se documenta aquí para que nadie lo interprete como olvido.
-- Las dos tablas que referencian a un cliente (access_grants y staff_actions)
-- lo hacen como dato, no como eje de aislamiento.
--
-- Convenciones heredadas de db/01_schema.sql: identificadores ULID con prefijo
-- semántico, timestamptz, CHECK de dominio explícitos, nombres de constraint
-- estables.
-- =============================================================================

BEGIN;

CREATE SCHEMA IF NOT EXISTS admin;

COMMENT ON SCHEMA admin IS
  'Dominio propio de la consola de administración: personal de KalliCode, '
  'concesiones de acceso a datos de cliente y auditoría de sus acciones. '
  'Sin RLS por diseño: no contiene datos de cliente.';

-- -----------------------------------------------------------------------------
-- Personal de KalliCode
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS admin.staff (
    id                  text PRIMARY KEY,                 -- st_<ulid>
    email               text        NOT NULL,
    full_name           text        NOT NULL,
    role                text        NOT NULL,
    status              text        NOT NULL DEFAULT 'invited',
    password_hash       text,                             -- Argon2id; NULL mientras está invitado
    totp_secret         text,                             -- cifrado con la clave de la bóveda
    totp_enrolled_at    timestamptz,
    last_login_at       timestamptz,
    failed_attempts     int         NOT NULL DEFAULT 0,
    deactivated_at      timestamptz,
    deactivated_reason  text,
    created_at          timestamptz NOT NULL DEFAULT now(),
    updated_at          timestamptz NOT NULL DEFAULT now(),

    CONSTRAINT staff_email_uq     UNIQUE (email),
    CONSTRAINT staff_role_chk     CHECK (role IN ('staff_soporte', 'staff_operaciones',
                                                  'staff_negocio', 'staff_admin')),
    CONSTRAINT staff_status_chk   CHECK (status IN ('invited', 'active', 'deactivated')),
    CONSTRAINT staff_email_len    CHECK (char_length(email) BETWEEN 6 AND 320),
    CONSTRAINT staff_name_len     CHECK (char_length(full_name) BETWEEN 2 AND 120),
    -- una cuenta activa exige contraseña y segundo factor inscrito (§18.2, §18.3)
    CONSTRAINT staff_active_chk   CHECK (
        status <> 'active' OR (password_hash IS NOT NULL AND totp_secret IS NOT NULL)),
    -- la desactivación exige motivo y fecha (§18.12)
    CONSTRAINT staff_deact_chk    CHECK (
        status <> 'deactivated' OR (deactivated_at IS NOT NULL
                                    AND char_length(coalesce(deactivated_reason, '')) >= 10))
);

COMMENT ON TABLE admin.staff IS
  'Catálogo de personal de KalliCode. Realm separado de core.users, que exige '
  'pertenencia a una organización cliente (ADM-G02).';
COMMENT ON COLUMN admin.staff.totp_secret IS
  'Secreto TOTP cifrado. Nunca se devuelve por la API salvo en la inscripción.';

-- Códigos de recuperación de un solo uso, guardados solo en hash
CREATE TABLE IF NOT EXISTS admin.staff_recovery_codes (
    staff_id    text        NOT NULL REFERENCES admin.staff(id) ON DELETE CASCADE,
    code_hash   text        NOT NULL,
    used_at     timestamptz,
    created_at  timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (staff_id, code_hash)
);

-- -----------------------------------------------------------------------------
-- Invitaciones: única vía de alta de personal (§18.11, §18.8)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS admin.staff_invitations (
    id           text PRIMARY KEY,                        -- inv_<ulid>
    email        text        NOT NULL,
    role         text        NOT NULL,
    token_hash   text        NOT NULL,
    note         text,
    invited_by   text        NOT NULL REFERENCES admin.staff(id),
    expires_at   timestamptz NOT NULL,
    accepted_at  timestamptz,
    revoked_at   timestamptz,
    created_at   timestamptz NOT NULL DEFAULT now(),

    CONSTRAINT inv_token_uq   UNIQUE (token_hash),
    CONSTRAINT inv_role_chk   CHECK (role IN ('staff_soporte', 'staff_operaciones',
                                              'staff_negocio', 'staff_admin')),
    CONSTRAINT inv_note_len   CHECK (note IS NULL OR char_length(note) <= 280)
);

-- -----------------------------------------------------------------------------
-- Sesiones: desafío de segundo factor, refresh rotativo y reset de contraseña
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS admin.staff_mfa_challenges (
    id          text PRIMARY KEY,                         -- mfa_<ulid>
    staff_id    text        NOT NULL REFERENCES admin.staff(id) ON DELETE CASCADE,
    token_hash  text        NOT NULL,
    attempts    int         NOT NULL DEFAULT 0,
    ip          text,
    user_agent  text,
    expires_at  timestamptz NOT NULL,
    consumed_at timestamptz,
    created_at  timestamptz NOT NULL DEFAULT now(),

    CONSTRAINT mfa_token_uq    UNIQUE (token_hash),
    CONSTRAINT mfa_attempts_chk CHECK (attempts BETWEEN 0 AND 3)
);

COMMENT ON TABLE admin.staff_mfa_challenges IS
  'Desafío de segundo factor de un solo uso, vida 5 minutos. Reutilizarlo es '
  'incidente de seguridad y se registra como CRITICAL (§18.2).';

CREATE TABLE IF NOT EXISTS admin.staff_refresh_tokens (
    id          text PRIMARY KEY,                         -- rt_<ulid>
    staff_id    text        NOT NULL REFERENCES admin.staff(id) ON DELETE CASCADE,
    token_hash  text        NOT NULL,
    mfa_at      timestamptz NOT NULL,                     -- cuándo se verificó el 2FA de esta sesión
    ip          text,
    user_agent  text,
    expires_at  timestamptz NOT NULL,
    used_at     timestamptz,
    revoked     boolean     NOT NULL DEFAULT false,
    revoked_reason text,
    created_at  timestamptz NOT NULL DEFAULT now(),

    CONSTRAINT srt_token_uq UNIQUE (token_hash)
);

CREATE TABLE IF NOT EXISTS admin.staff_password_resets (
    id          text PRIMARY KEY,                         -- prt_<ulid>
    staff_id    text        NOT NULL REFERENCES admin.staff(id) ON DELETE CASCADE,
    token_hash  text        NOT NULL,
    expires_at  timestamptz NOT NULL,
    used_at     timestamptz,
    created_at  timestamptz NOT NULL DEFAULT now(),

    CONSTRAINT prt_token_uq UNIQUE (token_hash)
);

-- Historial de contraseñas: impide reutilizar las tres anteriores (§18.7)
CREATE TABLE IF NOT EXISTS admin.staff_password_history (
    staff_id      text        NOT NULL REFERENCES admin.staff(id) ON DELETE CASCADE,
    password_hash text        NOT NULL,
    created_at    timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (staff_id, created_at)
);

-- -----------------------------------------------------------------------------
-- Concesiones de acceso a datos de cliente (§18.13 – §18.15, ADM-G03/G09)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS admin.access_grants (
    id              text PRIMARY KEY,                     -- gr_<ulid>
    staff_id        text        NOT NULL REFERENCES admin.staff(id),
    tenant_id       text        NOT NULL REFERENCES core.organizations(id),
    scope           text        NOT NULL,
    reason          text        NOT NULL,
    reference       text,
    granted_at      timestamptz NOT NULL DEFAULT now(),
    expires_at      timestamptz NOT NULL,
    revoked_at      timestamptz,
    revoked_by      text        REFERENCES admin.staff(id),
    revoked_reason  text,
    reads           int         NOT NULL DEFAULT 0,

    CONSTRAINT grant_scope_chk  CHECK (scope IN ('datos_negocio', 'expediente',
                                                 'contenido_codigo')),
    CONSTRAINT grant_reason_len CHECK (char_length(reason) BETWEEN 20 AND 500),
    CONSTRAINT grant_window_chk CHECK (expires_at > granted_at),
    -- el alcance más sensible dura como máximo 60 min y exige referencia (§18.13)
    CONSTRAINT grant_code_chk   CHECK (
        scope <> 'contenido_codigo'
        OR (expires_at <= granted_at + interval '60 minutes'
            AND reference IS NOT NULL)),
    CONSTRAINT grant_revoke_chk CHECK (
        revoked_at IS NULL OR revoked_by IS NOT NULL)
);

COMMENT ON TABLE admin.access_grants IS
  'Concesión justificada y temporal de acceso a datos identificables de un '
  'cliente. Es el mecanismo que hace defendible la excepción de aislamiento '
  'de §3.3.1: sin concesión vigente los datos van enmascarados.';

-- Una sola concesión vigente por empleado, cliente y alcance (§18.13, 409)
CREATE UNIQUE INDEX IF NOT EXISTS grant_active_uq
    ON admin.access_grants (staff_id, tenant_id, scope)
    WHERE revoked_at IS NULL;

CREATE INDEX IF NOT EXISTS grant_staff_ix  ON admin.access_grants (staff_id, granted_at DESC);
CREATE INDEX IF NOT EXISTS grant_tenant_ix ON admin.access_grants (tenant_id, granted_at DESC);
CREATE INDEX IF NOT EXISTS grant_expiry_ix ON admin.access_grants (expires_at)
    WHERE revoked_at IS NULL;

-- -----------------------------------------------------------------------------
-- Auditoría de las acciones del personal (§18.29, ADM-G04)
--
-- Cadena de hash propia con la misma semántica que audit.audit_events, para que
-- la migración al sellado en la cadena central del tenant (Sprint 10 de E6, que
-- depende de la extensión del modelo de actor que entrega E5) no pierda
-- información. Append-only: sin UPDATE ni DELETE para el rol de aplicación.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS admin.staff_actions (
    id            bigint GENERATED ALWAYS AS IDENTITY,
    occurred_at   timestamptz NOT NULL DEFAULT now(),
    staff_id      text        NOT NULL REFERENCES admin.staff(id),
    staff_role    text        NOT NULL,
    action        text        NOT NULL,
    tenant_id     text        REFERENCES core.organizations(id),
    grant_id      text        REFERENCES admin.access_grants(id),
    scope         text,
    reason        text,
    resource      text,
    endpoint      text        NOT NULL,
    ip            text,
    user_agent    text,
    request_id    text,
    payload       jsonb,
    prev_seal     text        NOT NULL,
    seal          text        NOT NULL,

    PRIMARY KEY (occurred_at, id),
    CONSTRAINT sa_action_chk CHECK (action IN ('grant_created', 'grant_revoked',
                                               'read', 'reveal', 'report',
                                               'staff_managed', 'admin_query')),
    CONSTRAINT sa_seal_chk      CHECK (seal ~ '^[0-9a-f]{64}$'),
    CONSTRAINT sa_prev_seal_chk CHECK (prev_seal = '' OR prev_seal ~ '^[0-9a-f]{64}$')
) PARTITION BY RANGE (occurred_at);

COMMENT ON TABLE admin.staff_actions IS
  'Registro append-only de toda acción del personal sobre datos de cliente, '
  'con encadenamiento de hash verificable. Migra al sellado en la cadena del '
  'tenant afectado cuando E5 extiende el modelo de actor.';

-- Particiones mensuales precreadas: se crean antes de que exista volumen, que
-- es la única ventana en que la operación es barata (lección de DB-F09).
CREATE TABLE IF NOT EXISTS admin.staff_actions_default
    PARTITION OF admin.staff_actions DEFAULT;

DO $$
DECLARE
    m date := date_trunc('month', now())::date;
    i int;
BEGIN
    FOR i IN 0..11 LOOP
        EXECUTE format(
            'CREATE TABLE IF NOT EXISTS admin.staff_actions_%s '
            'PARTITION OF admin.staff_actions FOR VALUES FROM (%L) TO (%L)',
            to_char(m + (i || ' month')::interval, 'YYYYMM'),
            (m + (i || ' month')::interval)::date,
            (m + ((i + 1) || ' month')::interval)::date);
    END LOOP;
END $$;

CREATE INDEX IF NOT EXISTS sa_staff_ix   ON admin.staff_actions (staff_id, occurred_at DESC);
CREATE INDEX IF NOT EXISTS sa_tenant_ix  ON admin.staff_actions (tenant_id, occurred_at DESC)
    WHERE tenant_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS sa_action_ix  ON admin.staff_actions (action, occurred_at DESC);

-- Cabeza de la cadena: un único registro global
CREATE TABLE IF NOT EXISTS admin.staff_action_head (
    lock_id    int         PRIMARY KEY DEFAULT 1,
    last_seal  text        NOT NULL DEFAULT '',
    events     bigint      NOT NULL DEFAULT 0,
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT sah_single CHECK (lock_id = 1)
);

INSERT INTO admin.staff_action_head (lock_id) VALUES (1)
    ON CONFLICT (lock_id) DO NOTHING;

-- Sellado y encadenamiento. A diferencia del defecto DB-F04 de la cadena
-- central, aquí el sello previo se toma de la cabeza y no del propio evento,
-- de modo que la verificación pueda comprobar el encadenamiento real.
CREATE OR REPLACE FUNCTION admin.seal_staff_action() RETURNS trigger AS $$
DECLARE
    prev text;
BEGIN
    SELECT last_seal INTO prev FROM admin.staff_action_head
        WHERE lock_id = 1 FOR UPDATE;
    NEW.prev_seal := coalesce(prev, '');
    NEW.seal := encode(digest(
        NEW.prev_seal
        || NEW.occurred_at::text || NEW.staff_id || NEW.action
        || coalesce(NEW.tenant_id, '') || coalesce(NEW.scope, '')
        || coalesce(NEW.reason, '') || coalesce(NEW.resource, '')
        || NEW.endpoint || coalesce(NEW.payload::text, ''),
        'sha256'), 'hex');
    UPDATE admin.staff_action_head
        SET last_seal = NEW.seal, events = events + 1, updated_at = now()
        WHERE lock_id = 1;
    RETURN NEW;
END $$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_seal_staff_action ON admin.staff_actions;
CREATE TRIGGER trg_seal_staff_action
    BEFORE INSERT ON admin.staff_actions
    FOR EACH ROW EXECUTE FUNCTION admin.seal_staff_action();

-- Append-only: ninguna vía de mutación, ni siquiera si un privilegio se
-- concediera por error (lección de DB-F05).
CREATE OR REPLACE FUNCTION admin.forbid_staff_action_mutation() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'admin.staff_actions es append-only: % no está permitido',
        TG_OP USING ERRCODE = 'insufficient_privilege';
END $$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_staff_actions_immutable ON admin.staff_actions;
CREATE TRIGGER trg_staff_actions_immutable
    BEFORE UPDATE OR DELETE ON admin.staff_actions
    FOR EACH ROW EXECUTE FUNCTION admin.forbid_staff_action_mutation();

-- Verificación del encadenamiento completo. Devuelve la primera posición rota,
-- o ninguna fila si la cadena es íntegra.
CREATE OR REPLACE FUNCTION admin.verify_staff_action_chain(
    p_from timestamptz DEFAULT NULL,
    p_to   timestamptz DEFAULT NULL)
RETURNS TABLE (broken_at timestamptz, broken_id bigint, motivo text) AS $$
DECLARE
    r        record;
    expected text := NULL;
BEGIN
    FOR r IN
        SELECT * FROM admin.staff_actions
        WHERE (p_from IS NULL OR occurred_at >= p_from)
          AND (p_to   IS NULL OR occurred_at <  p_to)
        ORDER BY occurred_at, id
    LOOP
        -- 1. el sello previo debe ser el sello real del evento anterior
        IF expected IS NOT NULL AND r.prev_seal <> expected THEN
            RETURN QUERY SELECT r.occurred_at, r.id,
                'encadenamiento roto: se esperaba ' || left(expected, 12);
            RETURN;
        END IF;
        -- 2. el sello debe reproducirse a partir del contenido
        IF r.seal <> encode(digest(
                r.prev_seal || r.occurred_at::text || r.staff_id || r.action
                || coalesce(r.tenant_id, '') || coalesce(r.scope, '')
                || coalesce(r.reason, '') || coalesce(r.resource, '')
                || r.endpoint || coalesce(r.payload::text, ''),
                'sha256'), 'hex') THEN
            RETURN QUERY SELECT r.occurred_at, r.id, 'sello no reproducible';
            RETURN;
        END IF;
        expected := r.seal;
    END LOOP;
END $$ LANGUAGE plpgsql;

COMMENT ON FUNCTION admin.verify_staff_action_chain IS
  'Verifica sello Y encadenamiento. Corrige de origen el defecto DB-F04 de '
  'audit.verify_chain, que solo comprobaba los sellos individuales y por tanto '
  'no detectaba la supresión de un tramo intermedio.';

-- -----------------------------------------------------------------------------
-- Informes exportables (§18.22, §18.23, §18.30)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS admin.reports (
    id              text PRIMARY KEY,                     -- rp_<ulid> | ex_<ulid>
    kind            text        NOT NULL,
    format          text        NOT NULL,
    params          jsonb       NOT NULL,
    requested_by    text        NOT NULL REFERENCES admin.staff(id),
    includes_pii    boolean     NOT NULL DEFAULT false,
    status          text        NOT NULL DEFAULT 'en_cola',
    blob_ref        text,
    sha256          text,
    rows_total      int,
    error           jsonb,
    idempotency_key text,
    requested_at    timestamptz NOT NULL DEFAULT now(),
    completed_at    timestamptz,
    expires_at      timestamptz,

    CONSTRAINT rep_kind_chk   CHECK (kind IN ('consumo', 'suscripciones', 'clientes',
                                              'sla', 'staff_actions')),
    CONSTRAINT rep_format_chk CHECK (format IN ('csv', 'xlsx', 'pdf')),
    CONSTRAINT rep_status_chk CHECK (status IN ('en_cola', 'generando', 'listo', 'fallido')),
    CONSTRAINT rep_sha_chk    CHECK (sha256 IS NULL OR sha256 ~ '^[0-9a-f]{64}$'),
    -- un informe listo tiene fichero y hash; uno fallido no deja parcial
    CONSTRAINT rep_ready_chk  CHECK (
        status <> 'listo' OR (blob_ref IS NOT NULL AND sha256 IS NOT NULL)),
    CONSTRAINT rep_failed_chk CHECK (status <> 'fallido' OR blob_ref IS NULL),
    CONSTRAINT rep_idem_uq    UNIQUE (requested_by, idempotency_key)
);

CREATE INDEX IF NOT EXISTS rep_requester_ix ON admin.reports (requested_by, requested_at DESC);
CREATE INDEX IF NOT EXISTS rep_pending_ix   ON admin.reports (requested_at)
    WHERE status IN ('en_cola', 'generando');

COMMIT;
