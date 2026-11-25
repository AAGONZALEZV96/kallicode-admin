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
import { useTranslation } from "react-i18next";
import { peticionApi, ApiError } from "../api/clienteApi";
import { useAuth } from "../estado/auth";
import { formatCurrencyEUR, formatDateTime, formatNumber, formatPercent } from "../i18n/formatters";
import { Boton } from "../componentes/Boton";
import { Badge } from "../componentes/Badge";
import { Select } from "../componentes/Select";
import { ContenedorEstado } from "../componentes/ContenedorEstado";
import { useInsideAdminLayout } from "../componentes/AdminLayout";

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

const LIMITE_FRESCURA_MS = 6 * 60 * 60 * 1000; // 6 horas

export const BizOverview: React.FC = () => {
  const { t, i18n } = useTranslation();
  const lang = i18n.resolvedLanguage || i18n.language;
  const insideLayout = useInsideAdminLayout();
  const RootTag: React.ElementType = insideLayout ? "div" : "main";
  const { usuario } = useAuth();
  const [periodo, setPeriodo] = useState<PeriodoRango>("mes_actual");
  const [compararCon, setCompararCon] = useState<ComparacionRango>("periodo_anterior");

  const opcionesPeriodo = [
    { valor: "mes_actual", etiqueta: t("views.bizOverview.filters.periods.mes_actual") },
    { valor: "mes_anterior", etiqueta: t("views.bizOverview.filters.periods.mes_anterior") },
    { valor: "trimestre", etiqueta: t("views.bizOverview.filters.periods.trimestre") },
    { valor: "ano", etiqueta: t("views.bizOverview.filters.periods.ano") },
  ];

  const opcionesComparacion = [
    { valor: "periodo_anterior", etiqueta: t("views.bizOverview.filters.comparisons.periodo_anterior") },
    {
      valor: "mismo_periodo_ano_anterior",
      etiqueta: t("views.bizOverview.filters.comparisons.mismo_periodo_ano_anterior"),
    },
  ];

  const formatearFrescuraRelativa = (fechaIso: string): string => {
    const timestamp = new Date(fechaIso).getTime();
    if (isNaN(timestamp)) return t("views.bizOverview.freshness.unavailable");
    const diffSegundos = Math.max(0, Math.floor((Date.now() - timestamp) / 1000));
    if (diffSegundos < 60) return t("views.bizOverview.freshness.secondsAgo");
    const diffMinutos = Math.floor(diffSegundos / 60);
    if (diffMinutos < 60) return t("views.bizOverview.freshness.minutesAgo", { count: diffMinutos });
    const diffHoras = Math.floor(diffMinutos / 60);
    if (diffHoras < 24) return t("views.bizOverview.freshness.hoursAgo", { count: diffHoras });
    const diffDias = Math.floor(diffHoras / 24);
    return t("views.bizOverview.freshness.daysAgo", { count: diffDias });
  };

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
      <RootTag
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
          <Badge variante="error">{t("common.errors.accessDeniedBadge")}</Badge>
          <strong style={{ fontSize: "1.1rem" }}>{t("common.errors.accessDeniedCode")}</strong>
        </div>
        <p style={{ color: "var(--muted)", margin: "0.5rem 0" }}>
          {t("views.bizOverview.rbacDenied", { role: usuario?.role })}
        </p>
      </RootTag>
    );
  }

  const apiErr = error instanceof ApiError ? error : null;
  const es503 = apiErr?.status === 503 || apiErr?.codigo === "AGREGADO_NO_DISPONIBLE";
  const es403 = apiErr?.status === 403 || apiErr?.codigo === "ROL_STAFF_INSUFICIENTE";

  // Cálculo del estado de Frescura de los datos agregados
  const antiguedadMs = data ? Date.now() - new Date(data.frescura).getTime() : 0;
  const esFrescuraAlta = data ? (Number.isNaN(antiguedadMs) ? false : antiguedadMs > LIMITE_FRESCURA_MS) : false;
  const variacionMrr = data ? (data.variacion_pct ?? data.tendencia?.mrr) : null;
  const altasClientes = data ? (data.clientes.nuevos ?? data.clientes.altas ?? 0) : 0;

  return (
    <ContenedorEstado
      cargando={isLoading}
      error={error}
      vacio={!isLoading && !error && !data}
      tipoCarga="kpis"
      tarjetasCarga={4}
      dataTestIdCarga="overview-loading"
      dataTestIdError="overview-error"
      dataTestIdTrace="overview-trace-id"
      tituloError={
        es503
          ? t("common.errors.aggregatesRefreshing")
          : es403
          ? t("common.errors.accessDeniedBadge")
          : t("views.bizOverview.errorTitle")
      }
      mensajeError={
        apiErr?.message || (es503 ? t("views.bizOverview.error503Message") : undefined)
      }
      textoBotonReintento={t("common.actions.retryQuery")}
      alReintentar={() => void refetch()}
    >
      {data && (
        <RootTag
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
            {t("views.bizOverview.title")}
          </h1>
          <p
            style={{
              fontSize: "0.875rem",
              color: "var(--muted)",
              margin: "0.25rem 0 0 0",
            }}
          >
            {t("views.bizOverview.subtitle")}
          </p>
        </div>

        {/* Indicador de Frescura de Agregados */}
        <div
          data-testid="indicador-frescura"
          style={{ display: "flex", alignItems: "center", gap: "0.5rem", flexWrap: "wrap" }}
        >
          {esFrescuraAlta ? (
            <Badge variante="warn" data-testid="badge-frescura-warn">
              {t("views.bizOverview.freshness.staleBadge")}
            </Badge>
          ) : (
            <Badge variante="good" data-testid="badge-frescura-ok">
              {t("views.bizOverview.freshness.activeBadge")}
            </Badge>
          )}
          <span
            style={{ fontSize: "0.75rem", color: "var(--muted)" }}
            title={t("views.bizOverview.freshness.exactTitle", {
              date: formatDateTime(data.frescura, undefined, lang),
            })}
          >
            <time dateTime={data.frescura}>
              {formatearFrescuraRelativa(data.frescura)}
            </time>
          </span>
          {isFetching && (
            <span style={{ fontSize: "0.75rem", color: "var(--accent)" }} aria-hidden="true">
              {t("views.bizOverview.freshness.updating")}
            </span>
          )}
        </div>
      </header>

      {/* Controles de Periodo y Comparación */}
      <section
        aria-label={t("views.bizOverview.filters.regionLabel")}
        className="kc-filter-bar"
        style={{
          padding: "1rem",
          backgroundColor: "var(--card)",
          borderRadius: "var(--radius-md)",
          border: "1px solid var(--border)",
        }}
      >
        <div className="kc-filter-item">
          <Select
            id="filtro-periodo"
            etiqueta={t("views.bizOverview.filters.periodLabel")}
            opciones={opcionesPeriodo}
            value={periodo}
            onChange={(e) => setPeriodo(e.target.value as PeriodoRango)}
          />
        </div>

        <div className="kc-filter-item-wide">
          <Select
            id="filtro-comparacion"
            etiqueta={t("views.bizOverview.filters.compareLabel")}
            opciones={opcionesComparacion}
            value={compararCon}
            onChange={(e) => setCompararCon(e.target.value as ComparacionRango)}
          />
        </div>

        <div className="kc-filter-actions" style={{ marginLeft: "auto" }}>
          <Boton
            variante="ghost"
            tamano="sm"
            onClick={() => void refetch()}
            disabled={isFetching}
            aria-label={t("views.bizOverview.filters.refreshAria")}
          >
            {t("views.bizOverview.filters.refreshButton")}
          </Boton>
        </div>
      </section>

      {/* 4 Bloques Principales de Métricas Consolidadas (KPIs) */}
      <section
        aria-label={t("views.bizOverview.kpis.regionLabel")}
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(min(100%, 200px), 1fr))",
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
              {t("views.bizOverview.kpis.mrrTitle")}
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
            {formatCurrencyEUR(data.mrr_eur, data.ingresos?.moneda || "EUR", lang)}
          </div>

          <footer style={{ fontSize: "0.75rem", display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <span style={{ color: "var(--muted)" }}>
              {t("views.bizOverview.kpis.currency", { currency: data.ingresos?.moneda || "EUR" })}
            </span>
            {variacionMrr !== undefined && variacionMrr !== null && (
              <span
                style={{
                  fontWeight: 600,
                  color: variacionMrr >= 0 ? "var(--good)" : "var(--bad)",
                }}
              >
                {formatPercent(variacionMrr, { decimals: 1, includeSign: true, lang })}
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
              {t("views.bizOverview.kpis.activeCustomersTitle")}
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
            {formatNumber(data.clientes.activos, undefined, lang)}
          </div>

          <footer
            style={{
              fontSize: "0.75rem",
              color: "var(--muted)",
              display: "flex",
              flexWrap: "wrap",
              gap: "0.5rem",
            }}
          >
            <span style={{ color: "var(--good)" }}>
              {t("views.bizOverview.kpis.signups", { count: altasClientes })}
            </span>
            <span style={{ color: "var(--bad)" }}>
              {t("views.bizOverview.kpis.cancellations", { count: data.clientes.perdidos })}
            </span>
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
              {t("views.bizOverview.kpis.tokensTitle")}
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
            {formatNumber(data.consumo.tokens, undefined, lang)}
          </div>

          <footer
            style={{
              fontSize: "0.75rem",
              color: "var(--muted)",
              display: "flex",
              flexDirection: "column",
              gap: "0.2rem",
            }}
          >
            <span>
              {t("views.bizOverview.kpis.locCount", {
                count: formatNumber(data.consumo.loc, undefined, lang),
              })}
            </span>
            <span>
              {t("views.bizOverview.kpis.estimatedCost", {
                cost: formatCurrencyEUR(data.consumo.coste_estimado, "EUR", lang),
              })}
            </span>
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
              {t("views.bizOverview.kpis.deliveredTicketsTitle")}
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
            {formatNumber(data.pipeline.tickets_entregados, undefined, lang)}
          </div>

          <footer
            style={{
              fontSize: "0.75rem",
              color: "var(--muted)",
              display: "flex",
              flexDirection: "column",
              gap: "0.2rem",
            }}
          >
            <span>
              {t("views.bizOverview.kpis.humanEscalation", {
                pct: formatPercent(data.pipeline.escalado_humano_pct, { decimals: 1, lang }),
              })}
            </span>
            <span>
              {t("views.bizOverview.kpis.p50Time", {
                hours: formatNumber(
                  data.pipeline.tiempo_e2e_p50_h ?? 0,
                  { minimumFractionDigits: 1, maximumFractionDigits: 1 },
                  lang
                ),
              })}
            </span>
          </footer>
        </article>
      </section>

      {/* Desglose de Organizaciones por Plan */}
      <section
        aria-label={t("views.bizOverview.plansBreakdown.regionLabel")}
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
          {t("views.bizOverview.plansBreakdown.title")}
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
                {t(`common.plans.${plan.toLowerCase()}`, { defaultValue: plan })}
              </span>
              <div
                style={{
                  fontSize: "1.25rem",
                  fontWeight: 700,
                  color: "var(--text)",
                  marginTop: "0.25rem",
                }}
              >
                {formatNumber(cantidad, undefined, lang)}
              </div>
            </div>
          ))}
        </div>
      </section>
    </RootTag>
      )}
    </ContenedorEstado>
  );
};
