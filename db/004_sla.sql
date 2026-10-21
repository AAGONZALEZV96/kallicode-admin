-- =============================================================================
-- KalliCode · Consola de Administración
-- Migración 004 — acuerdos de nivel de servicio
--
-- Resuelve la brecha ADM-G07, que no era técnica sino de producto: no existía
-- ninguna definición de nivel de servicio —ni objetivos por plan, ni relojes, ni
-- tratamiento de las pausas— y por tanto la pantalla no era construible.
--
-- La decisión que este fichero materializa, y que el Product Owner ratifica, es
-- que el reloj NO cuenta el tiempo en que la pelota está en el tejado del cliente
-- ni el tiempo de indisponibilidad ajena. Resolverlo al contrario —contando el
-- tiempo que un cliente tarda en firmar un gate— produciría incumplimientos
-- ficticios el primer mes y destruiría la confianza en la consola entera.
--
-- Los estados de pausa son configurables y no constantes en el código, para que
-- consola, alertas e informes usen el mismo criterio y este se pueda ajustar sin
-- desplegar.
-- =============================================================================

BEGIN;

-- -----------------------------------------------------------------------------
-- Objetivos por plan y etapa
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS admin.sla_targets (
    plan_codigo   text NOT NULL REFERENCES core.plans(codigo),
    etapa         text NOT NULL,              -- '*' = objetivo de extremo a extremo
    objetivo_h    numeric(8,2) NOT NULL,
    riesgo_pct    numeric(5,2) NOT NULL DEFAULT 80.00,
    vigente_desde date NOT NULL DEFAULT current_date,
    PRIMARY KEY (plan_codigo, etapa, vigente_desde),
    CONSTRAINT slat_obj_chk    CHECK (objetivo_h > 0),
    CONSTRAINT slat_riesgo_chk CHECK (riesgo_pct BETWEEN 1 AND 100),
    CONSTRAINT slat_etapa_chk  CHECK (etapa IN ('*', 'triage', 'design', 'build',
                                                'qa', 'security', 'deploy'))
);

COMMENT ON TABLE admin.sla_targets IS
  'Objetivo de nivel de servicio por plan y etapa. La etapa «*» es el objetivo de '
  'extremo a extremo. Un plan sin objetivos hace que §18.27 devuelva '
  'SLA_SIN_DEFINICION en lugar de calcular sobre un supuesto.';
COMMENT ON COLUMN admin.sla_targets.riesgo_pct IS
  'Porcentaje del objetivo a partir del cual un caso abierto se considera en '
  'riesgo. Sirve para avisar cuando aún se puede actuar.';

-- -----------------------------------------------------------------------------
-- Estados del job que pausan el reloj
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS admin.sla_pause_states (
    estado_job text PRIMARY KEY,
    motivo     text NOT NULL,
    activa     boolean NOT NULL DEFAULT true,
    nota       text
);

COMMENT ON TABLE admin.sla_pause_states IS
  'Estados de core.jobs durante los cuales el reloj de servicio no corre. Es la '
  'traducción de las reglas de pausa del ADR 003 y la única fuente: ni la consola '
  'ni las alertas codifican esta lista.';

INSERT INTO admin.sla_pause_states (estado_job, motivo, nota) VALUES
    ('gate1', 'espera_firma_cliente',
     'Gate 1: el cliente decide entre las alternativas de diseño.'),
    ('gate2', 'espera_firma_cliente',
     'Gate 2: el cliente revisa la evidencia de calidad.'),
    ('gate3', 'espera_firma_cliente',
     'Gate 3: el arquitecto autoriza el despliegue.'),
    ('escalado_humano', 'escalado_humano',
     'La fábrica ha escalado a un humano; el reloj de la fábrica se detiene.'),
    ('pausado_por_cuota', 'cuota_agotada',
     'El cliente ha agotado su cuota: la espera no es imputable al proveedor.')
ON CONFLICT (estado_job) DO NOTHING;

-- -----------------------------------------------------------------------------
-- Resultado por caso
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS admin.sla_cases (
    job_id        text PRIMARY KEY,
    tenant_id     text NOT NULL,
    ticket_id     text,
    ticket_numero text,
    plan_codigo   text,
    etapa_final   text,
    objetivo_h    numeric(8,2),
    bruto_h       numeric(10,2) NOT NULL,
    transcurrido_h numeric(10,2) NOT NULL,
    resultado     text NOT NULL,
    tramos        jsonb NOT NULL,
    reglas        text[] NOT NULL DEFAULT '{}',
    iniciado_en   timestamptz NOT NULL,
    terminado_en  timestamptz,
    calculado_en  timestamptz NOT NULL DEFAULT now(),

    CONSTRAINT slac_resultado_chk CHECK (resultado IN ('dentro', 'incumplido',
                                                       'en_curso', 'en_riesgo',
                                                       'sin_objetivo')),
    CONSTRAINT slac_horas_chk CHECK (transcurrido_h <= bruto_h + 0.01)
);

CREATE INDEX IF NOT EXISTS slac_tenant_ix ON admin.sla_cases (tenant_id, iniciado_en DESC);
CREATE INDEX IF NOT EXISTS slac_result_ix ON admin.sla_cases (resultado, iniciado_en DESC);
CREATE INDEX IF NOT EXISTS slac_ciclo_ix
    ON admin.sla_cases (iniciado_en, tenant_id);

COMMENT ON COLUMN admin.sla_cases.tramos IS
  'Desglose del reloj: [{inicio, fin, etapa, computa, causa_pausa}]. Es lo que '
  '§18.28 devuelve, y el requisito menos obvio de la pantalla: quien vea un '
  'incumplimiento tiene que poder explicar por qué el reloj contó lo que contó, '
  'porque será la primera pregunta del cliente.';

GRANT SELECT ON admin.sla_targets, admin.sla_pause_states, admin.sla_cases
    TO kallicode_admin_ro;
GRANT SELECT, INSERT, UPDATE, DELETE ON admin.sla_cases TO kallicode_admin_agg;
GRANT SELECT ON admin.sla_targets, admin.sla_pause_states TO kallicode_admin_agg;

-- -----------------------------------------------------------------------------
-- Cálculo del reloj de un caso
-- -----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION admin.compute_sla_case(p_job_id text)
RETURNS admin.sla_cases AS $$
DECLARE
    j            record;
    tr           record;
    fin_tramo    timestamptz;
    fin_caso     timestamptz;
    computa      boolean;
    causa        text;
    tramos       jsonb := '[]'::jsonb;
    reglas       text[] := '{}';
    bruto        numeric := 0;
    contado      numeric := 0;
    objetivo     numeric;
    plan_cod     text;
    res          text;
    salida       admin.sla_cases;
BEGIN
    SELECT jb.id, jb.tenant_id, jb.ticket_id, jb.estado, jb.creado_en,
           jb.terminado_en, tk.numero, tk.etapa
      INTO j
      FROM core.jobs jb
      LEFT JOIN core.tickets tk ON tk.id = jb.ticket_id
     WHERE jb.id = p_job_id;
    IF NOT FOUND THEN
        RETURN NULL;
    END IF;

    SELECT s.plan_codigo INTO plan_cod FROM core.subscriptions s
     WHERE s.tenant_id = j.tenant_id AND s.estado <> 'finalizada' LIMIT 1;

    SELECT t.objetivo_h INTO objetivo FROM admin.sla_targets t
     WHERE t.plan_codigo = plan_cod AND t.etapa = '*'
       AND t.vigente_desde <= j.creado_en::date
     ORDER BY t.vigente_desde DESC LIMIT 1;

    fin_caso := coalesce(j.terminado_en, now());

    -- Se recorren las transiciones en orden. Cada tramo va desde una transición
    -- hasta la siguiente, y su estado es el de destino de la primera.
    FOR tr IN
        SELECT jt.creado_en AS desde, jt.a_estado AS estado,
               lead(jt.creado_en) OVER (ORDER BY jt.creado_en, jt.id) AS hasta
          FROM core.job_transitions jt
         WHERE jt.job_id = p_job_id
         ORDER BY jt.creado_en, jt.id
    LOOP
        fin_tramo := coalesce(tr.hasta, fin_caso);
        IF fin_tramo <= tr.desde THEN
            CONTINUE;
        END IF;

        SELECT ps.motivo INTO causa FROM admin.sla_pause_states ps
         WHERE ps.estado_job = tr.estado AND ps.activa;
        computa := causa IS NULL;
        IF NOT computa AND NOT (causa = ANY(reglas)) THEN
            reglas := reglas || causa;
        END IF;

        bruto := bruto + extract(epoch FROM fin_tramo - tr.desde) / 3600.0;
        IF computa THEN
            contado := contado + extract(epoch FROM fin_tramo - tr.desde) / 3600.0;
        END IF;

        tramos := tramos || jsonb_build_object(
            'inicio', tr.desde, 'fin', fin_tramo, 'etapa', tr.estado,
            'computa', computa, 'causa_pausa', causa,
            'horas', round(extract(epoch FROM fin_tramo - tr.desde) / 3600.0, 3));
        causa := NULL;
    END LOOP;

    -- Sin transiciones registradas el caso no es evaluable: se cuenta el bruto
    -- para no perder la traza, pero el resultado lo declara.
    IF jsonb_array_length(tramos) = 0 THEN
        bruto := extract(epoch FROM fin_caso - j.creado_en) / 3600.0;
        contado := bruto;
    END IF;

    IF objetivo IS NULL THEN
        res := 'sin_objetivo';
    ELSIF j.terminado_en IS NULL THEN
        res := CASE WHEN contado > objetivo THEN 'incumplido'
                    WHEN contado >= objetivo * (
                        SELECT coalesce(max(riesgo_pct), 80) / 100.0
                          FROM admin.sla_targets
                         WHERE plan_codigo = plan_cod AND etapa = '*')
                    THEN 'en_riesgo' ELSE 'en_curso' END;
    ELSE
        res := CASE WHEN contado > objetivo THEN 'incumplido' ELSE 'dentro' END;
    END IF;

    INSERT INTO admin.sla_cases
        (job_id, tenant_id, ticket_id, ticket_numero, plan_codigo, etapa_final,
         objetivo_h, bruto_h, transcurrido_h, resultado, tramos, reglas,
         iniciado_en, terminado_en, calculado_en)
    VALUES (j.id, j.tenant_id, j.ticket_id, j.numero, plan_cod, j.etapa,
            objetivo, round(bruto, 2), round(contado, 2), res, tramos, reglas,
            j.creado_en, j.terminado_en, now())
    ON CONFLICT (job_id) DO UPDATE SET
        objetivo_h = excluded.objetivo_h, bruto_h = excluded.bruto_h,
        transcurrido_h = excluded.transcurrido_h, resultado = excluded.resultado,
        tramos = excluded.tramos, reglas = excluded.reglas,
        etapa_final = excluded.etapa_final, terminado_en = excluded.terminado_en,
        calculado_en = now()
    RETURNING * INTO salida;

    RETURN salida;
END $$ LANGUAGE plpgsql SECURITY DEFINER SET search_path = admin, core, pg_temp;

ALTER FUNCTION admin.compute_sla_case(text) OWNER TO kallicode_admin_agg;

COMMENT ON FUNCTION admin.compute_sla_case IS
  'Calcula el reloj de un caso a partir de core.job_transitions, aplicando las '
  'reglas de pausa. Es reproducible: el mismo caso cerrado devuelve siempre el '
  'mismo resultado, requisito de §18.27.';

-- Recalcula los casos de una ventana. Los cerrados no se recalculan salvo que se
-- fuerce, porque su resultado ya no puede cambiar.
CREATE OR REPLACE FUNCTION admin.refresh_sla(p_dias int DEFAULT 95,
                                             p_forzar boolean DEFAULT false)
RETURNS bigint AS $$
DECLARE
    r record;
    n bigint := 0;
BEGIN
    FOR r IN
        SELECT j.id FROM core.jobs j
         WHERE j.creado_en >= current_date - p_dias
           AND (p_forzar
                OR j.terminado_en IS NULL
                OR NOT EXISTS (SELECT 1 FROM admin.sla_cases c
                                WHERE c.job_id = j.id
                                  AND c.terminado_en IS NOT NULL))
    LOOP
        PERFORM admin.compute_sla_case(r.id);
        n := n + 1;
    END LOOP;

    INSERT INTO admin.aggregate_state (agregado, refreshed_at, rows_total, status)
         VALUES ('sla_cases', now(), n, 'ok')
    ON CONFLICT (agregado) DO UPDATE
        SET refreshed_at = now(), rows_total = n, status = 'ok', error = NULL;
    RETURN n;
END $$ LANGUAGE plpgsql SECURITY DEFINER SET search_path = admin, core, pg_temp;

ALTER FUNCTION admin.refresh_sla(int, boolean) OWNER TO kallicode_admin_agg;
GRANT EXECUTE ON FUNCTION admin.refresh_sla(int, boolean) TO kallicode_admin_app;

-- -----------------------------------------------------------------------------
-- Semilla provisional de objetivos: pendiente de ratificación del PO (ADR 003)
-- -----------------------------------------------------------------------------
INSERT INTO admin.sla_targets (plan_codigo, etapa, objetivo_h) VALUES
    ('starter',    '*', 72.00),
    ('growth',     '*', 24.00),
    ('enterprise', '*',  8.00)
ON CONFLICT DO NOTHING;

INSERT INTO admin.aggregate_state (agregado) VALUES ('sla_cases')
ON CONFLICT DO NOTHING;

COMMIT;
