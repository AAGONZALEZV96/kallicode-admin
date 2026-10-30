/**
 * BizOverview.tsx — Panel General de Negocio de la Consola Admin (§18.17 / §18.23)
 *
 * Muestra KPIs ejecutivos agregados: MRR, clientes activos, distribución por plan,
 * consumo de tokens, entregas de pipeline y frescura de los agregados en PostgreSQL.
 */

import React from "react";
import { useQuery } from "@tanstack/react-query";
import { peticionApi, ApiError } from "../api/clienteApi";
import { Boton } from "../componentes/Boton";
import { Badge } from "../componentes/Badge";

export interface OverviewClientes {
  activos: number;
  altas: number;
  perdidos: number;
  por_plan: Record<string, number>;
}

export interface OverviewConsumo {
  loc: number;
  tokens: number;
  coste_estimado: number;
}

export interface OverviewPipeline {
  tickets_entregados: number;
  tiempo_e2e_p50_h: number | null;
  escalado_humano_pct: number;
}

export interface OverviewTendencia {
  consumo: number | null;
  pipeline: number | null;
}

export interface OverviewResponse {
  frescura: string;
  clientes: OverviewClientes;
  ingresos: { importe: number; moneda: string };
  ingreso_recurrente: { importe: number; moneda: string };
  mrr_eur: number;
  consumo: OverviewConsumo;
  pipeline: OverviewPipeline;
  tendencia: OverviewTendencia;
}

export const BizOverview: React.FC = () => {
  const { data, isLoading, error, refetch } = useQuery<OverviewResponse, ApiError>({
    queryKey: ["business-overview"],
    queryFn: () => peticionApi<OverviewResponse>("/admin/v1/business/overview"),
    staleTime: 30000,
  });

  if (isLoading) {
    return (
      <div
        data-testid="overview-loading"
        style={{
          padding: "2rem",
          textAlign: "center",
          color: "var(--muted, #94a3b8)",
          backgroundColor: "var(--card, #1e293b)",
          borderRadius: "0.5rem",
          border: "1px solid var(--border, #334155)",
        }}
      >
        <p style={{ margin: 0, fontSize: "1rem" }}>Cargando indicadores de negocio...</p>
      </div>
    );
  }

  if (error || !data) {
    const apiErr = error instanceof ApiError ? error : null;
    const es503 = apiErr?.status === 503 || apiErr?.codigo === "AGREGADO_NO_DISPONIBLE";
    const es403 = apiErr?.status === 403 || apiErr?.codigo === "ROL_STAFF_INSUFICIENTE";

    return (
      <div
        data-testid="overview-error"
        style={{
          padding: "1.5rem",
          backgroundColor: "rgba(239, 68, 68, 0.1)",
          borderRadius: "0.5rem",
          border: "1px solid var(--bad, #ef4444)",
          color: "var(--text, #f8fafc)",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: "0.5rem", marginBottom: "0.5rem" }}>
          <Badge variante="error">
            {es503 ? "AGREGADOS EN REFRESCO" : es403 ? "ACCESO DENEGADO" : "ERROR"}
          </Badge>
          <strong style={{ fontSize: "1.1rem" }}>
            {es503
              ? "Agregados analíticos en proceso de cálculo"
              : es403
              ? "Permisos insuficientes"
              : "No se pudieron cargar los datos de negocio"}
          </strong>
        </div>
        <p style={{ color: "var(--muted, #94a3b8)", margin: "0.5rem 0 1rem 0", fontSize: "0.875rem" }}>
          {apiErr?.message || "Ocurrió un error inesperado al consultar la API de negocio."}
        </p>
        <Boton variante="secondary" tamano="sm" onClick={() => void refetch()}>
          Reintentar consulta
        </Boton>
      </div>
    );
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "1.5rem" }}>
      {/* Cabecera de la Vista */}
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          flexWrap: "wrap",
          gap: "1rem",
        }}
      >
        <div>
          <h1
            style={{
              fontSize: "1.5rem",
              fontWeight: 700,
              color: "var(--text, #f8fafc)",
              margin: 0,
            }}
          >
            Panel General de Negocio
          </h1>
          <p
            style={{
              fontSize: "0.875rem",
              color: "var(--muted, #94a3b8)",
              margin: "0.25rem 0 0 0",
            }}
          >
            Métricas ejecutivas consolidadas desde la capa de agregados en PostgreSQL.
          </p>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
          <Badge variante="good">ACTIVO</Badge>
          <span style={{ fontSize: "0.75rem", color: "var(--muted, #94a3b8)" }}>
            Frescura: {new Date(data.frescura).toLocaleTimeString()}
          </span>
        </div>
      </div>

      {/* Tarjetas de Indicadores Principales (KPIs) */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))",
          gap: "1rem",
        }}
      >
        {/* MRR */}
        <div
          data-testid="kpi-mrr"
          style={{
            padding: "1.25rem",
            backgroundColor: "var(--card, #1e293b)",
            borderRadius: "0.5rem",
            border: "1px solid var(--border, #334155)",
          }}
        >
          <span style={{ fontSize: "0.75rem", color: "var(--muted, #94a3b8)", textTransform: "uppercase" }}>
            Ingreso Recurrente Mensual
          </span>
          <div style={{ fontSize: "1.75rem", fontWeight: 700, color: "var(--accent, #6366f1)", marginTop: "0.25rem" }}>
            {data.mrr_eur.toLocaleString("es-ES", { minimumFractionDigits: 2 })} €
          </div>
          <div style={{ fontSize: "0.75rem", color: "var(--good, #10b981)", marginTop: "0.25rem" }}>
            Moneda: {data.ingresos?.moneda || "EUR"}
          </div>
        </div>

        {/* Clientes Activos */}
        <div
          data-testid="kpi-clientes-activos"
          style={{
            padding: "1.25rem",
            backgroundColor: "var(--card, #1e293b)",
            borderRadius: "0.5rem",
            border: "1px solid var(--border, #334155)",
          }}
        >
          <span style={{ fontSize: "0.75rem", color: "var(--muted, #94a3b8)", textTransform: "uppercase" }}>
            Clientes Activos
          </span>
          <div style={{ fontSize: "1.75rem", fontWeight: 700, color: "var(--text, #f8fafc)", marginTop: "0.25rem" }}>
            {data.clientes.activos}
          </div>
          <div style={{ fontSize: "0.75rem", color: "var(--muted, #94a3b8)", marginTop: "0.25rem" }}>
            +{data.clientes.altas} altas | -{data.clientes.perdidos} cancelaciones
          </div>
        </div>

        {/* Consumo de Tokens */}
        <div
          data-testid="kpi-tokens"
          style={{
            padding: "1.25rem",
            backgroundColor: "var(--card, #1e293b)",
            borderRadius: "0.5rem",
            border: "1px solid var(--border, #334155)",
          }}
        >
          <span style={{ fontSize: "0.75rem", color: "var(--muted, #94a3b8)", textTransform: "uppercase" }}>
            Consumo de Tokens (Ciclo)
          </span>
          <div style={{ fontSize: "1.75rem", fontWeight: 700, color: "var(--text, #f8fafc)", marginTop: "0.25rem" }}>
            {data.consumo.tokens.toLocaleString("es-ES")}
          </div>
          <div style={{ fontSize: "0.75rem", color: "var(--muted, #94a3b8)", marginTop: "0.25rem" }}>
            Coste estimado: {data.consumo.coste_estimado.toFixed(2)} €
          </div>
        </div>

        {/* Pipeline Entregas */}
        <div
          data-testid="kpi-pipeline"
          style={{
            padding: "1.25rem",
            backgroundColor: "var(--card, #1e293b)",
            borderRadius: "0.5rem",
            border: "1px solid var(--border, #334155)",
          }}
        >
          <span style={{ fontSize: "0.75rem", color: "var(--muted, #94a3b8)", textTransform: "uppercase" }}>
            Tickets Entregados
          </span>
          <div style={{ fontSize: "1.75rem", fontWeight: 700, color: "var(--text, #f8fafc)", marginTop: "0.25rem" }}>
            {data.pipeline.tickets_entregados}
          </div>
          <div style={{ fontSize: "0.75rem", color: "var(--muted, #94a3b8)", marginTop: "0.25rem" }}>
            Escalado humano: {data.pipeline.escalado_humano_pct}% | p50: {data.pipeline.tiempo_e2e_p50_h ?? 0}h
          </div>
        </div>
      </div>

      {/* Desglose por Planes */}
      <div
        style={{
          padding: "1.25rem",
          backgroundColor: "var(--card, #1e293b)",
          borderRadius: "0.5rem",
          border: "1px solid var(--border, #334155)",
        }}
      >
        <h2 style={{ fontSize: "1rem", fontWeight: 600, color: "var(--text, #f8fafc)", margin: "0 0 1rem 0" }}>
          Distribución de Organizaciones por Plan
        </h2>
        <div style={{ display: "flex", flexWrap: "wrap", gap: "1rem" }}>
          {Object.entries(data.clientes.por_plan).map(([plan, cantidad]) => (
            <div
              key={plan}
              style={{
                flex: "1 1 150px",
                padding: "0.75rem 1rem",
                backgroundColor: "rgba(255, 255, 255, 0.03)",
                borderRadius: "0.375rem",
                border: "1px solid var(--border, #334155)",
              }}
            >
              <span style={{ fontSize: "0.75rem", textTransform: "capitalize", color: "var(--muted, #94a3b8)" }}>
                {plan}
              </span>
              <div style={{ fontSize: "1.25rem", fontWeight: 700, color: "var(--text, #f8fafc)", marginTop: "0.25rem" }}>
                {cantidad}
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
};
