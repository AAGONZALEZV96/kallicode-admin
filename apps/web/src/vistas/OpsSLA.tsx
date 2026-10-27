import React, { useState, useCallback } from "react";
import { useLiveRefresh } from "../hooks/useLiveRefresh";
import { ControlesLiveRefresh } from "../componentes/ControlesLiveRefresh";
import { Tabla, TablaEncabezado, TablaCuerpo, TablaFila, TablaCelda, TablaCeldaEncabezado } from "../componentes/Tabla";
import { Badge } from "../componentes/Badge";

export interface SLACaso {
  job_id: string;
  tenant_id: string;
  plan: string;
  objetivo_h: number;
  transcurrido_h: number;
  resultado: "dentro" | "incumplido" | "en_riesgo";
}

export interface OpsSLADatos {
  resumen: {
    cumplimiento_pct: number;
    incumplidos: number;
    en_riesgo: number;
    total_evaluados: number;
  };
  casos: SLACaso[];
}

export interface OpsSLAProps {
  obtenerDatos?: () => Promise<OpsSLADatos>;
  datosIniciales?: OpsSLADatos | null;
}

const DATOS_DEFECTO: OpsSLADatos = {
  resumen: {
    cumplimiento_pct: 98.4,
    incumplidos: 2,
    en_riesgo: 4,
    total_evaluados: 125,
  },
  casos: [
    {
      job_id: "job_991823",
      tenant_id: "org_••••••••",
      plan: "enterprise",
      objetivo_h: 2.0,
      transcurrido_h: 1.4,
      resultado: "dentro",
    },
    {
      job_id: "job_991824",
      tenant_id: "org_••••••••",
      plan: "growth",
      objetivo_h: 4.0,
      transcurrido_h: 3.8,
      resultado: "en_riesgo",
    },
    {
      job_id: "job_991810",
      tenant_id: "org_••••••••",
      plan: "starter",
      objetivo_h: 8.0,
      transcurrido_h: 9.2,
      resultado: "incumplido",
    },
  ],
};

export const OpsSLA: React.FC<OpsSLAProps> = ({
  obtenerDatos,
  datosIniciales = DATOS_DEFECTO,
}) => {
  const [datos, setDatos] = useState<OpsSLADatos | null>(datosIniciales);
  const [errorCarga, setErrorCarga] = useState<string | null>(null);

  const cargarTelemetria = useCallback(async () => {
    try {
      if (obtenerDatos) {
        const respuesta = await obtenerDatos();
        setDatos(respuesta);
      }
      setErrorCarga(null);
    } catch (err) {
      setErrorCarga(err instanceof Error ? err.message : "Error al consultar SLA");
    }
  }, [obtenerDatos]);

  const liveRefresh = useLiveRefresh({
    intervaloMs: 15_000,
    alRefrescar: cargarTelemetria,
    pausarEnSegundoPlano: true,
    pausarEnPerdidaFoco: true,
  });

  if (!datos) return null;

  return (
    <div className="view ops-sla" style={{ display: "flex", flexDirection: "column", gap: "20px" }}>
      {/* Cabecera y controles de refresco en vivo */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: "12px" }}>
        <div>
          <h1 style={{ fontSize: "1.25rem", fontWeight: 700, margin: 0 }}>
            Cumplimiento de SLA e Incidentes de Servicio
          </h1>
          <p style={{ fontSize: "0.8125rem", color: "var(--muted)", margin: "4px 0 0 0" }}>
            Monitoreo en vivo de acuerdos de nivel de servicio y reloj de incidencias (§18.27, §18.28)
          </p>
        </div>

        <ControlesLiveRefresh hook={liveRefresh} />
      </div>

      {/* Resumen Global */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))", gap: "14px" }}>
        <div className="card">
          <div style={{ fontSize: "12px", color: "var(--muted)" }}>Cumplimiento Global</div>
          <div style={{ fontSize: "24px", fontWeight: 700, color: "var(--good)" }}>
            {datos.resumen.cumplimiento_pct.toFixed(1)}%
          </div>
        </div>
        <div className="card">
          <div style={{ fontSize: "12px", color: "var(--muted)" }}>Casos en Riesgo (alerta)</div>
          <div style={{ fontSize: "24px", fontWeight: 700, color: "var(--warn)" }}>
            {datos.resumen.en_riesgo}
          </div>
        </div>
        <div className="card">
          <div style={{ fontSize: "12px", color: "var(--muted)" }}>Incidentes Incumplidos</div>
          <div style={{ fontSize: "24px", fontWeight: 700, color: "var(--bad)" }}>
            {datos.resumen.incumplidos}
          </div>
        </div>
        <div className="card">
          <div style={{ fontSize: "12px", color: "var(--muted)" }}>Total Evaluados</div>
          <div style={{ fontSize: "24px", fontWeight: 700, color: "var(--text)" }}>
            {datos.resumen.total_evaluados}
          </div>
        </div>
      </div>

      {/* Tabla de Casos Activos */}
      <div className="card">
        <h3 style={{ fontSize: "14px", fontWeight: 650, marginBottom: "12px" }}>
          Casos de SLA en Curso y Reloj de Ejecución
        </h3>
        <Tabla densidad="alta">
          <TablaEncabezado>
            <TablaFila>
              <TablaCeldaEncabezado>Job ID</TablaCeldaEncabezado>
              <TablaCeldaEncabezado>Cliente (Tenant)</TablaCeldaEncabezado>
              <TablaCeldaEncabezado>Plan</TablaCeldaEncabezado>
              <TablaCeldaEncabezado numerico>Objetivo SLA</TablaCeldaEncabezado>
              <TablaCeldaEncabezado numerico>Transcurrido</TablaCeldaEncabezado>
              <TablaCeldaEncabezado>Resultado</TablaCeldaEncabezado>
            </TablaFila>
          </TablaEncabezado>
          <TablaCuerpo>
            {datos.casos.map((c) => (
              <TablaFila key={c.job_id}>
                <TablaCelda>
                  <code className="mono">{c.job_id}</code>
                </TablaCelda>
                <TablaCelda>
                  <span className="mono" style={{ color: "var(--muted)" }}>
                    {c.tenant_id}
                  </span>
                </TablaCelda>
                <TablaCelda>
                  <span style={{ textTransform: "capitalize", fontWeight: 500 }}>{c.plan}</span>
                </TablaCelda>
                <TablaCelda numerico>{c.objetivo_h.toFixed(1)} h</TablaCelda>
                <TablaCelda numerico>{c.transcurrido_h.toFixed(1)} h</TablaCelda>
                <TablaCelda>
                  <Badge
                    variante={
                      c.resultado === "dentro"
                        ? "good"
                        : c.resultado === "en_riesgo"
                        ? "warn"
                        : "bad"
                    }
                    punto
                  >
                    {c.resultado.toUpperCase()}
                  </Badge>
                </TablaCelda>
              </TablaFila>
            ))}
          </TablaCuerpo>
        </Tabla>
      </div>

      {errorCarga && (
        <div style={{ color: "var(--error)", fontSize: "12px" }}>
          Error: {errorCarga}
        </div>
      )}
    </div>
  );
};
