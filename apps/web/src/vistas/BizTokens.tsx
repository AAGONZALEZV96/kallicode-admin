/**
 * BizTokens.tsx — Pantalla de Análisis de Consumo de Tokens, Costes y Tendencias
 *
 * Implementa el ticket [KC-ADM-B4-04] (Épica EAD4 / §18.21 / ADM-G08 / ADM-G09):
 * 1. Conexión a GET /admin/v1/business/usage/tokens mediante TanStack Query.
 * 2. Barra de controles analíticos: periodo, plan/tier, búsqueda debounced (450ms) y agrupación (cliente, tier, dia).
 * 3. Tarjetas de resumen ejecutivo de FinOps (total tokens, coste consolidado EUR, porcentaje medio de cuota y alertas).
 * 4. Panel de tendencias y desglose por tier con separación estricta e innegociable de fable respecto a pro.
 * 5. Tabla densa paginada con allowlist de ordenación, enlace a ficha de cliente y badges de cuadre con facturación.
 * 6. Política E6 de privacidad: enmascaramiento por defecto (A•••• S.L.), indicador de privacidad e integración
 *    contextual con SolicitudConcesionModal para revelación de datos con justificación obligatoria (KC/SUP).
 * 7. Control de acceso RBAC: exclusivo para staff_negocio y staff_admin (bloqueo 403 ROL_STAFF_INSUFICIENTE para otros).
 * 8. Cumplimiento estricto de accesibilidad WCAG 2.1 AA y tokens de diseño (tokens.css).
 */

import React, { useState, useEffect, useMemo, useCallback } from "react";
import { useSearchParams, Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { peticionApi, ApiError } from "../api/clienteApi";
import { useAuth } from "../estado/auth";
import { formatCurrencyEUR, formatNumber, formatPercent, formatTime } from "../i18n/formatters";
import { Boton } from "../componentes/Boton";
import { Badge } from "../componentes/Badge";
import { Select } from "../componentes/Select";
import { Input } from "../componentes/Input";
import {
  Tabla,
  TablaEncabezado,
  TablaCuerpo,
  TablaFila,
  TablaCeldaEncabezado,
  TablaCelda,
} from "../componentes/Tabla";
import { ContenedorEstado } from "../componentes/ContenedorEstado";
import { SolicitudConcesionModal } from "../componentes/SolicitudConcesionModal";
import { ControlExportarReporte } from "../componentes/ControlExportarReporte";
import { useInsideAdminLayout } from "../componentes/AdminLayout";

// ------------------------------------------------------------------ Interfaces de Datos
export interface TokenPorTier {
  flash: number;
  pro: number;
  fable: number;
  [key: string]: number;
}

export interface UsageTokenItem {
  clave: string;
  tenant_id?: string | null;
  dia?: string | null;
  tier?: string | null;
  razon_social?: string;
  plan?: string;
  tokens_in: number;
  tokens_input?: number;
  tokens_out: number;
  tokens_output?: number;
  tokens_total: number;
  por_tier?: TokenPorTier;
  coste: number;
  coste_estimado_eur?: number;
  loc_consumidas?: number | null;
  loc_procesadas?: number | null;
  umbral?: number;
  cuota_asignada?: number;
  cuota_pct?: number | null;
  porcentaje_consumido?: number | null;
  cuadra_con_facturacion?: boolean;
  enmascarado?: boolean;
}

export interface UsageTokensResumen {
  total_tokens: number;
  tokens_total?: number;
  coste_consolidado: number;
  coste_total_eur?: number;
  porcentaje_medio_cuota: number;
  cuota_consumo_media_pct?: number;
  moneda: string;
}

export interface UsageTokensResponse {
  items: UsageTokenItem[];
  total: number;
  page: number;
  page_size: number;
  pages: number;
  ciclo?: string;
  periodo?: string;
  frescura?: string;
  totales?: {
    tokens: number;
    coste: number;
    moneda: string;
  };
  resumen?: UsageTokensResumen;
  cuadra_con_facturacion?: boolean;
  descuadres?: string[] | null;
  alguna_enmascarada?: boolean;
}

// ------------------------------------------------------------------ Componente Principal
export const BizTokens: React.FC = () => {
  const { t, i18n } = useTranslation();
  const lang = i18n.resolvedLanguage || i18n.language;
  const insideLayout = useInsideAdminLayout();
  const RbacTag: React.ElementType = insideLayout ? "div" : "main";
  const { usuario } = useAuth();
  const [searchParams, setSearchParams] = useSearchParams();

  const opcionesPeriodo = [
    { valor: "mes_actual", etiqueta: t("views.bizTokens.filters.periods.mes_actual") },
    { valor: "mes_anterior", etiqueta: t("views.bizTokens.filters.periods.mes_anterior") },
    { valor: "trimestre", etiqueta: t("views.bizTokens.filters.periods.trimestre") },
    { valor: "ano", etiqueta: t("views.bizTokens.filters.periods.ano") },
  ];

  const opcionesPlan = [
    { valor: "todos", etiqueta: t("common.plans.all") },
    { valor: "starter", etiqueta: t("common.plans.starter") },
    { valor: "growth", etiqueta: t("common.plans.growth") },
    { valor: "enterprise", etiqueta: t("common.plans.enterprise") },
  ];

  const opcionesAgrupacion = [
    { valor: "cliente", etiqueta: t("views.bizTokens.filters.groupBy.cliente") },
    { valor: "tier", etiqueta: t("views.bizTokens.filters.groupBy.tier") },
    { valor: "dia", etiqueta: t("views.bizTokens.filters.groupBy.dia") },
  ];

  const allowlistOrden = [
    { valor: "coste_desc", etiqueta: t("views.bizTokens.filters.sortOptions.coste_desc") },
    { valor: "coste_asc", etiqueta: t("views.bizTokens.filters.sortOptions.coste_asc") },
    { valor: "tokens_total_desc", etiqueta: t("views.bizTokens.filters.sortOptions.tokens_total_desc") },
    { valor: "tokens_total_asc", etiqueta: t("views.bizTokens.filters.sortOptions.tokens_total_asc") },
    { valor: "tokens_in_desc", etiqueta: t("views.bizTokens.filters.sortOptions.tokens_in_desc") },
    { valor: "tokens_out_desc", etiqueta: t("views.bizTokens.filters.sortOptions.tokens_out_desc") },
    { valor: "cuota_pct_desc", etiqueta: t("views.bizTokens.filters.sortOptions.cuota_pct_desc") },
    { valor: "cuota_pct_asc", etiqueta: t("views.bizTokens.filters.sortOptions.cuota_pct_asc") },
    { valor: "loc_consumidas_desc", etiqueta: t("views.bizTokens.filters.sortOptions.loc_consumidas_desc") },
  ];

  // Control RBAC estricto
  const esRolAutorizado =
    usuario?.role === "staff_negocio" || usuario?.role === "staff_admin";

  // Estados de Filtros sincronizados con URL
  const periodo = searchParams.get("periodo") || "mes_actual";
  const plan = searchParams.get("plan") || "todos";
  const agruparPor = searchParams.get("agrupar_por") || "cliente";
  const qUrl = searchParams.get("q") || "";
  const page = parseInt(searchParams.get("page") || "1", 10);
  const pageSize = parseInt(searchParams.get("page_size") || "25", 10);
  const orden = searchParams.get("order_by") || "coste_desc";

  // Input de búsqueda con debounce (450ms)
  const [busquedaInput, setBusquedaInput] = useState<string>(qUrl);

  useEffect(() => {
    setBusquedaInput(qUrl);
  }, [qUrl]);

  useEffect(() => {
    const timer = setTimeout(() => {
      if (busquedaInput !== qUrl) {
        setSearchParams((prev) => {
          const params = new URLSearchParams(prev);
          if (busquedaInput.trim()) {
            params.set("q", busquedaInput.trim());
          } else {
            params.delete("q");
          }
          params.set("page", "1");
          return params;
        });
      }
    }, 450);

    return () => clearTimeout(timer);
  }, [busquedaInput, qUrl, setSearchParams]);

  // Modal de Concesión E6
  const [modalConcesionAbierto, setModalConcesionAbierto] = useState(false);
  const [mostrarTodasColumnas, setMostrarTodasColumnas] = useState(false);
  const [concesionTenantId, setConcesionTenantId] = useState("");
  const [concesionRazonSocial, setConcesionRazonSocial] = useState("");

  const handleAbrirConcesion = (tId: string, rSoc?: string) => {
    setConcesionTenantId(tId);
    setConcesionRazonSocial(rSoc || "");
    setModalConcesionAbierto(true);
  };

  const handleCerrarConcesion = () => {
    setModalConcesionAbierto(false);
    setConcesionTenantId("");
    setConcesionRazonSocial("");
  };

  // Construcción de Query URL
  const endpointUrl = useMemo(() => {
    const params = new URLSearchParams();
    params.set("periodo", periodo);
    if (plan !== "todos") {
      params.set("plan", plan);
    }
    if (qUrl.trim()) {
      params.set("tenant_id", qUrl.trim());
    }
    params.set("agrupar_por", agruparPor);
    params.set("page", page.toString());
    params.set("page_size", pageSize.toString());

    // Mapeo de allowlist de ordenación al formato esperado por el backend
    if (orden === "coste_asc") params.set("order_by", "coste_eur");
    else if (orden === "coste_desc") params.set("order_by", "-coste_eur");
    else if (orden === "tokens_total_asc") params.set("order_by", "tokens_total");
    else if (orden === "tokens_total_desc") params.set("order_by", "-tokens_total");
    else if (orden === "tokens_in_desc") params.set("order_by", "-tokens_in");
    else if (orden === "tokens_out_desc") params.set("order_by", "-tokens_out");
    else if (orden === "cuota_pct_asc") params.set("order_by", "cuota_pct");
    else if (orden === "cuota_pct_desc") params.set("order_by", "-cuota_pct");
    else if (orden === "loc_consumidas_desc") params.set("order_by", "-loc_consumidas");

    return `/admin/v1/business/usage/tokens?${params.toString()}`;
  }, [periodo, plan, qUrl, agruparPor, page, pageSize, orden]);

  // Consulta TanStack Query
  const {
    data,
    isLoading,
    error,
    refetch,
    isFetching,
  } = useQuery<UsageTokensResponse>({
    queryKey: ["business-usage-tokens", periodo, plan, qUrl, agruparPor, page, pageSize, orden],
    queryFn: () => peticionApi<UsageTokensResponse>(endpointUrl),
    enabled: esRolAutorizado,
    staleTime: 30000,
  });

  // Manejo de actualización de filtros
  const handleCambioFiltro = useCallback(
    (clave: string, valor: string) => {
      setSearchParams((prev) => {
        const params = new URLSearchParams(prev);
        if (valor === "todos" || !valor) {
          params.delete(clave);
        } else {
          params.set(clave, valor);
        }
        params.set("page", "1");
        return params;
      });
    },
    [setSearchParams]
  );

  // Totales acumulados por Tier (Flash, Pro, Fable)
  const totalesPorTier = useMemo(() => {
    let flash = 0;
    let pro = 0;
    let fable = 0;

    if (!data?.items || data.items.length === 0) {
      return { flash: 0, pro: 0, fable: 0, total: 0, pctFlash: 0, pctPro: 0, pctFable: 0 };
    }

    data.items.forEach((item) => {
      if (item.por_tier) {
        flash += Number(item.por_tier.flash || 0);
        pro += Number(item.por_tier.pro || 0);
        fable += Number(item.por_tier.fable || 0);
      } else if (item.tier) {
        if (item.tier === "flash") flash += item.tokens_total;
        else if (item.tier === "pro") pro += item.tokens_total;
        else if (item.tier === "fable") fable += item.tokens_total;
      }
    });

    const sumaTiers = flash + pro + fable;
    const total = sumaTiers || data.resumen?.total_tokens || 0;

    if (total === 0) {
      return { flash, pro, fable, total: 0, pctFlash: 0, pctPro: 0, pctFable: 0 };
    }

    const pctFlash = Math.round((flash / total) * 100);
    const pctPro = Math.round((pro / total) * 100);
    // Garantía matemática estricta de suma 100% sin desviación por redondeo
    const pctFable = 100 - pctFlash - pctPro;

    return {
      flash,
      pro,
      fable,
      total,
      pctFlash,
      pctPro,
      pctFable,
    };
  }, [data]);

  // 1. Bloqueo Visual RBAC (403 ROL_STAFF_INSUFICIENTE)
  if (!esRolAutorizado) {
    return (
      <RbacTag
        className="biz-tokens-access-denied"
        data-testid="tokens-error"
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
          {t("views.bizTokens.rbacDenied", { role: usuario?.role })}
        </p>
      </RbacTag>
    );
  }

  // 2. Extracción de Metadatos de Error
  const apiErr = error instanceof ApiError ? error : null;
  const traceId =
    apiErr?.traceId ||
    ((apiErr?.detalle as Record<string, unknown>)?.trace_id as string) ||
    "trc_tokens_error_001";

  const resumen = data?.resumen || {
    total_tokens: data?.totales?.tokens || 0,
    coste_consolidado: data?.totales?.coste || 0,
    porcentaje_medio_cuota: 0,
    moneda: "EUR",
  };

  const hayDescuadreFacturacion =
    data?.cuadra_con_facturacion === false ||
    (Boolean(data?.descuadres && data.descuadres.length > 0));

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "1.5rem" }}>
      {/* Encabezado Principal */}
      <header
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "flex-start",
          flexWrap: "wrap",
          gap: "1rem",
        }}
      >
        <div>
          <div style={{ display: "flex", alignItems: "center", gap: "0.75rem", marginBottom: "0.25rem" }}>
            <h1 style={{ margin: 0, fontSize: "1.5rem", fontWeight: 700, color: "var(--text)" }}>
              {t("views.bizTokens.title")}
            </h1>
            {data?.frescura && (
              <span style={{ fontSize: "0.75rem", color: "var(--muted)" }}>
                {t("views.bizTokens.freshness", { time: formatTime(data.frescura, lang) })}
              </span>
            )}
            {isFetching && (
              <span
                role="status"
                style={{ fontSize: "0.75rem", color: "var(--accent)", fontStyle: "italic" }}
              >
                {t("views.bizTokens.updating")}
              </span>
            )}
          </div>
          <p style={{ margin: 0, fontSize: "0.875rem", color: "var(--muted)" }}>
            {t("views.bizTokens.subtitle")}
          </p>
        </div>

        <div className="kc-toolbar-actions">
          <ControlExportarReporte
            tipo="consumo"
            etiquetaBoton={t("components.exportReport.button")}
            formatosPermitidos={["csv", "xlsx", "pdf"]}
            rolesPermitidos={["staff_negocio", "staff_admin"]}
          />
          <Boton
            variante="secondary"
            tamano="sm"
            onClick={() => refetch()}
            disabled={isFetching}
            data-testid="btn-refetch-tokens"
          >
            {isFetching ? t("views.bizTokens.refreshing") : t("common.actions.refresh")}
          </Boton>
        </div>
      </header>

      {/* Alerta Destacada de Descuadre con Facturación */}
      {hayDescuadreFacturacion && (
        <section
          data-testid="alerta-descuadre-facturacion"
          role="alert"
          aria-live="assertive"
          style={{
            padding: "1rem 1.25rem",
            borderRadius: "var(--radius-md)",
            backgroundColor: "var(--bad-bg)",
            border: "1px solid var(--bad)",
            color: "var(--text)",
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            flexWrap: "wrap",
            gap: "0.75rem",
          }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: "0.75rem" }}>
            <span aria-hidden="true" style={{ fontSize: "1.5rem" }}>🚨</span>
            <div>
              <strong style={{ display: "block", color: "var(--bad)" }}>
                {t("views.bizTokens.discrepancyBanner.title")}
              </strong>
              <span style={{ fontSize: "0.875rem", color: "var(--muted)" }}>
                {t("views.bizTokens.discrepancyBanner.description", {
                  clients:
                    data?.descuadres?.join(", ") || t("views.bizTokens.discrepancyBanner.defaultClients"),
                })}
              </span>
            </div>
          </div>
          <Badge variante="error">{t("views.bizTokens.discrepancyBanner.badge")}</Badge>
        </section>
      )}

      {/* Región de anuncio reactivo accesible para cambios de filtros (§18.21 / A11Y) */}
      <div
        role="status"
        aria-live="polite"
        data-testid="anuncio-filtros-dinamicos"
        style={{
          position: "absolute",
          width: "1px",
          height: "1px",
          margin: "-1px",
          padding: 0,
          overflow: "hidden",
          clip: "rect(0, 0, 0, 0)",
          border: 0,
        }}
      >
        {t("views.bizTokens.liveFilterAnnouncement", {
          period: periodo,
          plan,
          groupBy: agruparPor,
          queryPart: qUrl ? t("views.bizTokens.liveFilterQueryPart", { query: qUrl }) : "",
        })}
      </div>

      {/* Barra de Filtros y Controles Analíticos */}
      <section
        aria-label={t("views.bizTokens.filters.regionLabel")}
        className="kc-filter-bar"
        style={{
          padding: "1rem",
          backgroundColor: "var(--card)",
          borderRadius: "var(--radius-md)",
          border: "1px solid var(--border)",
        }}
      >
        <div className="kc-filter-item">
          <label
            htmlFor="filtro-periodo"
            style={{ display: "block", fontSize: "0.75rem", fontWeight: 600, color: "var(--muted)", marginBottom: "4px" }}
          >
            {t("views.bizTokens.filters.periodLabel")}
          </label>
          <Select
            id="filtro-periodo"
            data-testid="select-periodo"
            value={periodo}
            onChange={(e) => handleCambioFiltro("periodo", e.target.value)}
            opciones={opcionesPeriodo}
          />
        </div>

        <div className="kc-filter-item">
          <label
            htmlFor="filtro-plan"
            style={{ display: "block", fontSize: "0.75rem", fontWeight: 600, color: "var(--muted)", marginBottom: "4px" }}
          >
            {t("views.bizTokens.filters.planLabel")}
          </label>
          <Select
            id="filtro-plan"
            data-testid="select-plan"
            value={plan}
            onChange={(e) => handleCambioFiltro("plan", e.target.value)}
            opciones={opcionesPlan}
          />
        </div>

        <div className="kc-filter-item">
          <label
            htmlFor="filtro-agrupacion"
            style={{ display: "block", fontSize: "0.75rem", fontWeight: 600, color: "var(--muted)", marginBottom: "4px" }}
          >
            {t("views.bizTokens.filters.groupLabel")}
          </label>
          <Select
            id="filtro-agrupacion"
            data-testid="select-agrupacion"
            value={agruparPor}
            onChange={(e) => handleCambioFiltro("agrupar_por", e.target.value)}
            opciones={opcionesAgrupacion}
          />
        </div>

        <div className="kc-filter-item-wide">
          <label
            htmlFor="filtro-busqueda-cliente"
            style={{ display: "block", fontSize: "0.75rem", fontWeight: 600, color: "var(--muted)", marginBottom: "4px" }}
          >
            {t("views.bizTokens.filters.searchLabel")}
          </label>
          <Input
            id="filtro-busqueda-cliente"
            data-testid="input-busqueda-cliente"
            placeholder={t("views.bizTokens.filters.searchPlaceholder")}
            value={busquedaInput}
            onChange={(e) => setBusquedaInput(e.target.value)}
          />
        </div>

        <div className="kc-filter-item">
          <label
            htmlFor="filtro-ordenacion"
            style={{ display: "block", fontSize: "0.75rem", fontWeight: 600, color: "var(--muted)", marginBottom: "4px" }}
          >
            {t("views.bizTokens.filters.sortLabel")}
          </label>
          <Select
            id="filtro-ordenacion"
            data-testid="select-ordenacion"
            value={orden}
            onChange={(e) => handleCambioFiltro("order_by", e.target.value)}
            opciones={allowlistOrden}
          />
        </div>
      </section>

      {/* Orquestador de Estados de Contenido */}
      <ContenedorEstado
        cargando={isLoading && !data}
        error={error}
        vacio={!isLoading && !error && (!data?.items || data.items.length === 0)}
        tipoCarga="tabla"
        filasCarga={6}
        columnasCarga={7}
        alReintentar={() => refetch()}
        tituloError={
          apiErr?.status === 503
            ? t("views.bizTokens.errors.title503")
            : t("views.bizTokens.errors.titleGeneric")
        }
        mensajeError={
          apiErr?.status === 503
            ? t("views.bizTokens.errors.msg503", { traceId })
            : t("views.bizTokens.errors.msgGeneric", { message: apiErr?.message || "" })
        }
        tituloVacio={t("views.bizTokens.empty.title")}
        descripcionVacio={t("views.bizTokens.empty.description")}
        textoAccionVacio={t("views.bizTokens.empty.action")}
        alAccionarVacio={() => setSearchParams({ periodo: "mes_actual", agrupar_por: "cliente" })}
      >
        {data && (
          <>
            {/* Tarjetas de Resumen Ejecutivo (FinOps) */}
            <section
              aria-label={t("views.bizTokens.kpis.regionLabel")}
              style={{
                display: "grid",
                gridTemplateColumns: "repeat(auto-fit, minmax(min(100%, 220px), 1fr))",
                gap: "1rem",
              }}
            >
              {/* Tarjeta 1: Total Tokens */}
              <div
                data-testid="card-total-tokens"
                style={{
                  padding: "1.25rem",
                  backgroundColor: "var(--card)",
                  borderRadius: "var(--radius-md)",
                  border: "1px solid var(--border)",
                  display: "flex",
                  flexDirection: "column",
                  gap: "0.5rem",
                }}
              >
                <span style={{ fontSize: "0.75rem", fontWeight: 600, color: "var(--muted)", textTransform: "uppercase" }}>
                  {t("views.bizTokens.kpis.totalTokens")}
                </span>
                <div style={{ fontSize: "1.75rem", fontWeight: 700, color: "var(--text)" }}>
                  {formatNumber(resumen.total_tokens || resumen.tokens_total, undefined, lang)}
                </div>
                <span style={{ fontSize: "0.75rem", color: "var(--muted)" }}>
                  {t("views.bizTokens.kpis.totalTokensSub", { period: periodo })}
                </span>
              </div>

              {/* Tarjeta 2: Coste Consolidado */}
              <div
                data-testid="card-coste-consolidado"
                style={{
                  padding: "1.25rem",
                  backgroundColor: "var(--card)",
                  borderRadius: "var(--radius-md)",
                  border: "1px solid var(--border)",
                  display: "flex",
                  flexDirection: "column",
                  gap: "0.5rem",
                }}
              >
                <span style={{ fontSize: "0.75rem", fontWeight: 600, color: "var(--muted)", textTransform: "uppercase" }}>
                  {t("views.bizTokens.kpis.consolidatedCost")}
                </span>
                <div style={{ fontSize: "1.75rem", fontWeight: 700, color: "var(--accent)" }}>
                  {formatCurrencyEUR(resumen.coste_consolidado || resumen.coste_total_eur, resumen.moneda, lang)}
                </div>
                <span style={{ fontSize: "0.75rem", color: "var(--muted)" }}>
                  {t("views.bizTokens.kpis.consolidatedCostSub")}
                </span>
              </div>

              {/* Tarjeta 3: Porcentaje Medio de Cuota */}
              <div
                data-testid="card-porcentaje-cuota"
                style={{
                  padding: "1.25rem",
                  backgroundColor: "var(--card)",
                  borderRadius: "var(--radius-md)",
                  border: "1px solid var(--border)",
                  display: "flex",
                  flexDirection: "column",
                  gap: "0.5rem",
                }}
              >
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                  <span style={{ fontSize: "0.75rem", fontWeight: 600, color: "var(--muted)", textTransform: "uppercase" }}>
                    {t("views.bizTokens.kpis.avgQuota")}
                  </span>
                  {resumen.porcentaje_medio_cuota > 100 ? (
                    <Badge variante="error">{t("views.bizTokens.kpis.quotaSaturated")}</Badge>
                  ) : resumen.porcentaje_medio_cuota > 80 ? (
                    <Badge variante="warn">{t("views.bizTokens.kpis.quotaWarn")}</Badge>
                  ) : (
                    <Badge variante="good">{t("views.bizTokens.kpis.quotaNormal")}</Badge>
                  )}
                </div>
                <div style={{ fontSize: "1.75rem", fontWeight: 700, color: "var(--text)" }}>
                  {formatPercent(resumen.porcentaje_medio_cuota || resumen.cuota_consumo_media_pct, {
                    decimals: 1,
                    lang,
                  })}
                </div>
                <span style={{ fontSize: "0.75rem", color: "var(--muted)" }}>
                  {t("views.bizTokens.kpis.avgQuotaSub")}
                </span>
              </div>

              {/* Tarjeta 4: Estado de Facturación */}
              <div
                data-testid="card-estado-facturacion"
                style={{
                  padding: "1.25rem",
                  backgroundColor: "var(--card)",
                  borderRadius: "var(--radius-md)",
                  border: "1px solid var(--border)",
                  display: "flex",
                  flexDirection: "column",
                  gap: "0.5rem",
                }}
              >
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                  <span style={{ fontSize: "0.75rem", fontWeight: 600, color: "var(--muted)", textTransform: "uppercase" }}>
                    {t("views.bizTokens.kpis.billingMatch")}
                  </span>
                  {hayDescuadreFacturacion ? (
                    <Badge variante="error">{t("views.bizTokens.kpis.billingMismatchBadge")}</Badge>
                  ) : (
                    <Badge variante="good">{t("views.bizTokens.kpis.billingMatchedBadge")}</Badge>
                  )}
                </div>
                <div
                  style={{
                    fontSize: "1.25rem",
                    fontWeight: 700,
                    color: hayDescuadreFacturacion ? "var(--bad)" : "var(--good)",
                  }}
                >
                  {hayDescuadreFacturacion
                    ? t("views.bizTokens.kpis.billingMismatchValue")
                    : t("views.bizTokens.kpis.billingMatchedValue")}
                </div>
                <span style={{ fontSize: "0.75rem", color: "var(--muted)" }}>
                  {hayDescuadreFacturacion
                    ? t("views.bizTokens.kpis.billingMismatchSub")
                    : t("views.bizTokens.kpis.billingMatchedSub")}
                </span>
              </div>
            </section>

            {/* Panel de Tendencias y Desglose por Tier (Regla estricta: fable separado de pro) */}
            <section
              role="region"
              aria-labelledby="titulo-panel-tiers"
              aria-label={t("views.bizTokens.tiersPanel.regionLabel")}
              data-testid="panel-graficos-tendencias"
              style={{
                padding: "1.25rem",
                backgroundColor: "var(--card)",
                borderRadius: "var(--radius-md)",
                border: "1px solid var(--border)",
                display: "flex",
                flexDirection: "column",
                gap: "1rem",
              }}
            >
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap" }}>
                <div>
                  <h2 id="titulo-panel-tiers" style={{ margin: 0, fontSize: "1.125rem", fontWeight: 600, color: "var(--text)" }}>
                    {t("views.bizTokens.tiersPanel.title")}
                  </h2>
                  <p style={{ margin: "2px 0 0", fontSize: "0.8125rem", color: "var(--muted)" }}>
                    {t("views.bizTokens.tiersPanel.description")}
                  </p>
                </div>
                <Badge variante="accent">{t("views.bizTokens.tiersPanel.badge")}</Badge>
              </div>

              {/* Barra de Distribución Proporcional */}
              <div
                role="img"
                data-testid="barra-distribucion-proporcional"
                aria-label={t("views.bizTokens.tiersPanel.barAria", {
                  flash: totalesPorTier.pctFlash,
                  pro: totalesPorTier.pctPro,
                  fable: totalesPorTier.pctFable,
                })}
                style={{
                  height: "12px",
                  borderRadius: "6px",
                  display: "flex",
                  overflow: "hidden",
                  backgroundColor: "var(--surface2)",
                }}
              >
                <div
                  data-testid="segmento-flash"
                  title={`Flash: ${formatPercent(totalesPorTier.pctFlash, { decimals: 0, lang })}`}
                  style={{ width: `${totalesPorTier.pctFlash}%`, backgroundColor: "var(--accent)" }}
                />
                <div
                  data-testid="segmento-pro"
                  title={`Pro: ${formatPercent(totalesPorTier.pctPro, { decimals: 0, lang })}`}
                  style={{ width: `${totalesPorTier.pctPro}%`, backgroundColor: "var(--purple)" }}
                />
                <div
                  data-testid="segmento-fable"
                  title={`Fable: ${formatPercent(totalesPorTier.pctFable, { decimals: 0, lang })}`}
                  style={{ width: `${totalesPorTier.pctFable}%`, backgroundColor: "var(--warn)" }}
                />
              </div>

              {/* Tarjetas Visuales por Tier */}
              <div className="kc-grid-cards">
                {/* Tier Flash */}
                <div
                  data-testid="tier-desglose-flash"
                  style={{
                    padding: "1rem",
                    borderRadius: "var(--radius-sm)",
                    backgroundColor: "var(--surface)",
                    borderLeft: "4px solid var(--accent)",
                  }}
                >
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "4px" }}>
                    <strong style={{ fontSize: "0.875rem", color: "var(--text)" }}>
                      {t("views.bizTokens.tiersPanel.flashTitle")}
                    </strong>
                    <Badge variante="accent">{t("views.bizTokens.tiersPanel.flashBadge")}</Badge>
                  </div>
                  <div style={{ fontSize: "1.25rem", fontWeight: 700, color: "var(--text)" }}>
                    {formatNumber(totalesPorTier.flash, undefined, lang)}
                  </div>
                  <div style={{ fontSize: "0.75rem", color: "var(--muted)", marginTop: "2px" }}>
                    {t("views.bizTokens.tiersPanel.volumePct", {
                      pct: formatPercent(totalesPorTier.pctFlash, { decimals: 0, lang }),
                    })}
                  </div>
                </div>

                {/* Tier Pro */}
                <div
                  data-testid="tier-desglose-pro"
                  style={{
                    padding: "1rem",
                    borderRadius: "var(--radius-sm)",
                    backgroundColor: "var(--surface)",
                    borderLeft: "4px solid var(--purple)",
                  }}
                >
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "4px" }}>
                    <strong style={{ fontSize: "0.875rem", color: "var(--text)" }}>
                      {t("views.bizTokens.tiersPanel.proTitle")}
                    </strong>
                    <Badge variante="accent">{t("views.bizTokens.tiersPanel.proBadge")}</Badge>
                  </div>
                  <div style={{ fontSize: "1.25rem", fontWeight: 700, color: "var(--text)" }}>
                    {formatNumber(totalesPorTier.pro, undefined, lang)}
                  </div>
                  <div style={{ fontSize: "0.75rem", color: "var(--muted)", marginTop: "2px" }}>
                    {t("views.bizTokens.tiersPanel.volumePct", {
                      pct: formatPercent(totalesPorTier.pctPro, { decimals: 0, lang }),
                    })}
                  </div>
                </div>

                {/* Tier Fable (OBLIGATORIO SEPARADO) */}
                <div
                  data-testid="tier-desglose-fable"
                  style={{
                    padding: "1rem",
                    borderRadius: "var(--radius-sm)",
                    backgroundColor: "var(--surface)",
                    borderLeft: "4px solid var(--warn)",
                  }}
                >
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "4px" }}>
                    <strong style={{ fontSize: "0.875rem", color: "var(--text)" }}>
                      {t("views.bizTokens.tiersPanel.fableTitle")}
                    </strong>
                    <Badge variante="warn">{t("views.bizTokens.tiersPanel.fableBadge")}</Badge>
                  </div>
                  <div style={{ fontSize: "1.25rem", fontWeight: 700, color: "var(--warn)" }}>
                    {formatNumber(totalesPorTier.fable, undefined, lang)}
                  </div>
                  <div style={{ fontSize: "0.75rem", color: "var(--muted)", marginTop: "2px" }}>
                    {t("views.bizTokens.tiersPanel.volumePctSpecialized", {
                      pct: formatPercent(totalesPorTier.pctFable, { decimals: 0, lang }),
                    })}
                  </div>
                </div>
              </div>

              {/* Tabla Accesible para Cumplimiento A11Y */}
              <div
                aria-live="polite"
                style={{
                  fontSize: "0.75rem",
                  color: "var(--muted)",
                  overflowX: "auto",
                  marginTop: "0.5rem",
                }}
              >
                <table
                  data-testid="tabla-accesible-tiers"
                  style={{ width: "100%", borderCollapse: "collapse", textAlign: "left" }}
                  summary={t("views.bizTokens.tiersPanel.a11yTableSummary")}
                  aria-label={t("views.bizTokens.tiersPanel.a11yTableSummary")}
                >
                  <thead>
                    <tr style={{ borderBottom: "1px solid var(--border)" }}>
                      <th style={{ padding: "4px 8px" }}>{t("views.bizTokens.tiersPanel.a11yColTier")}</th>
                      <th style={{ padding: "4px 8px" }}>{t("views.bizTokens.tiersPanel.a11yColCategory")}</th>
                      <th style={{ padding: "4px 8px", textAlign: "right" }}>
                        {t("views.bizTokens.tiersPanel.a11yColTokens")}
                      </th>
                      <th style={{ padding: "4px 8px", textAlign: "right" }}>
                        {t("views.bizTokens.tiersPanel.a11yColPercent")}
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr>
                      <td style={{ padding: "4px 8px", fontWeight: 600 }}>Flash</td>
                      <td style={{ padding: "4px 8px" }}>{t("views.bizTokens.tiersPanel.catFlash")}</td>
                      <td style={{ padding: "4px 8px", textAlign: "right" }}>
                        {formatNumber(totalesPorTier.flash, undefined, lang)}
                      </td>
                      <td style={{ padding: "4px 8px", textAlign: "right" }}>
                        {formatPercent(totalesPorTier.pctFlash, { decimals: 0, lang })}
                      </td>
                    </tr>
                    <tr>
                      <td style={{ padding: "4px 8px", fontWeight: 600 }}>Pro</td>
                      <td style={{ padding: "4px 8px" }}>{t("views.bizTokens.tiersPanel.catPro")}</td>
                      <td style={{ padding: "4px 8px", textAlign: "right" }}>
                        {formatNumber(totalesPorTier.pro, undefined, lang)}
                      </td>
                      <td style={{ padding: "4px 8px", textAlign: "right" }}>
                        {formatPercent(totalesPorTier.pctPro, { decimals: 0, lang })}
                      </td>
                    </tr>
                    <tr>
                      <td style={{ padding: "4px 8px", fontWeight: 600, color: "var(--warn)" }}>Fable</td>
                      <td style={{ padding: "4px 8px", color: "var(--warn)" }}>
                        {t("views.bizTokens.tiersPanel.catFable")}
                      </td>
                      <td style={{ padding: "4px 8px", textAlign: "right", color: "var(--warn)" }}>
                        {formatNumber(totalesPorTier.fable, undefined, lang)}
                      </td>
                      <td style={{ padding: "4px 8px", textAlign: "right", color: "var(--warn)" }}>
                        {formatPercent(totalesPorTier.pctFable, { decimals: 0, lang })}
                      </td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </section>

            {/* Tabla Densa Paginada de Consumo */}
            <section
              aria-labelledby="titulo-tabla-consumo"
              style={{
                backgroundColor: "var(--card)",
                borderRadius: "var(--radius-md)",
                border: "1px solid var(--border)",
                overflowX: "clip",
              }}
            >
              <div
                style={{
                  padding: "1rem 1.25rem",
                  borderBottom: "1px solid var(--border)",
                  display: "flex",
                  justifyContent: "space-between",
                  alignItems: "center",
                  flexWrap: "wrap",
                  gap: "0.5rem",
                }}
              >
                <div>
                  <h2 id="titulo-tabla-consumo" style={{ margin: 0, fontSize: "1rem", fontWeight: 600, color: "var(--text)" }}>
                    {agruparPor === "cliente"
                      ? t("views.bizTokens.table.titleByClient")
                      : agruparPor === "tier"
                      ? t("views.bizTokens.table.titleByTier")
                      : t("views.bizTokens.table.titleByDay")}
                  </h2>
                  <div style={{ display: "flex", gap: "0.5rem", alignItems: "center", marginTop: "0.25rem", flexWrap: "wrap" }}>
                    <span style={{ fontSize: "0.75rem", color: "var(--muted)" }}>
                      {t("views.bizTokens.table.showingRecords", {
                        count: data.items.length,
                        total: data.total,
                      })}
                    </span>
                    <Badge variante="neutro" style={{ fontSize: "0.75rem" }}>
                      {t("views.bizTokens.table.cycleBadge", { cycle: data.ciclo || periodo })}
                    </Badge>
                  </div>
                </div>

                <div className="kc-toolbar-actions">
                  {data.alguna_enmascarada && (
                    <Badge variante="warn">
                      {t("views.bizTokens.table.maskedBanner")}
                    </Badge>
                  )}
                  <Boton
                    variante="ghost"
                    tamano="sm"
                    className="kc-columns-toggle"
                    data-testid="toggle-columnas-completas"
                    aria-pressed={mostrarTodasColumnas}
                    aria-label={t("components.table.toggleColumnsAria")}
                    onClick={() => setMostrarTodasColumnas((prev) => !prev)}
                  >
                    {mostrarTodasColumnas
                      ? t("components.table.compactColumns")
                      : t("components.table.showAllColumns")}
                  </Boton>
                </div>
              </div>

              {/* Renderizado de Tabla Semántica A11Y */}
              <Tabla densidad="alta" mostrarTodasColumnas={mostrarTodasColumnas}>
                <TablaEncabezado>
                  <TablaFila>
                    {agruparPor === "cliente" ? (
                      <>
                        <TablaCeldaEncabezado scope="col" fija>{t("views.bizTokens.table.colClient")}</TablaCeldaEncabezado>
                        <TablaCeldaEncabezado scope="col" prioridad="media">{t("views.bizTokens.table.colPlan")}</TablaCeldaEncabezado>
                        <TablaCeldaEncabezado scope="col" prioridad="baja" style={{ textAlign: "right" }}>
                          {t("views.bizTokens.table.colTokensIn")}
                        </TablaCeldaEncabezado>
                        <TablaCeldaEncabezado scope="col" prioridad="baja" style={{ textAlign: "right" }}>
                          {t("views.bizTokens.table.colTokensOut")}
                        </TablaCeldaEncabezado>
                        <TablaCeldaEncabezado scope="col" style={{ textAlign: "right" }}>
                          {t("views.bizTokens.table.colTokensTotal")}
                        </TablaCeldaEncabezado>
                        <TablaCeldaEncabezado scope="col" prioridad="baja">{t("views.bizTokens.table.colTiers")}</TablaCeldaEncabezado>
                        <TablaCeldaEncabezado scope="col" style={{ textAlign: "right" }}>
                          {t("views.bizTokens.table.colEstCost")}
                        </TablaCeldaEncabezado>
                        <TablaCeldaEncabezado scope="col" prioridad="media">{t("views.bizTokens.table.colUsageQuota")}</TablaCeldaEncabezado>
                        <TablaCeldaEncabezado scope="col" prioridad="baja" style={{ textAlign: "center" }}>
                          {t("views.bizTokens.table.colBilling")}
                        </TablaCeldaEncabezado>
                        <TablaCeldaEncabezado scope="col" prioridad="media" style={{ textAlign: "center" }}>
                          {t("views.bizTokens.table.colPrivacy")}
                        </TablaCeldaEncabezado>
                      </>
                    ) : agruparPor === "tier" ? (
                      <>
                        <TablaCeldaEncabezado scope="col" fija>{t("views.bizTokens.table.colTierModel")}</TablaCeldaEncabezado>
                        <TablaCeldaEncabezado scope="col" prioridad="baja" style={{ textAlign: "right" }}>
                          {t("views.bizTokens.table.colTokensIn")}
                        </TablaCeldaEncabezado>
                        <TablaCeldaEncabezado scope="col" prioridad="baja" style={{ textAlign: "right" }}>
                          {t("views.bizTokens.table.colTokensOut")}
                        </TablaCeldaEncabezado>
                        <TablaCeldaEncabezado scope="col" style={{ textAlign: "right" }}>
                          {t("views.bizTokens.table.colTokensTotal")}
                        </TablaCeldaEncabezado>
                        <TablaCeldaEncabezado scope="col" style={{ textAlign: "right" }}>
                          {t("views.bizTokens.table.colEstimatedCost")}
                        </TablaCeldaEncabezado>
                        <TablaCeldaEncabezado scope="col" prioridad="media" style={{ textAlign: "center" }}>
                          {t("views.bizTokens.table.colBilling")}
                        </TablaCeldaEncabezado>
                      </>
                    ) : (
                      <>
                        <TablaCeldaEncabezado scope="col" fija>{t("views.bizTokens.table.colDate")}</TablaCeldaEncabezado>
                        <TablaCeldaEncabezado scope="col" prioridad="baja" style={{ textAlign: "right" }}>
                          {t("views.bizTokens.table.colTokensIn")}
                        </TablaCeldaEncabezado>
                        <TablaCeldaEncabezado scope="col" prioridad="baja" style={{ textAlign: "right" }}>
                          {t("views.bizTokens.table.colTokensOut")}
                        </TablaCeldaEncabezado>
                        <TablaCeldaEncabezado scope="col" style={{ textAlign: "right" }}>
                          {t("views.bizTokens.table.colTokensTotal")}
                        </TablaCeldaEncabezado>
                        <TablaCeldaEncabezado scope="col" prioridad="baja">{t("views.bizTokens.table.colTiers")}</TablaCeldaEncabezado>
                        <TablaCeldaEncabezado scope="col" style={{ textAlign: "right" }}>
                          {t("views.bizTokens.table.colEstimatedCost")}
                        </TablaCeldaEncabezado>
                        <TablaCeldaEncabezado scope="col" prioridad="media" style={{ textAlign: "center" }}>
                          {t("views.bizTokens.table.colBilling")}
                        </TablaCeldaEncabezado>
                      </>
                    )}
                  </TablaFila>
                </TablaEncabezado>

                <TablaCuerpo>
                  {data.items.map((item, idx) => {
                    const cuadra = item.cuadra_con_facturacion !== false;
                    const cuota = item.cuota_pct ?? item.porcentaje_consumido ?? 0;

                    if (agruparPor === "cliente") {
                      const tenantId = item.tenant_id || item.clave;
                      const esEnmascarado = item.enmascarado ?? true;

                      return (
                        <TablaFila key={tenantId || idx} data-testid={`fila-cliente-${tenantId}`}>
                          {/* Organización y Razón Social */}
                          <TablaCelda fija>
                            <div style={{ display: "flex", flexDirection: "column", gap: "2px" }}>
                              <Link
                                to={`/business/customers/${tenantId}`}
                                style={{
                                  fontWeight: 600,
                                  color: "var(--accent)",
                                  textDecoration: "none",
                                  fontSize: "0.875rem",
                                }}
                              >
                                {tenantId}
                              </Link>
                              <span style={{ fontSize: "0.8125rem", color: "var(--text)" }}>
                                {item.razon_social || "A•••• S.L."}
                              </span>
                            </div>
                          </TablaCelda>

                          {/* Plan Comercial */}
                          <TablaCelda prioridad="media">
                            <Badge variante="accent">{item.plan || "starter"}</Badge>
                          </TablaCelda>

                          {/* Tokens In */}
                          <TablaCelda prioridad="baja" style={{ textAlign: "right", fontFamily: "monospace", fontSize: "0.8125rem" }}>
                            {formatNumber(item.tokens_input ?? item.tokens_in, undefined, lang)}
                          </TablaCelda>

                          {/* Tokens Out */}
                          <TablaCelda prioridad="baja" style={{ textAlign: "right", fontFamily: "monospace", fontSize: "0.8125rem" }}>
                            {formatNumber(item.tokens_output ?? item.tokens_out, undefined, lang)}
                          </TablaCelda>

                          {/* Tokens Total */}
                          <TablaCelda style={{ textAlign: "right", fontFamily: "monospace", fontWeight: 700, fontSize: "0.875rem" }}>
                            {formatNumber(item.tokens_total, undefined, lang)}
                          </TablaCelda>

                          {/* Desglose por Tier */}
                          <TablaCelda prioridad="baja">
                            <div style={{ display: "flex", flexDirection: "column", gap: "2px", fontSize: "0.75rem" }}>
                              <span>
                                Flash: <strong>{formatNumber(item.por_tier?.flash ?? 0, undefined, lang)}</strong>
                              </span>
                              <span>
                                Pro: <strong>{formatNumber(item.por_tier?.pro ?? 0, undefined, lang)}</strong>
                              </span>
                              <span style={{ color: "var(--warn)" }}>
                                Fable: <strong>{formatNumber(item.por_tier?.fable ?? 0, undefined, lang)}</strong>
                              </span>
                            </div>
                          </TablaCelda>

                          {/* Coste Estimado EUR */}
                          <TablaCelda style={{ textAlign: "right", fontWeight: 600, color: "var(--accent)" }}>
                            {formatCurrencyEUR(item.coste_estimado_eur ?? item.coste, "EUR", lang)}
                          </TablaCelda>

                          {/* Cuota de Uso */}
                          <TablaCelda prioridad="media">
                            <div style={{ display: "flex", flexDirection: "column", gap: "4px", minWidth: "100px" }}>
                              <div style={{ display: "flex", justifyContent: "space-between", fontSize: "0.75rem" }}>
                                <span>{formatPercent(cuota, { decimals: 1, lang })}</span>
                                {cuota > 100 ? (
                                  <span style={{ color: "var(--bad)", fontWeight: 700 }}>
                                    {t("views.bizTokens.table.quotaExceeded")}
                                  </span>
                                ) : cuota > 80 ? (
                                  <span style={{ color: "var(--warn)", fontWeight: 700 }}>
                                    {t("views.bizTokens.table.quotaAlert")}
                                  </span>
                                ) : null}
                              </div>
                              <div
                                style={{
                                  height: "6px",
                                  borderRadius: "3px",
                                  backgroundColor: "var(--surface2)",
                                  overflow: "hidden",
                                }}
                              >
                                <div
                                  style={{
                                    width: `${Math.min(cuota, 100)}%`,
                                    height: "100%",
                                    backgroundColor:
                                      cuota > 100
                                        ? "var(--bad)"
                                        : cuota > 80
                                        ? "var(--warn)"
                                        : "var(--good)",
                                  }}
                                />
                              </div>
                            </div>
                          </TablaCelda>

                          {/* Cuadre Facturación */}
                          <TablaCelda prioridad="baja" style={{ textAlign: "center" }}>
                            {cuadra ? (
                              <Badge variante="good" title={t("views.bizTokens.table.matchOkTitle")}>
                                {t("views.bizTokens.table.matchOk")}
                              </Badge>
                            ) : (
                              <Badge variante="error" title={t("views.bizTokens.table.matchErrTitle")}>
                                {t("views.bizTokens.table.matchErr")}
                              </Badge>
                            )}
                          </TablaCelda>

                          {/* Privacidad E6 y Concesión */}
                          <TablaCelda prioridad="media" style={{ textAlign: "center" }}>
                            {esEnmascarado ? (
                              <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: "4px" }}>
                                <Badge variante="neutro">{t("common.states.masked")}</Badge>
                                <Boton
                                  variante="secondary"
                                  tamano="sm"
                                  onClick={() => handleAbrirConcesion(tenantId, item.razon_social)}
                                  data-testid={`btn-concesion-${tenantId}`}
                                  style={{ fontSize: "0.6875rem", padding: "2px 6px" }}
                                >
                                  {t("common.actions.requestAccess")}
                                </Boton>
                              </div>
                            ) : (
                              <Badge variante="good">{t("common.states.unmasked")}</Badge>
                            )}
                          </TablaCelda>
                        </TablaFila>
                      );
                    }

                    if (agruparPor === "tier") {
                      const nombreTier = item.tier || item.clave;
                      const esFable = nombreTier === "fable";

                      return (
                        <TablaFila key={nombreTier} data-testid={`fila-tier-${nombreTier}`}>
                          <TablaCelda fija>
                            <div style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
                              <Badge variante={esFable ? "warn" : "accent"}>{nombreTier}</Badge>
                              {esFable && (
                                <span style={{ fontSize: "0.75rem", color: "var(--warn)" }}>
                                  {t("views.bizTokens.table.fableNote")}
                                </span>
                              )}
                            </div>
                          </TablaCelda>
                          <TablaCelda prioridad="baja" style={{ textAlign: "right", fontFamily: "monospace" }}>
                            {formatNumber(item.tokens_input ?? item.tokens_in, undefined, lang)}
                          </TablaCelda>
                          <TablaCelda prioridad="baja" style={{ textAlign: "right", fontFamily: "monospace" }}>
                            {formatNumber(item.tokens_output ?? item.tokens_out, undefined, lang)}
                          </TablaCelda>
                          <TablaCelda style={{ textAlign: "right", fontFamily: "monospace", fontWeight: 700 }}>
                            {formatNumber(item.tokens_total, undefined, lang)}
                          </TablaCelda>
                          <TablaCelda style={{ textAlign: "right", fontWeight: 600, color: "var(--accent)" }}>
                            {formatCurrencyEUR(item.coste_estimado_eur ?? item.coste, "EUR", lang)}
                          </TablaCelda>
                          <TablaCelda prioridad="media" style={{ textAlign: "center" }}>
                            <Badge variante="good">{t("views.bizTokens.table.reconciledBadge")}</Badge>
                          </TablaCelda>
                        </TablaFila>
                      );
                    }

                    // Agrupación por día
                    const diaStr = item.dia || item.clave;
                    return (
                      <TablaFila key={diaStr} data-testid={`fila-dia-${diaStr}`}>
                        <TablaCelda fija style={{ fontWeight: 600 }}>{diaStr}</TablaCelda>
                        <TablaCelda prioridad="baja" style={{ textAlign: "right", fontFamily: "monospace" }}>
                          {formatNumber(item.tokens_input ?? item.tokens_in, undefined, lang)}
                        </TablaCelda>
                        <TablaCelda prioridad="baja" style={{ textAlign: "right", fontFamily: "monospace" }}>
                          {formatNumber(item.tokens_output ?? item.tokens_out, undefined, lang)}
                        </TablaCelda>
                        <TablaCelda style={{ textAlign: "right", fontFamily: "monospace", fontWeight: 700 }}>
                          {formatNumber(item.tokens_total, undefined, lang)}
                        </TablaCelda>
                        <TablaCelda prioridad="baja">
                          <div style={{ display: "flex", gap: "0.5rem", fontSize: "0.75rem" }}>
                            <span>
                              F: <strong>{formatNumber(item.por_tier?.flash ?? 0, undefined, lang)}</strong>
                            </span>
                            <span>
                              P: <strong>{formatNumber(item.por_tier?.pro ?? 0, undefined, lang)}</strong>
                            </span>
                            <span style={{ color: "var(--warn)" }}>
                              Fa: <strong>{formatNumber(item.por_tier?.fable ?? 0, undefined, lang)}</strong>
                            </span>
                          </div>
                        </TablaCelda>
                        <TablaCelda style={{ textAlign: "right", fontWeight: 600, color: "var(--accent)" }}>
                          {formatCurrencyEUR(item.coste_estimado_eur ?? item.coste, "EUR", lang)}
                        </TablaCelda>
                        <TablaCelda prioridad="media" style={{ textAlign: "center" }}>
                          <Badge variante="good">{t("views.bizTokens.table.reconciledBadge")}</Badge>
                        </TablaCelda>
                      </TablaFila>
                    );
                  })}
                </TablaCuerpo>
              </Tabla>

              {/* Barra de Paginación Transversal */}
              <div
                className="kc-pagination"
                style={{
                  padding: "0.75rem 1.25rem",
                  borderTop: "1px solid var(--border)",
                  fontSize: "0.8125rem",
                  color: "var(--muted)",
                }}
              >
                <div className="kc-pagination-controls">
                  <span>{t("common.pagination.rowsPerPage")}</span>
                  <select
                    data-testid="select-page-size"
                    aria-label={t("common.pagination.recordsPerPage")}
                    value={pageSize}
                    onChange={(e) => handleCambioFiltro("page_size", e.target.value)}
                    style={{
                      backgroundColor: "var(--surface)",
                      color: "var(--text)",
                      border: "1px solid var(--border)",
                      borderRadius: "var(--radius-sm)",
                      padding: "2px 6px",
                      fontSize: "0.8125rem",
                    }}
                  >
                    <option value="10">10</option>
                    <option value="25">25</option>
                    <option value="50">50</option>
                    <option value="100">100</option>
                  </select>
                  <span>
                    {t("common.pagination.pageOfParens", {
                      page: data.page,
                      pages: Math.max(data.pages, 1),
                    })}
                  </span>
                </div>

                <div style={{ display: "flex", gap: "0.5rem" }}>
                  <Boton
                    variante="secondary"
                    tamano="sm"
                    disabled={data.page <= 1}
                    onClick={() => handleCambioFiltro("page", (data.page - 1).toString())}
                    data-testid="btn-pagina-anterior"
                  >
                    {t("common.pagination.previous")}
                  </Boton>
                  <Boton
                    variante="secondary"
                    tamano="sm"
                    disabled={data.page >= data.pages}
                    onClick={() => handleCambioFiltro("page", (data.page + 1).toString())}
                    data-testid="btn-pagina-siguiente"
                  >
                    {t("common.pagination.next")}
                  </Boton>
                </div>
              </div>
            </section>
          </>
        )}
      </ContenedorEstado>

      {/* Modal de Concesión Contextual E6 */}
      <SolicitudConcesionModal
        abierto={modalConcesionAbierto}
        alCerrar={handleCerrarConcesion}
        tenantId={concesionTenantId}
        razonSocial={concesionRazonSocial}
        onConcesionConcedida={() => {
          refetch();
        }}
      />
    </div>
  );
};
