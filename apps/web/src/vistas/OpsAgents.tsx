import React, { useState, useCallback } from "react";
import { useLiveRefresh } from "../hooks/useLiveRefresh";
import { ControlesLiveRefresh } from "../componentes/ControlesLiveRefresh";
import { Tabla, TablaEncabezado, TablaCuerpo, TablaFila, TablaCelda, TablaCeldaEncabezado } from "../componentes/Tabla";
import { Badge } from "../componentes/Badge";

export interface OpsAgentsDatos {
  telemetria: {
    disponible: boolean;
    antiguedad_s: number;
  };
  lineas: {
    activas: number;
    mantenimiento: number;
    libres: number;
  };
  etapas: Array<{
    nombre: string;
    agentes_total: number;
    agentes_ocupados: number;
    agentes_caidos: number;
  }>;
  colas: Array<{
    nombre: string;
    pendientes: number;
    antiguedad_max_s: number;
    estado: "normal" | "atencion" | "critico";
  }>;
}

export interface OpsAgentsProps {
  obtenerDatos?: () => Promise<OpsAgentsDatos>;
  datosIniciales?: OpsAgentsDatos | null;
}

const DATOS_DEFECTO: OpsAgentsDatos = {
  telemetria: { disponible: true, antiguedad_s: 4 },
  lineas: { activas: 12, mantenimiento: 1, libres: 5 },
  etapas: [
    { nombre: "triage", agentes_total: 4, agentes_ocupados: 2, agentes_caidos: 0 },
    { nombre: "design", agentes_total: 6, agentes_ocupados: 5, agentes_caidos: 0 },
    { nombre: "build", agentes_total: 10, agentes_ocupados: 8, agentes_caidos: 1 },
    { nombre: "qa", agentes_total: 5, agentes_ocupados: 3, agentes_caidos: 0 },
  ],
  colas: [
    { nombre: "cola_ingesta", pendientes: 24, antiguedad_max_s: 15, estado: "normal" },
    { nombre: "cola_generacion", pendientes: 78, antiguedad_max_s: 45, estado: "atencion" },
    { nombre: "dead_letter_queue", pendientes: 2, antiguedad_max_s: 120, estado: "critico" },
  ],
};

export const OpsAgents: React.FC<OpsAgentsProps> = ({
  obtenerDatos,
  datosIniciales = DATOS_DEFECTO,
}) => {
  const [datos, setDatos] = useState<OpsAgentsDatos | null>(datosIniciales);
  const [errorCarga, setErrorCarga] = useState<string | null>(null);

  // Callback de recarga que invoca el hook de polling inteligente
  const cargarTelemetria = useCallback(async () => {
    try {
      if (obtenerDatos) {
        const respuesta = await obtenerDatos();
        setDatos(respuesta);
      }
      setErrorCarga(null);
    } catch (err) {
      setErrorCarga(err instanceof Error ? err.message : "Error al consultar telemetría");
    }
  }, [obtenerDatos]);

  // Hook de refresco en vivo con presupuesto RL-4 y detección de visibilidad
  const liveRefresh = useLiveRefresh({
    intervaloMs: 15_000,
    alRefrescar: cargarTelemetria,
    pausarEnSegundoPlano: true,
    pausarEnPerdidaFoco: true,
  });

  const sinTelemetria = !datos || !datos.telemetria.disponible;

  return (
    <div className="view ops-agents" style={{ display: "flex", flexDirection: "column", gap: "20px" }}>
      {/* Cabecera y controles de refresco en vivo */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: "12px" }}>
        <div>
          <h1 style={{ fontSize: "1.25rem", fontWeight: 700, margin: 0 }}>
            Estado de Agentes y Colas de Producción
          </h1>
          <p style={{ fontSize: "0.8125rem", color: "var(--muted)", margin: "4px 0 0 0" }}>
            Supervisión técnica de la fábrica de software y telemetría de mensajería (§18.24, §18.25)
          </p>
        </div>

        <ControlesLiveRefresh hook={liveRefresh} />
      </div>

      {/* Regla Crítica: Si la telemetría no está disponible, mostrar banner y anular métricas */}
      {sinTelemetria ? (
        <div
          style={{
            backgroundColor: "var(--bad-bg)",
            border: "1px solid var(--bad)",
            color: "var(--bad)",
            padding: "16px",
            borderRadius: "var(--radius-md)",
            fontWeight: 600,
          }}
          data-testid="banner-sin-telemetria"
        >
          ⚠️ Sin telemetría disponible. El pipeline no está emitiendo eventos o el servicio de telemetría está inaccesible.
        </div>
      ) : (
        <>
          {/* Tarjetas de Resumen de Líneas */}
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))", gap: "14px" }}>
            <div className="card">
              <div style={{ fontSize: "12px", color: "var(--muted)" }}>Líneas Activas</div>
              <div style={{ fontSize: "24px", fontWeight: 700, color: "var(--good)" }}>
                {datos.lineas.activas}
              </div>
            </div>
            <div className="card">
              <div style={{ fontSize: "12px", color: "var(--muted)" }}>Líneas en Mantenimiento</div>
              <div style={{ fontSize: "24px", fontWeight: 700, color: "var(--warn)" }}>
                {datos.lineas.mantenimiento}
              </div>
            </div>
            <div className="card">
              <div style={{ fontSize: "12px", color: "var(--muted)" }}>Líneas Libres</div>
              <div style={{ fontSize: "24px", fontWeight: 700, color: "var(--text)" }}>
                {datos.lineas.libres}
              </div>
            </div>
            <div className="card">
              <div style={{ fontSize: "12px", color: "var(--muted)" }}>Antigüedad de Telemetría</div>
              <div style={{ fontSize: "24px", fontWeight: 700, color: "var(--accent)" }}>
                {datos.telemetria.antiguedad_s}s
              </div>
            </div>
          </div>

          {/* Tabla de Agentes por Etapa */}
          <div className="card">
            <h3 style={{ fontSize: "14px", fontWeight: 650, marginBottom: "12px" }}>
              Agentes por Etapa del Pipeline
            </h3>
            <Tabla densidad="alta">
              <TablaEncabezado>
                <TablaFila>
                  <TablaCeldaEncabezado>Etapa</TablaCeldaEncabezado>
                  <TablaCeldaEncabezado numerico>Agentes Totales</TablaCeldaEncabezado>
                  <TablaCeldaEncabezado numerico>Ocupados</TablaCeldaEncabezado>
                  <TablaCeldaEncabezado numerico>Caídos / Error</TablaCeldaEncabezado>
                </TablaFila>
              </TablaEncabezado>
              <TablaCuerpo>
                {datos.etapas.map((et) => (
                  <TablaFila key={et.nombre}>
                    <TablaCelda>
                      <span style={{ fontWeight: 600, textTransform: "capitalize" }}>{et.nombre}</span>
                    </TablaCelda>
                    <TablaCelda numerico>{et.agentes_total}</TablaCelda>
                    <TablaCelda numerico>{et.agentes_ocupados}</TablaCelda>
                    <TablaCelda numerico>
                      {et.agentes_caidos > 0 ? (
                        <Badge variante="bad">{et.agentes_caidos}</Badge>
                      ) : (
                        <span style={{ color: "var(--muted)" }}>0</span>
                      )}
                    </TablaCelda>
                  </TablaFila>
                ))}
              </TablaCuerpo>
            </Tabla>
          </div>

          {/* Tabla de Colas de Mensajería */}
          <div className="card">
            <h3 style={{ fontSize: "14px", fontWeight: 650, marginBottom: "12px" }}>
              Profundidad de Colas y Dead Letter Queues
            </h3>
            <Tabla densidad="alta">
              <TablaEncabezado>
                <TablaFila>
                  <TablaCeldaEncabezado>Cola</TablaCeldaEncabezado>
                  <TablaCeldaEncabezado numerico>Mensajes Pendientes</TablaCeldaEncabezado>
                  <TablaCeldaEncabezado numerico>Antigüedad Máxima (s)</TablaCeldaEncabezado>
                  <TablaCeldaEncabezado>Estado</TablaCeldaEncabezado>
                </TablaFila>
              </TablaEncabezado>
              <TablaCuerpo>
                {datos.colas.map((q) => (
                  <TablaFila key={q.nombre}>
                    <TablaCelda>
                      <code className="mono">{q.nombre}</code>
                    </TablaCelda>
                    <TablaCelda numerico>{q.pendientes}</TablaCelda>
                    <TablaCelda numerico>{q.antiguedad_max_s}s</TablaCelda>
                    <TablaCelda>
                      <Badge
                        variante={
                          q.estado === "normal"
                            ? "good"
                            : q.estado === "atencion"
                            ? "warn"
                            : "bad"
                        }
                        punto
                      >
                        {q.estado.toUpperCase()}
                      </Badge>
                    </TablaCelda>
                  </TablaFila>
                ))}
              </TablaCuerpo>
            </Tabla>
          </div>
        </>
      )}

      {errorCarga && (
        <div style={{ color: "var(--error)", fontSize: "12px" }}>
          Error: {errorCarga}
        </div>
      )}
    </div>
  );
};
