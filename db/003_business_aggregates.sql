-- =============================================================================
-- KalliCode · Consola de Administración
-- Migración 003 — agregados de negocio y su refresco
--
-- Resuelve la brecha ADM-G05. Las tablas de core existen pero están indexadas
-- para el patrón contrario —acceso por tenant_id como primera columna— y la
-- consola necesita agregación cross-tenant por periodo, plan y tier. Consultarlas
-- en vivo produciría esperas de segundos compitiendo con el tráfico del portal.
--
-- Decisión de arquitectura: tablas de agregado con funciones SECURITY DEFINER, y
-- no vistas materializadas. El motivo es el modelo de acceso: refrescar una vista
-- materializada exige ser su propietario, y el propietario tendría que poder leer
-- core, lo que rompería la separación entre el rol que escribe (sin acceso a datos
-- de cliente) y el que lee (sin capacidad de escritura). Con funciones SECURITY
-- DEFINER propiedad de un tercer rol de agregación, el privilegio de lectura
-- queda encapsulado en la función y ni el rol de la aplicación ni el de lectura lo
-- adquieren.
--
-- Dos tablas de configuración que no existen en la plataforma y aquí hacen falta:
--   · admin.plan_prices  — core.plans no tiene importe, así que el ingreso
--     recurrente de §18.16 no se puede calcular sin declararlo en algún sitio.
--   · admin.token_rates  — el coste estimado de §18.21 depende de tarifas de
--     proveedor que cambian dentro del ciclo, y así se declara al usuario.
-- =============================================================================

BEGIN;

-- -----------------------------------------------------------------------------
-- Rol de agregación: lee core, escribe solo los agregados
-- -----------------------------------------------------------------------------
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'kallicode_admin_agg') THEN
        CREATE ROLE kallicode_admin_agg NOLOGIN NOBYPASSRLS;
    END IF;
END $$;
ALTER ROLE kallicode_admin_agg NOBYPASSRLS NOSUPERUSER;

COMMENT ON ROLE kallicode_admin_agg IS
  'Propietario de las funciones de agregación (SECURITY DEFINER). Lee las mismas '
  'columnas del inventario que kallicode_admin_ro y escribe solo en las tablas '
  'admin.agg_*. Sin LOGIN: nadie se conecta con él.';

GRANT USAGE ON SCHEMA core, admin TO kallicode_admin_agg;

-- -----------------------------------------------------------------------------
-- Configuración: precios y tarifas
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS admin.plan_prices (
    plan_codigo   text        NOT NULL REFERENCES core.plans(codigo),
    importe_mes   numeric(12,2) NOT NULL,
    moneda        text        NOT NULL DEFAULT 'EUR',
    vigente_desde date        NOT NULL DEFAULT current_date,
    PRIMARY KEY (plan_codigo, vigente_desde),
    CONSTRAINT pp_importe_chk CHECK (importe_mes >= 0),
    CONSTRAINT pp_moneda_chk  CHECK (moneda ~ '^[A-Z]{3}$')
);

COMMENT ON TABLE admin.plan_prices IS
  'Importe mensual por plan. core.plans define límites pero no precio, así que el '
  'ingreso recurrente de §18.16 no sería calculable sin esta tabla. Los valores '
  'los ratifica el Product Owner; los de la semilla son provisionales.';

CREATE TABLE IF NOT EXISTS admin.token_rates (
    tier          text        NOT NULL,
    modelo        text        NOT NULL DEFAULT '*',
    precio_in     numeric(12,6) NOT NULL,      -- por 1.000 tokens de entrada
    precio_out    numeric(12,6) NOT NULL,      -- por 1.000 tokens de salida
    moneda        text        NOT NULL DEFAULT 'EUR',
    vigente_desde date        NOT NULL DEFAULT current_date,
    PRIMARY KEY (tier, modelo, vigente_desde),
    CONSTRAINT tr_tier_chk CHECK (tier IN ('flash', 'pro', 'fable'))
);

COMMENT ON TABLE admin.token_rates IS
  'Tarifa por tier y modelo. El coste que la consola muestra es estimado y así se '
  'declara: depende de tarifas que pueden cambiar dentro del ciclo.';

-- -----------------------------------------------------------------------------
-- Estado del refresco: la frescura es parte de la respuesta, no un detalle
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS admin.aggregate_state (
    agregado     text PRIMARY KEY,
    refreshed_at timestamptz,
    duration_ms  int,
    rows_total   bigint,
    status       text        NOT NULL DEFAULT 'pendiente',
    error        text,
    CONSTRAINT as_status_chk CHECK (status IN ('pendiente', 'refrescando', 'ok', 'fallido'))
);

COMMENT ON TABLE admin.aggregate_state IS
  'Frescura y resultado del último refresco de cada agregado. Si un refresco '
  'falla, la API devuelve AGREGADO_NO_DISPONIBLE en lugar de servir un dato viejo '
  'como si fuera actual.';

-- -----------------------------------------------------------------------------
-- Agregados
-- -----------------------------------------------------------------------------
-- Una fila por cliente: alimenta §18.16, §18.17, §18.18 y §18.19.
CREATE TABLE IF NOT EXISTS admin.agg_customer_state (
    tenant_id          text PRIMARY KEY,
    razon_social       text,
    despliegue         text,
    idioma             text,
    fabrica_activa     boolean,
    alta_el            timestamptz,
    eliminado_en       timestamptz,
    plan_codigo        text,
    plan_nombre        text,
    suscripcion_estado text,
    inicia_el          date,
    renueva_el         date,
    finaliza_el        date,
    lineas_contratadas int,
    lineas_activas     int,
    loc_mes            int,
    usuarios_activos   int,
    usuarios_total     int,
    integraciones      int,
    docs_onboarding    int,
    tickets_abiertos   int,
    ultima_actividad   timestamptz,
    importe_mes        numeric(12,2),
    moneda             text
);

-- Consumo por cliente y ciclo: alimenta §18.21 y el histórico de §18.18.
CREATE TABLE IF NOT EXISTS admin.agg_usage_cycle (
    tenant_id      text NOT NULL,
    ciclo          text NOT NULL,
    loc_consumidas int  NOT NULL DEFAULT 0,
    umbral         int,
    cuota_pct      numeric(6,2),
    tokens_in      bigint NOT NULL DEFAULT 0,
    tokens_out     bigint NOT NULL DEFAULT 0,
    tokens_flash   bigint NOT NULL DEFAULT 0,
    tokens_pro     bigint NOT NULL DEFAULT 0,
    tokens_fable   bigint NOT NULL DEFAULT 0,
    coste          numeric(14,2) NOT NULL DEFAULT 0,
    moneda         text,
    PRIMARY KEY (tenant_id, ciclo)
);

CREATE INDEX IF NOT EXISTS agg_usage_ciclo_ix ON admin.agg_usage_cycle (ciclo);

-- Serie diaria por tier y modelo: alimenta §18.21 agrupado por día y §18.26.
CREATE TABLE IF NOT EXISTS admin.agg_tokens_daily (
    dia          date   NOT NULL,
    tenant_id    text   NOT NULL,
    tier         text   NOT NULL,
    modelo       text   NOT NULL,
    etapa        text,
    invocaciones bigint NOT NULL DEFAULT 0,
    tokens_in    bigint NOT NULL DEFAULT 0,
    tokens_out   bigint NOT NULL DEFAULT 0,
    duracion_p50 int,
    duracion_p95 int,
    errores      bigint NOT NULL DEFAULT 0,
    coste        numeric(14,2) NOT NULL DEFAULT 0,
    PRIMARY KEY (dia, tenant_id, tier, modelo, etapa)
);

CREATE INDEX IF NOT EXISTS agg_tokens_dia_ix   ON admin.agg_tokens_daily (dia DESC);
CREATE INDEX IF NOT EXISTS agg_tokens_modelo_ix ON admin.agg_tokens_daily (modelo, dia DESC);

-- Serie diaria del pipeline: alimenta el bloque `pipeline` de §18.16.
CREATE TABLE IF NOT EXISTS admin.agg_pipeline_daily (
    dia                 date   NOT NULL PRIMARY KEY,
    tickets_creados     int    NOT NULL DEFAULT 0,
    tickets_entregados  int    NOT NULL DEFAULT 0,
    tiempo_e2e_p50_h    numeric(8,2),
    tiempo_e2e_p95_h    numeric(8,2),
    escalados_humano    int    NOT NULL DEFAULT 0,
    jobs_completados    int    NOT NULL DEFAULT 0
);

-- Solicitudes de cambio de plan pendientes: alimenta §18.20.
CREATE TABLE IF NOT EXISTS admin.agg_upgrade_requests (
    solicitud_id  text PRIMARY KEY,
    tenant_id     text NOT NULL,
    razon_social  text,
    plan_actual   text,
    plan_deseado  text,
    urgente       boolean,
    estado        text,
    comentario    text,
    solicitado_el timestamptz,
    cuota_uso_pct numeric(6,2)
);

CREATE INDEX IF NOT EXISTS agg_upg_estado_ix
    ON admin.agg_upgrade_requests (estado, solicitado_el);

-- -----------------------------------------------------------------------------
-- Privilegios: el rol de agregación escribe; el de lectura lee
-- -----------------------------------------------------------------------------
GRANT SELECT, INSERT, UPDATE, DELETE ON
    admin.agg_customer_state, admin.agg_usage_cycle, admin.agg_tokens_daily,
    admin.agg_pipeline_daily, admin.agg_upgrade_requests, admin.aggregate_state
    TO kallicode_admin_agg;
GRANT SELECT ON admin.plan_prices, admin.token_rates TO kallicode_admin_agg;

-- El rol de agregación necesita las mismas columnas del inventario que el de
-- lectura: se derivan de la misma fuente para que no puedan divergir.
DO $$
DECLARE
    r record;
BEGIN
    FOR r IN SELECT table_name, string_agg(quote_ident(column_name), ', ') AS cols
             FROM admin.access_inventory WHERE table_name LIKE 'core.%'
             GROUP BY table_name
    LOOP
        EXECUTE format('GRANT SELECT (%s) ON %s TO kallicode_admin_agg',
                       r.cols, r.table_name);
    END LOOP;
END $$;

-- Y política de lectura cross-tenant, igual que para el rol de lectura.
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
        EXECUTE format('DROP POLICY IF EXISTS admin_agg_select ON %s', t);
        EXECUTE format(
            'CREATE POLICY admin_agg_select ON %s FOR SELECT '
            'TO kallicode_admin_agg USING (true)', t);
    END LOOP;
END $$;

GRANT SELECT ON
    admin.agg_customer_state, admin.agg_usage_cycle, admin.agg_tokens_daily,
    admin.agg_pipeline_daily, admin.agg_upgrade_requests, admin.aggregate_state,
    admin.plan_prices, admin.token_rates
    TO kallicode_admin_ro;

-- -----------------------------------------------------------------------------
-- Funciones de refresco (SECURITY DEFINER, propiedad del rol de agregación)
-- -----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION admin.refresh_customer_state() RETURNS bigint AS $$
DECLARE
    n bigint;
BEGIN
    DELETE FROM admin.agg_customer_state;
    INSERT INTO admin.agg_customer_state
    SELECT o.id, o.nombre, o.despliegue, o.idioma, o.fabrica_activa,
           o.creado_en, o.eliminado_en,
           s.plan_codigo, p.nombre, s.estado, s.inicia_el, s.renueva_el,
           s.finaliza_el, p.lineas,
           (SELECT count(*) FROM core.production_lines pl
             WHERE pl.tenant_id = o.id AND pl.estado = 'ocupada'),
           p.loc_mes,
           (SELECT count(*) FROM core.users u
             WHERE u.tenant_id = o.id AND u.estado = 'activo'),
           (SELECT count(*) FROM core.users u WHERE u.tenant_id = o.id),
           (SELECT count(*) FROM core.connections c
             WHERE c.tenant_id = o.id AND c.estado = 'activa'),
           (SELECT count(*) FROM core.onboarding_documents d
             WHERE d.tenant_id = o.id),
           (SELECT count(*) FROM core.tickets t
             WHERE t.tenant_id = o.id AND t.cerrado_en IS NULL
               AND t.etapa NOT IN ('cancelado', 'cerrado_duplicado')),
           greatest(
             (SELECT max(t.creado_en) FROM core.tickets t WHERE t.tenant_id = o.id),
             (SELECT max(j.actualizado_en) FROM core.jobs j WHERE j.tenant_id = o.id)),
           pr.importe_mes, pr.moneda
    FROM core.organizations o
    LEFT JOIN core.subscriptions s
           ON s.tenant_id = o.id AND s.estado <> 'finalizada'
    LEFT JOIN core.plans p ON p.codigo = s.plan_codigo
    LEFT JOIN LATERAL (
        SELECT importe_mes, moneda FROM admin.plan_prices pp
        WHERE pp.plan_codigo = s.plan_codigo AND pp.vigente_desde <= current_date
        ORDER BY pp.vigente_desde DESC LIMIT 1) pr ON true;
    SELECT count(*) INTO n FROM admin.agg_customer_state;
    RETURN n;
END $$ LANGUAGE plpgsql SECURITY DEFINER SET search_path = admin, core, pg_temp;

ALTER FUNCTION admin.refresh_customer_state() OWNER TO kallicode_admin_agg;

CREATE OR REPLACE FUNCTION admin.refresh_usage_cycle(p_ciclos int DEFAULT 13)
RETURNS bigint AS $$
DECLARE
    n bigint;
    desde date := (date_trunc('month', current_date)
                   - make_interval(months => p_ciclos - 1))::date;
BEGIN
    DELETE FROM admin.agg_usage_cycle
     WHERE to_date(ciclo || '-01', 'YYYY-MM-DD') >= desde;

    INSERT INTO admin.agg_usage_cycle
        (tenant_id, ciclo, loc_consumidas, umbral, cuota_pct,
         tokens_in, tokens_out, tokens_flash, tokens_pro, tokens_fable,
         coste, moneda)
    SELECT c.tenant_id, c.ciclo, c.loc_consumidas, c.umbral,
           CASE WHEN coalesce(c.umbral, 0) > 0
                THEN round(100.0 * c.loc_consumidas / c.umbral, 2) END,
           coalesce(t.tin, 0), coalesce(t.tout, 0),
           coalesce(t.flash, 0), coalesce(t.pro, 0), coalesce(t.fable, 0),
           coalesce(t.coste, 0), coalesce(t.moneda, 'EUR')
    FROM core.usage_cycles c
    LEFT JOIN LATERAL (
        SELECT sum(ut.tokens_in) AS tin, sum(ut.tokens_out) AS tout,
               sum(CASE WHEN ut.tier = 'flash'
                        THEN ut.tokens_in + ut.tokens_out END) AS flash,
               sum(CASE WHEN ut.tier = 'pro'
                        THEN ut.tokens_in + ut.tokens_out END) AS pro,
               -- fable se agrega por separado: su coste no es comparable con pro
               sum(CASE WHEN ut.tier = 'fable'
                        THEN ut.tokens_in + ut.tokens_out END) AS fable,
               sum((ut.tokens_in / 1000.0) * coalesce(tr.precio_in, 0)
                 + (ut.tokens_out / 1000.0) * coalesce(tr.precio_out, 0)) AS coste,
               max(tr.moneda) AS moneda
        FROM core.usage_tokens ut
        LEFT JOIN LATERAL (
            SELECT precio_in, precio_out, moneda FROM admin.token_rates r
            WHERE r.tier = ut.tier AND r.modelo IN (ut.modelo, '*')
              AND r.vigente_desde <= ut.creado_en::date
            ORDER BY (r.modelo = ut.modelo) DESC, r.vigente_desde DESC
            LIMIT 1) tr ON true
        WHERE ut.tenant_id = c.tenant_id
          AND to_char(ut.creado_en, 'YYYY-MM') = c.ciclo) t ON true
    WHERE to_date(c.ciclo || '-01', 'YYYY-MM-DD') >= desde;

    SELECT count(*) INTO n FROM admin.agg_usage_cycle;
    RETURN n;
END $$ LANGUAGE plpgsql SECURITY DEFINER SET search_path = admin, core, pg_temp;

ALTER FUNCTION admin.refresh_usage_cycle(int) OWNER TO kallicode_admin_agg;

CREATE OR REPLACE FUNCTION admin.refresh_tokens_daily(p_dias int DEFAULT 35)
RETURNS bigint AS $$
DECLARE
    n bigint;
    desde date := current_date - p_dias;
BEGIN
    DELETE FROM admin.agg_tokens_daily WHERE dia >= desde;

    INSERT INTO admin.agg_tokens_daily
        (dia, tenant_id, tier, modelo, etapa, invocaciones, tokens_in,
         tokens_out, duracion_p50, duracion_p95, errores, coste)
    SELECT s.creado_en::date, s.tenant_id, s.tier, s.modelo,
           coalesce(s.etapa, 'sin_etapa'),
           count(*), sum(s.tokens_in), sum(s.tokens_out),
           percentile_disc(0.5) WITHIN GROUP (ORDER BY s.duracion_ms)::int,
           percentile_disc(0.95) WITHIN GROUP (ORDER BY s.duracion_ms)::int,
           count(*) FILTER (WHERE s.validacion IS DISTINCT FROM 'ok'),
           sum((s.tokens_in / 1000.0) * coalesce(tr.precio_in, 0)
             + (s.tokens_out / 1000.0) * coalesce(tr.precio_out, 0))
    FROM core.llm_steps s
    LEFT JOIN LATERAL (
        SELECT precio_in, precio_out FROM admin.token_rates r
        WHERE r.tier = s.tier AND r.modelo IN (s.modelo, '*')
          AND r.vigente_desde <= s.creado_en::date
        ORDER BY (r.modelo = s.modelo) DESC, r.vigente_desde DESC
        LIMIT 1) tr ON true
    WHERE s.creado_en::date >= desde
    GROUP BY 1, 2, 3, 4, 5;

    SELECT count(*) INTO n FROM admin.agg_tokens_daily;
    RETURN n;
END $$ LANGUAGE plpgsql SECURITY DEFINER SET search_path = admin, core, pg_temp;

ALTER FUNCTION admin.refresh_tokens_daily(int) OWNER TO kallicode_admin_agg;

CREATE OR REPLACE FUNCTION admin.refresh_pipeline_daily(p_dias int DEFAULT 95)
RETURNS bigint AS $$
DECLARE
    n bigint;
    desde date := current_date - p_dias;
BEGIN
    DELETE FROM admin.agg_pipeline_daily WHERE dia >= desde;

    INSERT INTO admin.agg_pipeline_daily
        (dia, tickets_creados, tickets_entregados, tiempo_e2e_p50_h,
         tiempo_e2e_p95_h, escalados_humano, jobs_completados)
    SELECT d.dia,
           coalesce(cr.n, 0), coalesce(en.n, 0), en.p50, en.p95,
           coalesce(es.n, 0), coalesce(jc.n, 0)
    FROM generate_series(desde::timestamp, current_date::timestamp, interval '1 day') AS d(dia)
    LEFT JOIN LATERAL (
        SELECT count(*) AS n FROM core.tickets t
        WHERE t.creado_en::date = d.dia) cr ON true
    LEFT JOIN LATERAL (
        SELECT count(*) AS n,
               round(percentile_disc(0.5) WITHIN GROUP (
                   ORDER BY extract(epoch FROM t.cerrado_en - t.creado_en))
                   / 3600.0, 2) AS p50,
               round(percentile_disc(0.95) WITHIN GROUP (
                   ORDER BY extract(epoch FROM t.cerrado_en - t.creado_en))
                   / 3600.0, 2) AS p95
        FROM core.tickets t
        WHERE t.cerrado_en::date = d.dia AND t.etapa = 'produccion') en ON true
    LEFT JOIN LATERAL (
        SELECT count(*) AS n FROM core.job_transitions jt
        WHERE jt.creado_en::date = d.dia
          AND jt.a_estado = 'escalado_humano') es ON true
    LEFT JOIN LATERAL (
        SELECT count(*) AS n FROM core.jobs j
        WHERE j.terminado_en::date = d.dia) jc ON true;

    SELECT count(*) INTO n FROM admin.agg_pipeline_daily;
    RETURN n;
END $$ LANGUAGE plpgsql SECURITY DEFINER SET search_path = admin, core, pg_temp;

ALTER FUNCTION admin.refresh_pipeline_daily(int) OWNER TO kallicode_admin_agg;

CREATE OR REPLACE FUNCTION admin.refresh_upgrade_requests() RETURNS bigint AS $$
DECLARE
    n bigint;
BEGIN
    DELETE FROM admin.agg_upgrade_requests;
    INSERT INTO admin.agg_upgrade_requests
    SELECT u.id, u.tenant_id, o.nombre, s.plan_codigo, u.plan_deseado,
           u.urgente, u.estado, u.comentario, u.creado_en,
           (SELECT cuota_pct FROM admin.agg_usage_cycle c
             WHERE c.tenant_id = u.tenant_id
               AND c.ciclo = to_char(u.creado_en, 'YYYY-MM'))
    FROM core.upgrade_requests u
    JOIN core.organizations o ON o.id = u.tenant_id
    LEFT JOIN core.subscriptions s
           ON s.tenant_id = u.tenant_id AND s.estado <> 'finalizada';
    SELECT count(*) INTO n FROM admin.agg_upgrade_requests;
    RETURN n;
END $$ LANGUAGE plpgsql SECURITY DEFINER SET search_path = admin, core, pg_temp;

ALTER FUNCTION admin.refresh_upgrade_requests() OWNER TO kallicode_admin_agg;

-- Orquestador: refresca todo y registra frescura y resultado por agregado.
CREATE OR REPLACE FUNCTION admin.refresh_all() RETURNS TABLE (
    agregado text, filas bigint, ms int, estado text) AS $$
DECLARE
    nombres text[] := ARRAY['customer_state', 'usage_cycle', 'tokens_daily',
                            'pipeline_daily', 'upgrade_requests'];
    nm text;
    t0 timestamptz;
    n  bigint;
BEGIN
    FOREACH nm IN ARRAY nombres LOOP
        t0 := clock_timestamp();
        INSERT INTO admin.aggregate_state (agregado, status)
             VALUES (nm, 'refrescando')
        ON CONFLICT (agregado) DO UPDATE SET status = 'refrescando', error = NULL;
        BEGIN
            EXECUTE format('SELECT admin.refresh_%s()', nm) INTO n;
            UPDATE admin.aggregate_state
               SET refreshed_at = now(), rows_total = n, status = 'ok',
                   error = NULL,
                   duration_ms = extract(milliseconds FROM clock_timestamp() - t0)::int
             WHERE agregado = nm;
            RETURN QUERY SELECT nm, n,
                extract(milliseconds FROM clock_timestamp() - t0)::int, 'ok';
        EXCEPTION WHEN OTHERS THEN
            -- Un agregado que falla no impide refrescar los demás, y su fallo
            -- queda registrado para que la API devuelva 503 en lugar de un dato
            -- viejo presentado como actual.
            UPDATE admin.aggregate_state
               SET status = 'fallido', error = SQLERRM,
                   duration_ms = extract(milliseconds FROM clock_timestamp() - t0)::int
             WHERE agregado = nm;
            RETURN QUERY SELECT nm, 0::bigint,
                extract(milliseconds FROM clock_timestamp() - t0)::int,
                'fallido';
        END;
    END LOOP;
END $$ LANGUAGE plpgsql SECURITY DEFINER SET search_path = admin, core, pg_temp;

ALTER FUNCTION admin.refresh_all() OWNER TO kallicode_admin_agg;

GRANT EXECUTE ON FUNCTION admin.refresh_all() TO kallicode_admin_app;

-- -----------------------------------------------------------------------------
-- Semilla provisional: pendiente de ratificación del Product Owner
-- -----------------------------------------------------------------------------
INSERT INTO admin.plan_prices (plan_codigo, importe_mes, moneda) VALUES
    ('starter', 900.00, 'EUR'),
    ('growth', 2900.00, 'EUR'),
    ('enterprise', 9500.00, 'EUR')
ON CONFLICT DO NOTHING;

INSERT INTO admin.token_rates (tier, modelo, precio_in, precio_out) VALUES
    ('flash', '*', 0.000150, 0.000600),
    ('pro',   '*', 0.001200, 0.004800),
    ('fable', '*', 0.012000, 0.060000)
ON CONFLICT DO NOTHING;

INSERT INTO admin.aggregate_state (agregado) VALUES
    ('customer_state'), ('usage_cycle'), ('tokens_daily'),
    ('pipeline_daily'), ('upgrade_requests')
ON CONFLICT DO NOTHING;

COMMIT;
