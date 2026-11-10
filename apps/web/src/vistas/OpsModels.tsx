import React, { useState, useCallback } from "react";
import { useLiveRefresh } from "../hooks/useLiveRefresh";
import { ControlesLiveRefresh } from "../componentes/ControlesLiveRefresh";
import { Tabla, TablaEncabezado, TablaCuerpo, TablaFila, TablaCelda, TablaCeldaEncabezado } from "../componentes/Tabla";
import { Badge } from "../componentes/Badge";

export interface ModeloMetrica {
  proveedor: string;
  modelo: string;
  tier: "flash" | "pro" | "fable";
  disponibilidad_pct: number;
  latencia_p95_ms: number;
  tasa_error_pct: number;
}

export interface OpsModelsDatos {
  modelos: ModeloMetrica[];
  escalados: {
    flash_a_pro: number;
    pro_a_fable: number;
    a_humano: number;
  };
  servicios: {
    postgres: boolean;
    blob: boolean;
    telemetria: boolean;
    agregados: boolean;
  };
}

export interface OpsModelsProps {
  obtenerDatos?: () => Promise<OpsModelsDatos>;
  datosIniciales?: OpsModelsDatos | null;
}

const DATOS_DEFECTO: OpsModelsDatos = {
  modelos: [
    {
      proveedor: "Google Gemini",
      modelo: "gemini-2.5-flash",
      tier: "flash",
      disponibilidad_pct: 99.98,
      latencia_p95_ms: 420,
      tasa_error_pct: 0.05,
    },
    {
      proveedor: "Google Gemini",
      modelo: "gemini-2.5-pro",
      tier: "pro",
      disponibilidad_pct: 99.85,
      latencia_p95_ms: 1250,
      tasa_error_pct: 0.12,
    },
    {
      proveedor: "Anthropic",
      modelo: "claude-3-7-sonnet",
      tier: "fable",
      disponibilidad_pct: 99.92,
      latencia_p95_ms: 1840,
      tasa_error_pct: 0.08,
    },
  ],
  escalados: {
    flash_a_pro: 142,
    pro_a_fable: 18,
    a_humano: 3,
  },
  servicios: {
    postgres: true,
    blob: true,
    telemetria: true,
    agregados: true,
  },
};

export const OpsModels: React.FC<OpsModelsProps> = ({
  obtenerDatos,
  datosIniciales = DATOS_DEFECTO,
}) => {
  const [datos, setDatos] = useState<OpsModelsDatos | null>(datosIniciales);
  const [errorCarga, setErrorCarga] = useState<string | null>(null);

  const cargarTelemetria = useCallback(async () => {
    try {
      if (obtenerDatos) {
        const respuesta = await obtenerDatos();
        setDatos(respuesta);
      }
      setErrorCarga(null);
    } catch (err) {
      setErrorCarga(err instanceof Error ? err.message : "Error al consultar telemetría de modelos");
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
    <div className="view ops-models" style={{ display: "flex", flexDirection: "column", gap: "20px" }}>
      {/* Cabecera y controles de refresco en vivo */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: "12px" }}>
        <div>
          <h1 style={{ fontSize: "1.25rem", fontWeight: 700, margin: 0 }}>
            Métricas de Modelos LLM y Servicios Core
          </h1>
          <p style={{ fontSize: "0.8125rem", color: "var(--muted)", margin: "4px 0 0 0" }}>
            Disponibilidad, latencia, tasa de error y escalado de tiers (§18.26, §18.31)
          </p>
        </div>

        <ControlesLiveRefresh hook={liveRefresh} />
      </div>

      {/* Servicios Core */}
      <div className="card">
        <h3 style={{ fontSize: "14px", fontWeight: 650, marginBottom: "12px" }}>
          Salud de Servicios y Dependencias Core
        </h3>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: "12px" }}>
          {Object.entries(datos.servicios).map(([servicio, ok]) => (
            <div
              key={servicio}
              style={{
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
                padding: "10px 14px",
                backgroundColor: "var(--surface2)",
                borderRadius: "var(--radius-md)",
              }}
            >
              <span style={{ textTransform: "capitalize", fontSize: "13px" }}>{servicio}</span>
              <Badge variante={ok ? "good" : "bad"} punto>
                {ok ? "OPERATIVO" : "DEGRADADO"}
              </Badge>
            </div>
          ))}
        </div>
      </div>

      {/* Tarjetas de Escalados */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))", gap: "14px" }}>
        <div className="card">
          <div style={{ fontSize: "12px", color: "var(--muted)" }}>Escalados Flash → Pro</div>
          <div style={{ fontSize: "24px", fontWeight: 700, color: "var(--accent)" }}>
            {datos.escalados.flash_a_pro}
          </div>
        </div>
        <div className="card">
          <div style={{ fontSize: "12px", color: "var(--muted)" }}>Escalados Pro → Fable</div>
          <div style={{ fontSize: "24px", fontWeight: 700, color: "var(--purple)" }}>
            {datos.escalados.pro_a_fable}
          </div>
        </div>
        <div className="card">
          <div style={{ fontSize: "12px", color: "var(--muted)" }}>Escalados a Humano (Fallback)</div>
          <div style={{ fontSize: "24px", fontWeight: 700, color: "var(--warn)" }}>
            {datos.escalados.a_humano}
          </div>
        </div>
      </div>

      {/* Tabla de Rendimiento de Modelos LLM */}
      <div className="card">
        <h3 style={{ fontSize: "14px", fontWeight: 650, marginBottom: "12px" }}>
          Rendimiento por Modelo y Tier
        </h3>
        <Tabla densidad="alta">
          <TablaEncabezado>
            <TablaFila>
              <TablaCeldaEncabezado>Proveedor</TablaCeldaEncabezado>
              <TablaCeldaEncabezado>Modelo</TablaCeldaEncabezado>
              <TablaCeldaEncabezado>Tier</TablaCeldaEncabezado>
              <TablaCeldaEncabezado numerico>Disponibilidad</TablaCeldaEncabezado>
              <TablaCeldaEncabezado numerico>Latencia p95</TablaCeldaEncabezado>
              <TablaCeldaEncabezado numerico>Tasa de Error</TablaCeldaEncabezado>
            </TablaFila>
          </TablaEncabezado>
          <TablaCuerpo>
            {datos.modelos.map((m) => (
              <TablaFila key={m.modelo}>
                <TablaCelda>{m.proveedor}</TablaCelda>
                <TablaCelda>
                  <code className="mono">{m.modelo}</code>
                </TablaCelda>
                <TablaCelda>
                  <Badge
                    variante={
                      m.tier === "fable" ? "enmascarado" : m.tier === "pro" ? "accent" : "neutro"
                    }
                  >
                    {m.tier.toUpperCase()}
                  </Badge>
                </TablaCelda>
                <TablaCelda numerico>
                  <span style={{ color: m.disponibilidad_pct >= 99.9 ? "var(--good)" : "var(--warn)", fontWeight: 600 }}>
                    {m.disponibilidad_pct.toFixed(2)}%
                  </span>
                </TablaCelda>
                <TablaCelda numerico>{m.latencia_p95_ms} ms</TablaCelda>
                <TablaCelda numerico>{m.tasa_error_pct.toFixed(2)}%</TablaCelda>
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
