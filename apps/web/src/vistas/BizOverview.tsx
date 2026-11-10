/**
 * BizOverview.tsx — Panel General de Negocio de la Consola Admin (§18.17 / §18.23)
 *
 * Muestra los 4 bloques principales de métricas consolidadas:
 * 1. Ingreso Recurrente Mensual (MRR con variación y moneda).
 * 2. Clientes Activos (total, altas, bajas y desglose por plan: starter, growth, enterprise).
 * 3. Consumo Agregado de Plataforma (LOC, tokens y coste comercial estimado).
 * 4. Rendimiento del Pipeline (tickets entregados, tiempo e2e p50 y tasa de escalado humano).
 *
 * Incluye controles de rango temporal, declaración de frescura con alerta de antigüedad (> 6h),
 * estados de carga con skeleton loading, tarjeta de error con X-Trace-Id y control RBAC.
 */

import React, { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { peticionApi, ApiError } from "../api/clienteApi";
import { useAuth } from "../estado/auth";
import { Boton } from "../componentes/Boton";
import { Badge } from "../componentes/Badge";
import { Select } from "../componentes/Select";

export interface OverviewClientes {
  activos: number;
  nuevos?: number;
  altas?: number;
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
  mrr?: number | null;
  consumo?: number | null;
  pipeline?: number | null;
}

export interface OverviewPeriodo {
  inicio?: string;
  fin?: string;
  tipo?: string;
  comparar_con?: string;
}

export interface OverviewResponse {
  frescura: string;
  periodo?: OverviewPeriodo;
  variacion_pct?: number | null;
  clientes: OverviewClientes;
  ingresos: { importe: number; moneda: string };
  ingreso_recurrente: { importe: number; moneda: string };
  mrr_eur: number;
  consumo: OverviewConsumo;
  pipeline: OverviewPipeline;
  tendencia: OverviewTendencia;
}

export type PeriodoRango = "mes_actual" | "mes_anterior" | "trimestre" | "ano";
export type ComparacionRango = "periodo_anterior" | "mismo_periodo_ano_anterior";

const OPCIONES_PERIODO = [
  { valor: "mes_actual", etiqueta: "Mes actual" },
  { valor: "mes_anterior", etiqueta: "Mes anterior" },
  { valor: "trimestre", etiqueta: "Trimestre en curso" },
  { valor: "ano", etiqueta: "Año en curso" },
];

const OPCIONES_COMPARACION = [
  { valor: "periodo_anterior", etiqueta: "Periodo anterior" },
  { valor: "mismo_periodo_ano_anterior", etiqueta: "Mismo periodo año anterior" },
];

const LIMITE_FRESCURA_MS = 6 * 60 * 60 * 1000; // 6 horas

export const BizOverview: React.FC = () => {
  const { usuario } = useAuth();
  const [periodo, setPeriodo] = useState<PeriodoRango>("mes_actual");
  const [compararCon, setCompararCon] = useState<ComparacionRango>("periodo_anterior");

  // Validación de acceso RBAC a nivel de componente
  const rolNoAutorizado =
    Boolean(usuario) &&
    usuario?.role !== "staff_negocio" &&
    usuario?.role !== "staff_admin";

  const { data, isLoading, isFetching, error, refetch } = useQuery<OverviewResponse, ApiError>({
    queryKey: ["business-overview", periodo, compararCon],
    queryFn: () =>
      peticionApi<OverviewResponse>("/admin/v1/business/overview", {
        params: {
          periodo,
          comparar_con: compararCon,
        },
      }),
    enabled: !rolNoAutorizado,
    placeholderData: (previousData) => previousData,
    staleTime: 30000,
  });

  // 1. Pantalla de denegación de permisos RBAC
  if (rolNoAutorizado) {
    return (
      <main
        className="biz-overview-access-denied"
        data-testid="overview-error"
        role="alert"
        style={{
          padding: "1.5rem",
          backgroundColor: "var(--bad-bg)",
          borderRadius: "var(--radius-md)",
          border: "1px solid var(--bad)",
          color: "var(--text)",
          margin: "1rem 0",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: "0.5rem", marginBottom: "0.5rem" }}>
          <Badge variante="error">ACCESO DENEGADO</Badge>
          <strong style={{ fontSize: "1.1rem" }}>403 ROL_STAFF_INSUFICIENTE</strong>
        </div>
        <p style={{ color: "var(--muted)", margin: "0.5rem 0" }}>
          Acceso denegado para el rol {usuario?.role}. Esta pantalla es de visualización exclusiva para personal de negocio o administración.
        </p>
      </main>
    );
  }

  // 2. Estado de Carga: Skeleton Loading estructural preservando el layout
  if (isLoading) {
    return (
      <main
        className="biz-overview-loading"
        data-testid="overview-loading"
        role="status"
        aria-busy="true"
        style={{ display: "flex", flexDirection: "column", gap: "1.5rem" }}
      >
        <span className="sr-only">Cargando indicadores de negocio...</span>

        {/* Cabecera Esqueleto */}
        <header
          style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
            flexWrap: "wrap",
            gap: "1rem",
          }}
        >
          <div>
            <div
              style={{
                width: "220px",
                height: "28px",
                backgroundColor: "var(--surface2)",
                borderRadius: "var(--radius-sm)",
                marginBottom: "0.5rem",
              }}
            />
            <div
              style={{
                width: "360px",
                height: "16px",
                backgroundColor: "var(--surface)",
                borderRadius: "var(--radius-sm)",
              }}
            />
          </div>
          <div
            style={{
              width: "120px",
              height: "24px",
              backgroundColor: "var(--surface2)",
              borderRadius: "var(--radius-sm)",
            }}
          />
        </header>

        {/* Barra de Filtros Esqueleto */}
        <div
          style={{
            display: "flex",
            gap: "1rem",
            padding: "1rem",
            backgroundColor: "var(--card)",
            borderRadius: "var(--radius-md)",
            border: "1px solid var(--border)",
          }}
        >
          <div style={{ width: "180px", height: "36px", backgroundColor: "var(--surface2)", borderRadius: "var(--radius-sm)" }} />
          <div style={{ width: "220px", height: "36px", backgroundColor: "var(--surface2)", borderRadius: "var(--radius-sm)" }} />
        </div>

        {/* Grid de KPIs Esqueleto */}
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))",
            gap: "1rem",
          }}
        >
          {[1, 2, 3, 4].map((i) => (
            <div
              key={i}
              style={{
                padding: "1.25rem",
                backgroundColor: "var(--card)",
                borderRadius: "var(--radius-md)",
                border: "1px solid var(--border)",
                minHeight: "120px",
                display: "flex",
                flexDirection: "column",
                justifyContent: "space-between",
              }}
            >
              <div style={{ width: "60%", height: "14px", backgroundColor: "var(--surface2)", borderRadius: "var(--radius-sm)" }} />
              <div style={{ width: "80%", height: "32px", backgroundColor: "var(--surface)", borderRadius: "var(--radius-sm)" }} />
              <div style={{ width: "40%", height: "12px", backgroundColor: "var(--surface2)", borderRadius: "var(--radius-sm)" }} />
            </div>
          ))}
        </div>

        <p style={{ margin: 0, textAlign: "center", color: "var(--muted)", fontSize: "0.875rem" }}>
          Cargando indicadores de negocio...
        </p>
      </main>
    );
  }

  // 3. Manejo de Errores Accionable (HTTP 503, HTTP 403, Errores de Red)
  if (error || !data) {
    const apiErr = error instanceof ApiError ? error : null;
    const es503 = apiErr?.status === 503 || apiErr?.codigo === "AGREGADO_NO_DISPONIBLE";
    const es403 = apiErr?.status === 403 || apiErr?.codigo === "ROL_STAFF_INSUFICIENTE";
    const traceId =
      apiErr?.traceId ||
      (apiErr?.detalle as Record<string, unknown>)?.trace_id as string ||
      "trc_biz_overview_error";

    return (
      <main
        className="biz-overview-error"
        data-testid="overview-error"
        role="alert"
        style={{
          padding: "1.5rem",
          backgroundColor: "var(--bad-bg)",
          borderRadius: "var(--radius-md)",
          border: "1px solid var(--bad)",
          color: "var(--text)",
          margin: "1rem 0",
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

        <p style={{ color: "var(--muted)", margin: "0.5rem 0", fontSize: "0.875rem" }}>
          {apiErr?.message || "Ocurrió un error inesperado al consultar la API de negocio."}
        </p>

        {/* Visualización explícita del X-Trace-Id para diagnóstico */}
        <div
          data-testid="overview-trace-id"
          style={{
            margin: "0.75rem 0",
            fontSize: "0.75rem",
            color: "var(--muted)",
            display: "flex",
            alignItems: "center",
            gap: "0.5rem",
          }}
        >
          <span>X-Trace-Id:</span>
          <code
            style={{
              padding: "0.15rem 0.4rem",
              backgroundColor: "var(--surface)",
              borderRadius: "var(--radius-sm)",
              border: "1px solid var(--border)",
              color: "var(--text)",
            }}
          >
            {traceId}
          </code>
        </div>

        <Boton variante="secondary" tamano="sm" onClick={() => void refetch()}>
          Reintentar consulta
        </Boton>
      </main>
    );
  }

  // 4. Cálculo del estado de Frescura de los datos agregados
  const antiguedadMs = Date.now() - new Date(data.frescura).getTime();
  const esFrescuraAlta = Number.isNaN(antiguedadMs) ? false : antiguedadMs > LIMITE_FRESCURA_MS;
  const variacionMrr = data.variacion_pct ?? data.tendencia?.mrr;
  const altasClientes = data.clientes.nuevos ?? data.clientes.altas ?? 0;

  return (
    <main
      className="biz-overview"
      aria-live="polite"
      style={{ display: "flex", flexDirection: "column", gap: "1.5rem" }}
    >
      {/* Cabecera Ejecutiva */}
      <header
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
              color: "var(--text)",
              margin: 0,
            }}
          >
            Panel General de Negocio
          </h1>
          <p
            style={{
              fontSize: "0.875rem",
              color: "var(--muted)",
              margin: "0.25rem 0 0 0",
            }}
          >
            Métricas ejecutivas consolidadas desde la capa de agregados en PostgreSQL.
          </p>
        </div>

        {/* Indicador de Frescura de Agregados */}
        <div
          data-testid="indicador-frescura"
          style={{ display: "flex", alignItems: "center", gap: "0.5rem", flexWrap: "wrap" }}
        >
          {esFrescuraAlta ? (
            <Badge variante="warn" data-testid="badge-frescura-warn">
              WARN admin.business.frescura_alta
            </Badge>
          ) : (
            <Badge variante="good" data-testid="badge-frescura-ok">
              ACTIVO
            </Badge>
          )}
          <span style={{ fontSize: "0.75rem", color: "var(--muted)" }}>
            Frescura:{" "}
            <time dateTime={data.frescura}>
              {new Date(data.frescura).toLocaleTimeString("es-ES", {
                hour: "2-digit",
                minute: "2-digit",
                second: "2-digit",
              })}
            </time>
          </span>
          {isFetching && (
            <span style={{ fontSize: "0.75rem", color: "var(--accent)" }} aria-hidden="true">
              (Actualizando...)
            </span>
          )}
        </div>
      </header>

      {/* Controles de Periodo y Comparación */}
      <section
        aria-label="Controles de rango temporal y comparación"
        style={{
          display: "flex",
          flexWrap: "wrap",
          alignItems: "flex-end",
          gap: "1rem",
          padding: "1rem",
          backgroundColor: "var(--card)",
          borderRadius: "var(--radius-md)",
          border: "1px solid var(--border)",
        }}
      >
        <div style={{ minWidth: "180px" }}>
          <Select
            id="filtro-periodo"
            etiqueta="Periodo"
            opciones={OPCIONES_PERIODO}
            value={periodo}
            onChange={(e) => setPeriodo(e.target.value as PeriodoRango)}
          />
        </div>

        <div style={{ minWidth: "220px" }}>
          <Select
            id="filtro-comparacion"
            etiqueta="Comparar con"
            opciones={OPCIONES_COMPARACION}
            value={compararCon}
            onChange={(e) => setCompararCon(e.target.value as ComparacionRango)}
          />
        </div>

        <div style={{ marginLeft: "auto", alignSelf: "flex-end" }}>
          <Boton
            variante="ghost"
            tamano="sm"
            onClick={() => void refetch()}
            disabled={isFetching}
            aria-label="Refrescar métricas de negocio"
          >
            Refrescar métricas
          </Boton>
        </div>
      </section>

      {/* 4 Bloques Principales de Métricas Consolidadas (KPIs) */}
      <section
        aria-label="Tarjetas principales de indicadores de negocio"
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))",
          gap: "1rem",
        }}
      >
        {/* Bloque 1: Ingreso Recurrente Mensual (MRR) */}
        <article
          data-testid="kpi-mrr"
          style={{
            padding: "1.25rem",
            backgroundColor: "var(--card)",
            borderRadius: "var(--radius-md)",
            border: "1px solid var(--border)",
            display: "flex",
            flexDirection: "column",
            justifyContent: "space-between",
          }}
        >
          <header>
            <span
              style={{
                fontSize: "0.75rem",
                color: "var(--muted)",
                textTransform: "uppercase",
                letterSpacing: "0.05em",
                fontWeight: 600,
              }}
            >
              Ingreso Recurrente Mensual
            </span>
          </header>

          <div
            style={{
              fontSize: "1.75rem",
              fontWeight: 700,
              color: "var(--accent)",
              marginTop: "0.35rem",
              marginBottom: "0.35rem",
            }}
          >
            {data.mrr_eur.toLocaleString("es-ES", { minimumFractionDigits: 2 })} €
          </div>

          <footer style={{ fontSize: "0.75rem", display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <span style={{ color: "var(--muted)" }}>
              Moneda: {data.ingresos?.moneda || "EUR"}
            </span>
            {variacionMrr !== undefined && variacionMrr !== null && (
              <span
                style={{
                  fontWeight: 600,
                  color: variacionMrr >= 0 ? "var(--good)" : "var(--bad)",
                }}
              >
                {variacionMrr >= 0 ? `+${variacionMrr}%` : `${variacionMrr}%`}
              </span>
            )}
          </footer>
        </article>

        {/* Bloque 2: Clientes Activos */}
        <article
          data-testid="kpi-clientes-activos"
          style={{
            padding: "1.25rem",
            backgroundColor: "var(--card)",
            borderRadius: "var(--radius-md)",
            border: "1px solid var(--border)",
            display: "flex",
            flexDirection: "column",
            justifyContent: "space-between",
          }}
        >
          <header>
            <span
              style={{
                fontSize: "0.75rem",
                color: "var(--muted)",
                textTransform: "uppercase",
                letterSpacing: "0.05em",
                fontWeight: 600,
              }}
            >
              Clientes Activos
            </span>
          </header>

          <div
            style={{
              fontSize: "1.75rem",
              fontWeight: 700,
              color: "var(--text)",
              marginTop: "0.35rem",
              marginBottom: "0.35rem",
            }}
          >
            {data.clientes.activos}
          </div>

          <footer style={{ fontSize: "0.75rem", color: "var(--muted)" }}>
            +{altasClientes} altas | -{data.clientes.perdidos} cancelaciones
          </footer>
        </article>

        {/* Bloque 3: Consumo Agregado de Plataforma */}
        <article
          data-testid="kpi-tokens"
          style={{
            padding: "1.25rem",
            backgroundColor: "var(--card)",
            borderRadius: "var(--radius-md)",
            border: "1px solid var(--border)",
            display: "flex",
            flexDirection: "column",
            justifyContent: "space-between",
          }}
        >
          <header>
            <span
              style={{
                fontSize: "0.75rem",
                color: "var(--muted)",
                textTransform: "uppercase",
                letterSpacing: "0.05em",
                fontWeight: 600,
              }}
            >
              Consumo de Tokens (Ciclo)
            </span>
          </header>

          <div
            style={{
              fontSize: "1.75rem",
              fontWeight: 700,
              color: "var(--text)",
              marginTop: "0.35rem",
              marginBottom: "0.35rem",
            }}
          >
            {data.consumo.tokens.toLocaleString("es-ES")}
          </div>

          <footer style={{ fontSize: "0.75rem", color: "var(--muted)" }}>
            {data.consumo.loc.toLocaleString("es-ES")} LOC | Coste: {data.consumo.coste_estimado.toFixed(2)} €
          </footer>
        </article>

        {/* Bloque 4: Rendimiento del Pipeline */}
        <article
          data-testid="kpi-pipeline"
          style={{
            padding: "1.25rem",
            backgroundColor: "var(--card)",
            borderRadius: "var(--radius-md)",
            border: "1px solid var(--border)",
            display: "flex",
            flexDirection: "column",
            justifyContent: "space-between",
          }}
        >
          <header>
            <span
              style={{
                fontSize: "0.75rem",
                color: "var(--muted)",
                textTransform: "uppercase",
                letterSpacing: "0.05em",
                fontWeight: 600,
              }}
            >
              Tickets Entregados
            </span>
          </header>

          <div
            style={{
              fontSize: "1.75rem",
              fontWeight: 700,
              color: "var(--text)",
              marginTop: "0.35rem",
              marginBottom: "0.35rem",
            }}
          >
            {data.pipeline.tickets_entregados}
          </div>

          <footer style={{ fontSize: "0.75rem", color: "var(--muted)" }}>
            Escalado humano: {data.pipeline.escalado_humano_pct}% | p50: {data.pipeline.tiempo_e2e_p50_h ?? 0}h
          </footer>
        </article>
      </section>

      {/* Desglose de Organizaciones por Plan */}
      <section
        aria-label="Desglose por plan de suscripción"
        style={{
          padding: "1.25rem",
          backgroundColor: "var(--card)",
          borderRadius: "var(--radius-md)",
          border: "1px solid var(--border)",
        }}
      >
        <h2
          style={{
            fontSize: "1rem",
            fontWeight: 600,
            color: "var(--text)",
            margin: "0 0 1rem 0",
          }}
        >
          Distribución de Organizaciones por Plan
        </h2>

        <div style={{ display: "flex", flexWrap: "wrap", gap: "1rem" }}>
          {Object.entries(data.clientes.por_plan).map(([plan, cantidad]) => (
            <div
              key={plan}
              data-testid={`plan-${plan}`}
              style={{
                flex: "1 1 150px",
                padding: "0.75rem 1rem",
                backgroundColor: "var(--surface)",
                borderRadius: "var(--radius-sm)",
                border: "1px solid var(--border)",
              }}
            >
              <span
                style={{
                  fontSize: "0.75rem",
                  textTransform: "capitalize",
                  color: "var(--muted)",
                  fontWeight: 500,
                }}
              >
                {plan}
              </span>
              <div
                style={{
                  fontSize: "1.25rem",
                  fontWeight: 700,
                  color: "var(--text)",
                  marginTop: "0.25rem",
                }}
              >
                {cantidad}
              </div>
            </div>
          ))}
        </div>
      </section>
    </main>
  );
};
