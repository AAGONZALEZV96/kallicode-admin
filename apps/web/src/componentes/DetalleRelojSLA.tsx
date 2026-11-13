/**
 * DetalleRelojSLA.tsx — Modal de Explicabilidad del Reloj y Tramos de SLA
 *
 * Muestra la descomposición cronológica del reloj para un caso específico:
 * - Ecuación de consistencia: Tiempo Bruto = Tiempo Computado + Pausas Justificadas.
 * - Línea de tiempo cronológica diferenciando tramos computables y pausas tipificadas.
 * - Reglas aplicadas del cálculo de nivel de servicio sin exponer detalles técnicos internos.
 */

import React from "react";
import { useQuery } from "@tanstack/react-query";
import { peticionApi } from "../api/clienteApi";
import { Modal } from "./Modal";
import { Badge, BadgeVariante } from "./Badge";
import { Boton } from "./Boton";
import { ContenedorEstado } from "./ContenedorEstado";

export interface SlaClockSegment {
  inicio: string;
  fin: string | null;
  duracion_h: number;
  horas?: number;
  computa: boolean;
  etapa: string | null;
  causa_pausa: string | null;
}

export type SlaResultado = "dentro" | "incumplido" | "en_curso" | "en_riesgo" | "sin_objetivo";

export interface SlaCaseDetailData {
  job_id: string;
  ticket_id?: string | null;
  ticket_numero?: string | null;
  razon_social?: string | null;
  tenant_id: string;
  plan?: string | null;
  etapa_actual?: string | null;
  objetivo_h?: number | null;
  bruto_h: number;
  transcurrido_h: number;
  pausa_total_h: number;
  resultado: SlaResultado;
  tramos: SlaClockSegment[];
  reglas_aplicadas: string[];
  iniciado_en?: string | null;
  terminado_en?: string | null;
  calculado_en?: string | null;
  enmascarado?: string[];
}

export interface DetalleRelojSLAProps {
  jobId: string | null;
  abierto: boolean;
  alCerrar: () => void;
}

const ETIQUETAS_CAUSA_PAUSA: Record<string, string> = {
  espera_firma_cliente: "Espera de firma del cliente",
  escalado_humano: "Escalado a revisión humana",
  ventana_mantenimiento: "Ventana de mantenimiento programado",
  indisponibilidad_proveedor_llm: "Indisponibilidad de proveedor LLM",
  otro: "Otra pausa justificada",
};

export function traducirCausaPausa(causa: string | null | undefined): string {
  if (!causa) return "Pausa justificada";
  return ETIQUETAS_CAUSA_PAUSA[causa] ?? causa.replace(/_/g, " ");
}

function obtenerVarianteResultado(resultado: SlaResultado): BadgeVariante {
  switch (resultado) {
    case "dentro":
      return "good";
    case "en_riesgo":
      return "warn";
    case "incumplido":
      return "bad";
    case "en_curso":
      return "accent";
    default:
      return "neutro";
  }
}

function formatearFechaHora(iso: string | null | undefined): string {
  if (!iso) return "En curso";
  const fecha = new Date(iso);
  if (isNaN(fecha.getTime())) return iso;
  return fecha.toLocaleString("es-ES", {
    dateStyle: "short",
    timeStyle: "short",
  });
}

function sanitizarReglaTexto(texto: string): string {
  return texto
    .replace(/§\d+(\.\d+)?/g, "")
    .replace(/\badmin\.[a-z0-9_]+\b/gi, "registro interno de nivel de servicio")
    .trim();
}

export const DetalleRelojSLA: React.FC<DetalleRelojSLAProps> = ({
  jobId,
  abierto,
  alCerrar,
}) => {
  const {
    data,
    isLoading,
    error,
    refetch,
  } = useQuery<SlaCaseDetailData>({
    queryKey: ["ops-sla-case", jobId],
    queryFn: () =>
      peticionApi<SlaCaseDetailData>(`/admin/v1/ops/sla/cases/${encodeURIComponent(jobId || "")}`),
    enabled: abierto && Boolean(jobId),
  });

  const estaEnmascarado =
    !data?.enmascarado ||
    data.enmascarado.includes("razon_social") ||
    data.enmascarado.includes("tenant_id");

  const bruto = data?.bruto_h ?? 0;
  const computado = data?.transcurrido_h ?? 0;
  const pausas = data?.pausa_total_h ?? Math.max(0, bruto - computado);
  const totalBarra = bruto > 0 ? bruto : computado + pausas;
  const pctComputado = totalBarra > 0 ? Math.min(100, (computado / totalBarra) * 100) : 0;
  const pctPausas = totalBarra > 0 ? Math.max(0, 100 - pctComputado) : 0;

  return (
    <Modal
      abierto={abierto}
      alCerrar={alCerrar}
      titulo={jobId ? `Desglose del reloj de servicio: ${jobId}` : "Desglose del reloj de servicio"}
      idTitulo="detalle-reloj-sla-titulo"
      anchoMaximo="820px"
      pie={
        <div style={{ display: "flex", justifyContent: "flex-end" }}>
          <Boton variante="secondary" onClick={alCerrar}>
            Cerrar
          </Boton>
        </div>
      }
    >
      <ContenedorEstado
        cargando={isLoading}
        error={error}
        vacio={!data}
        tipoCarga="detalle"
        mensajeCarga="Cargando tramos cronológicos del reloj SLA..."
        onReintentar={() => void refetch()}
        tituloError="No se pudo obtener el desglose del reloj SLA"
        tituloVacio="Sin datos de reloj para este caso"
        descripcionVacio="No existen segmentos registrados para el identificador seleccionado."
        dataTestIdCarga="detalle-reloj-loading"
        dataTestIdError="detalle-reloj-error"
        dataTestIdTrace="detalle-reloj-trace"
      >
        {data && (
          <div style={{ display: "flex", flexDirection: "column", gap: "18px" }}>
            {/* Metadatos del caso */}
            <div
              style={{
                display: "grid",
                gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))",
                gap: "12px",
                padding: "12px",
                borderRadius: "var(--radius-md, 8px)",
                backgroundColor: "var(--surface2, #1e293b)",
                border: "1px solid var(--border, #334155)",
              }}
            >
              <div>
                <div style={{ fontSize: "11px", color: "var(--muted)" }}>Ticket</div>
                <div className="mono" style={{ fontWeight: 600 }}>
                  {data.ticket_numero || data.ticket_id || "—"}
                </div>
              </div>
              <div>
                <div style={{ fontSize: "11px", color: "var(--muted)" }}>Cliente / Tenant</div>
                <div style={{ display: "flex", alignItems: "center", gap: "6px", flexWrap: "wrap" }}>
                  <span style={{ fontWeight: 600 }}>
                    {data.razon_social || data.tenant_id}
                  </span>
                  <Badge variante={estaEnmascarado ? "masked" : "good"}>
                    {estaEnmascarado ? "ENMASCARADO" : "EN CLARO"}
                  </Badge>
                </div>
              </div>
              <div>
                <div style={{ fontSize: "11px", color: "var(--muted)" }}>Plan y Objetivo</div>
                <div style={{ fontWeight: 600, textTransform: "capitalize" }}>
                  {data.plan || "—"} ·{" "}
                  {data.objetivo_h != null ? `${data.objetivo_h.toFixed(1)} h` : "Sin objetivo"}
                </div>
              </div>
              <div>
                <div style={{ fontSize: "11px", color: "var(--muted)" }}>Etapa y Resultado</div>
                <div style={{ display: "flex", alignItems: "center", gap: "8px", marginTop: "2px" }}>
                  <span style={{ fontSize: "13px", textTransform: "uppercase" }}>
                    {data.etapa_actual || "—"}
                  </span>
                  <Badge variante={obtenerVarianteResultado(data.resultado)} punto>
                    {data.resultado.toUpperCase()}
                  </Badge>
                </div>
              </div>
            </div>

            {/* Ecuación de consistencia matemática */}
            <section
              aria-label="Ecuación de consistencia del reloj SLA"
              data-testid="ecuacion-reloj-sla"
              style={{
                padding: "14px",
                borderRadius: "var(--radius-md, 8px)",
                border: "1px solid var(--border, #334155)",
                backgroundColor: "var(--surface, #0f172a)",
              }}
            >
              <div
                style={{
                  fontSize: "12px",
                  fontWeight: 600,
                  color: "var(--muted)",
                  marginBottom: "10px",
                }}
              >
                Ecuación de consistencia: Tiempo Bruto = Tiempo Computado + Horas de Pausa Justificada
              </div>

              <div
                style={{
                  display: "grid",
                  gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))",
                  gap: "10px",
                  alignItems: "center",
                  marginBottom: "12px",
                }}
              >
                <div
                  style={{
                    padding: "10px",
                    borderRadius: "6px",
                    backgroundColor: "var(--surface2, #1e293b)",
                  }}
                >
                  <div style={{ fontSize: "11px", color: "var(--muted)" }}>Tiempo Bruto</div>
                  <div className="mono" style={{ fontSize: "18px", fontWeight: 700 }}>
                    {bruto.toFixed(2)} h
                  </div>
                </div>
                <div
                  style={{
                    padding: "10px",
                    borderRadius: "6px",
                    backgroundColor: "rgba(56, 189, 248, 0.12)",
                    border: "1px solid rgba(56, 189, 248, 0.35)",
                  }}
                >
                  <div style={{ fontSize: "11px", color: "var(--accent, #38bdf8)" }}>
                    Tiempo Computado (Neto)
                  </div>
                  <div
                    className="mono"
                    style={{ fontSize: "18px", fontWeight: 700, color: "var(--accent, #38bdf8)" }}
                  >
                    {computado.toFixed(2)} h
                  </div>
                </div>
                <div
                  style={{
                    padding: "10px",
                    borderRadius: "6px",
                    backgroundColor: "rgba(245, 158, 11, 0.12)",
                    border: "1px solid rgba(245, 158, 11, 0.35)",
                  }}
                >
                  <div style={{ fontSize: "11px", color: "var(--warn, #f59e0b)" }}>
                    Horas de Pausa Justificada
                  </div>
                  <div
                    className="mono"
                    style={{ fontSize: "18px", fontWeight: 700, color: "var(--warn, #f59e0b)" }}
                  >
                    {pausas.toFixed(2)} h
                  </div>
                </div>
              </div>

              {/* Barra visual proporcional */}
              <div
                role="img"
                aria-label={`Distribución del reloj: ${computado.toFixed(2)} horas computables y ${pausas.toFixed(2)} horas en pausa justificada`}
                style={{
                  display: "flex",
                  height: "12px",
                  borderRadius: "999px",
                  overflow: "hidden",
                  backgroundColor: "var(--surface2, #334155)",
                }}
              >
                <div
                  style={{
                    width: `${pctComputado}%`,
                    backgroundColor: "var(--accent, #38bdf8)",
                    transition: "width 0.25s ease",
                  }}
                  title={`Computable: ${computado.toFixed(2)} h`}
                />
                <div
                  style={{
                    width: `${pctPausas}%`,
                    backgroundColor: "var(--warn, #f59e0b)",
                    transition: "width 0.25s ease",
                  }}
                  title={`Pausa justificada: ${pausas.toFixed(2)} h`}
                />
              </div>
            </section>

            {/* Línea de tiempo cronológica de tramos */}
            <section aria-label="Línea de tiempo de tramos cronológicos" data-testid="timeline-tramos-sla">
              <h3 style={{ fontSize: "14px", fontWeight: 650, margin: "0 0 10px 0" }}>
                Línea de tiempo cronológica de tramos
              </h3>
              {data.tramos.length === 0 ? (
                <div style={{ fontSize: "13px", color: "var(--muted)" }}>
                  No hay tramos registrados para este caso.
                </div>
              ) : (
                <ol
                  style={{
                    listStyle: "none",
                    padding: 0,
                    margin: 0,
                    display: "flex",
                    flexDirection: "column",
                    gap: "10px",
                  }}
                >
                  {data.tramos.map((tramo, idx) => {
                    const duracion = tramo.duracion_h ?? tramo.horas ?? 0;
                    const esComputable = Boolean(tramo.computa);
                    const colorBorde = esComputable
                      ? "var(--accent, #38bdf8)"
                      : "var(--warn, #f59e0b)";
                    return (
                      <li
                        key={`${tramo.inicio}-${idx}`}
                        data-testid={`tramo-sla-${idx}`}
                        style={{
                          borderLeft: `4px solid ${colorBorde}`,
                          padding: "10px 12px",
                          borderRadius: "6px",
                          backgroundColor: esComputable
                            ? "rgba(56, 189, 248, 0.08)"
                            : "rgba(245, 158, 11, 0.08)",
                          display: "flex",
                          justifyContent: "space-between",
                          alignItems: "center",
                          flexWrap: "wrap",
                          gap: "10px",
                        }}
                      >
                        <div style={{ display: "flex", flexDirection: "column", gap: "4px" }}>
                          <div style={{ display: "flex", alignItems: "center", gap: "8px", flexWrap: "wrap" }}>
                            <span style={{ fontWeight: 600, textTransform: "uppercase", fontSize: "12px" }}>
                              {tramo.etapa || "General"}
                            </span>
                            <Badge variante={esComputable ? "accent" : "warn"}>
                              {esComputable ? "Computa al SLA" : "Pausa justificada"}
                            </Badge>
                            {!esComputable && tramo.causa_pausa && (
                              <span
                                style={{
                                  fontSize: "12px",
                                  fontWeight: 500,
                                  color: "var(--warn, #f59e0b)",
                                }}
                              >
                                {traducirCausaPausa(tramo.causa_pausa)}
                              </span>
                            )}
                          </div>
                          <div style={{ fontSize: "12px", color: "var(--muted)" }}>
                            {formatearFechaHora(tramo.inicio)} — {formatearFechaHora(tramo.fin)}
                          </div>
                        </div>

                        <div className="mono" style={{ fontWeight: 700, fontSize: "14px" }}>
                          {duracion.toFixed(2)} h
                        </div>
                      </li>
                    );
                  })}
                </ol>
              )}
            </section>

            {/* Reglas aplicadas ADR-003 */}
            {data.reglas_aplicadas && data.reglas_aplicadas.length > 0 && (
              <section
                aria-label="Reglas aplicadas en el cómputo de nivel de servicio"
                data-testid="reglas-adr003-sla"
                style={{
                  padding: "12px",
                  borderRadius: "var(--radius-md, 8px)",
                  backgroundColor: "var(--surface2, #1e293b)",
                  border: "1px solid var(--border, #334155)",
                }}
              >
                <h3 style={{ fontSize: "13px", fontWeight: 650, margin: "0 0 8px 0" }}>
                  Criterios y deducciones aplicadas en el reloj
                </h3>
                <ul style={{ margin: 0, paddingLeft: "18px", fontSize: "13px", display: "grid", gap: "6px" }}>
                  {data.reglas_aplicadas.map((regla, idx) => (
                    <li key={idx}>{sanitizarReglaTexto(regla)}</li>
                  ))}
                </ul>
              </section>
            )}
          </div>
        )}
      </ContenedorEstado>
    </Modal>
  );
};
