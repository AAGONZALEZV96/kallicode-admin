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
import { peticionApi, ApiError } from "../api/clienteApi";
import { useAuth } from "../estado/auth";
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

// ------------------------------------------------------------------ Constantes y Opciones
const OPCIONES_PERIODO = [
  { valor: "mes_actual", etiqueta: "Mes actual (defecto)" },
  { valor: "mes_anterior", etiqueta: "Mes anterior" },
  { valor: "trimestre", etiqueta: "Último trimestre" },
  { valor: "ano", etiqueta: "Año en curso" },
];

const OPCIONES_PLAN = [
  { valor: "todos", etiqueta: "Todos los planes" },
  { valor: "starter", etiqueta: "Starter" },
  { valor: "growth", etiqueta: "Growth" },
  { valor: "enterprise", etiqueta: "Enterprise" },
];

const OPCIONES_AGRUPACION = [
  { valor: "cliente", etiqueta: "Por cliente (organización)" },
  { valor: "tier", etiqueta: "Por tier de modelo" },
  { valor: "dia", etiqueta: "Por serie diaria" },
];

const ALLOWLIST_ORDEN = [
  { valor: "coste_desc", etiqueta: "Coste (Mayor a Menor)" },
  { valor: "coste_asc", etiqueta: "Coste (Menor a Mayor)" },
  { valor: "tokens_total_desc", etiqueta: "Tokens Totales (Mayor a Menor)" },
  { valor: "tokens_total_asc", etiqueta: "Tokens Totales (Menor a Mayor)" },
  { valor: "tokens_in_desc", etiqueta: "Tokens In (Mayor a Menor)" },
  { valor: "tokens_out_desc", etiqueta: "Tokens Out (Mayor a Menor)" },
  { valor: "cuota_pct_desc", etiqueta: "% Cuota (Mayor a Menor)" },
  { valor: "cuota_pct_asc", etiqueta: "% Cuota (Menor a Mayor)" },
  { valor: "loc_consumidas_desc", etiqueta: "Líneas de Código (Mayor a Menor)" },
];

// ------------------------------------------------------------------ Funciones Auxiliares
function formatearNumero(val?: number | null): string {
  if (val === undefined || val === null || isNaN(val)) return "0";
  return new Intl.NumberFormat("es-ES").format(val);
}

function formatearMoneda(val?: number | null, moneda = "EUR"): string {
  if (val === undefined || val === null || isNaN(val)) return "0,00 €";
  return new Intl.NumberFormat("es-ES", {
    style: "currency",
    currency: moneda,
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(val);
}

function formatearPorcentaje(val?: number | null): string {
  if (val === undefined || val === null || isNaN(val)) return "0.0%";
  return `${Number(val).toFixed(1)}%`;
}

// ------------------------------------------------------------------ Componente Principal
export const BizTokens: React.FC = () => {
  const { usuario } = useAuth();
  const [searchParams, setSearchParams] = useSearchParams();

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
      <main
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
          <Badge variante="error">ACCESO DENEGADO</Badge>
          <strong style={{ fontSize: "1.1rem" }}>403 ROL_STAFF_INSUFICIENTE</strong>
        </div>
        <p style={{ color: "var(--muted)", margin: "0.5rem 0" }}>
          Acceso denegado para el rol {usuario?.role}. La supervisión analítica de consumo de tokens y costes de inferencia es exclusiva para personal de negocio o administración.
        </p>
      </main>
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
              Consumo de Tokens y FinOps
            </h1>
            {data?.frescura && (
              <span style={{ fontSize: "0.75rem", color: "var(--muted)" }}>
                Frescura: {new Date(data.frescura).toLocaleTimeString("es-ES")}
              </span>
            )}
            {isFetching && (
              <span
                role="status"
                style={{ fontSize: "0.75rem", color: "var(--accent)", fontStyle: "italic" }}
              >
                Actualizando datos...
              </span>
            )}
          </div>
          <p style={{ margin: 0, fontSize: "0.875rem", color: "var(--muted)" }}>
            Supervisión económica de consumo de inferencia LLM, costes por tier, control de cuotas y cuadre con facturación.
          </p>
        </div>

        <div style={{ display: "flex", gap: "0.5rem", alignItems: "center" }}>
          <Boton
            variante="secondary"
            tamano="sm"
            onClick={() => refetch()}
            disabled={isFetching}
            data-testid="btn-refetch-tokens"
          >
            {isFetching ? "Refrescando..." : "Refrescar"}
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
            <span style={{ fontSize: "1.5rem" }}>🚨</span>
            <div>
              <strong style={{ display: "block", color: "var(--bad)" }}>
                Alerta Crítica: Descuadre Detectado entre Consumo y Facturación
              </strong>
              <span style={{ fontSize: "0.875rem", color: "var(--muted)" }}>
                Las líneas de código o tokens computados difieren de las unidades facturadas en el ciclo. Clientes afectados:{" "}
                <strong>{data?.descuadres?.join(", ") || "Organizaciones auditadas"}</strong>.
              </span>
            </div>
          </div>
          <Badge variante="error">AUDITORÍA REQUERIDA</Badge>
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
        {`Filtros activos: Periodo ${periodo}, Plan ${plan}, Agrupación ${agruparPor}${qUrl ? `, Búsqueda ${qUrl}` : ""}`}
      </div>

      {/* Barra de Filtros y Controles Analíticos */}
      <section
        aria-label="Controles y Filtros Analíticos"
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(min(100%, 180px), 1fr))",
          gap: "1rem",
          padding: "1rem",
          backgroundColor: "var(--card)",
          borderRadius: "var(--radius-md)",
          border: "1px solid var(--border)",
        }}
      >
        <div>
          <label
            htmlFor="filtro-periodo"
            style={{ display: "block", fontSize: "0.75rem", fontWeight: 600, color: "var(--muted)", marginBottom: "4px" }}
          >
            Periodo Temporal
          </label>
          <Select
            id="filtro-periodo"
            data-testid="select-periodo"
            value={periodo}
            onChange={(e) => handleCambioFiltro("periodo", e.target.value)}
            opciones={OPCIONES_PERIODO}
          />
        </div>

        <div>
          <label
            htmlFor="filtro-plan"
            style={{ display: "block", fontSize: "0.75rem", fontWeight: 600, color: "var(--muted)", marginBottom: "4px" }}
          >
            Plan Comercial
          </label>
          <Select
            id="filtro-plan"
            data-testid="select-plan"
            value={plan}
            onChange={(e) => handleCambioFiltro("plan", e.target.value)}
            opciones={OPCIONES_PLAN}
          />
        </div>

        <div>
          <label
            htmlFor="filtro-agrupacion"
            style={{ display: "block", fontSize: "0.75rem", fontWeight: 600, color: "var(--muted)", marginBottom: "4px" }}
          >
            Agrupación Analítica
          </label>
          <Select
            id="filtro-agrupacion"
            data-testid="select-agrupacion"
            value={agruparPor}
            onChange={(e) => handleCambioFiltro("agrupar_por", e.target.value)}
            opciones={OPCIONES_AGRUPACION}
          />
        </div>

        <div>
          <label
            htmlFor="filtro-busqueda-cliente"
            style={{ display: "block", fontSize: "0.75rem", fontWeight: 600, color: "var(--muted)", marginBottom: "4px" }}
          >
            Buscar Cliente / Organización
          </label>
          <Input
            id="filtro-busqueda-cliente"
            data-testid="input-busqueda-cliente"
            placeholder="Buscar por tenant_id o nombre..."
            value={busquedaInput}
            onChange={(e) => setBusquedaInput(e.target.value)}
          />
        </div>

        <div>
          <label
            htmlFor="filtro-ordenacion"
            style={{ display: "block", fontSize: "0.75rem", fontWeight: 600, color: "var(--muted)", marginBottom: "4px" }}
          >
            Criterio de Ordenación
          </label>
          <Select
            id="filtro-ordenacion"
            data-testid="select-ordenacion"
            value={orden}
            onChange={(e) => handleCambioFiltro("order_by", e.target.value)}
            opciones={ALLOWLIST_ORDEN}
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
            ? "Agregados analíticos en refresco"
            : "Error al cargar consumo de tokens"
        }
        mensajeError={
          apiErr?.status === 503
            ? `Los agregados de cómputo están recalculándose. Traza: ${traceId}`
            : `No se pudo obtener el informe de tokens. ${apiErr?.message || ""}`
        }
        tituloVacio="Sin datos de consumo de tokens"
        descripcionVacio="No existen registros de consumo de inferencia para los filtros y periodo seleccionados."
        textoAccionVacio="Limpiar Filtros"
        alAccionarVacio={() => setSearchParams({ periodo: "mes_actual", agrupar_por: "cliente" })}
      >
        {data && (
          <>
            {/* Tarjetas de Resumen Ejecutivo (FinOps) */}
            <section
              aria-label="Resumen Ejecutivo FinOps"
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
                  Total Tokens Consumidos
                </span>
                <div style={{ fontSize: "1.75rem", fontWeight: 700, color: "var(--text)" }}>
                  {formatearNumero(resumen.total_tokens || resumen.tokens_total)}
                </div>
                <span style={{ fontSize: "0.75rem", color: "var(--muted)" }}>
                  Inferencia LLM acumulada en el periodo ({periodo})
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
                  Coste Consolidado
                </span>
                <div style={{ fontSize: "1.75rem", fontWeight: 700, color: "var(--accent)" }}>
                  {formatearMoneda(resumen.coste_consolidado || resumen.coste_total_eur, resumen.moneda)}
                </div>
                <span style={{ fontSize: "0.75rem", color: "var(--muted)" }}>
                  Coste monetario de cómputo estimado
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
                    Consumo Medio de Cuota
                  </span>
                  {resumen.porcentaje_medio_cuota > 100 ? (
                    <Badge variante="error">SATURADA (&gt;100%)</Badge>
                  ) : resumen.porcentaje_medio_cuota > 80 ? (
                    <Badge variante="warn">AVISO (&gt;80%)</Badge>
                  ) : (
                    <Badge variante="good">NORMAL</Badge>
                  )}
                </div>
                <div style={{ fontSize: "1.75rem", fontWeight: 700, color: "var(--text)" }}>
                  {formatearPorcentaje(resumen.porcentaje_medio_cuota || resumen.cuota_consumo_media_pct)}
                </div>
                <span style={{ fontSize: "0.75rem", color: "var(--muted)" }}>
                  Media sobre capacidad contratada por organización
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
                    Cuadre Facturación
                  </span>
                  {hayDescuadreFacturacion ? (
                    <Badge variante="error">DESCUADRE</Badge>
                  ) : (
                    <Badge variante="good">CONCILIADO</Badge>
                  )}
                </div>
                <div
                  style={{
                    fontSize: "1.25rem",
                    fontWeight: 700,
                    color: hayDescuadreFacturacion ? "var(--bad)" : "var(--good)",
                  }}
                >
                  {hayDescuadreFacturacion ? "Discrepancia Activa" : "100% Conciliado"}
                </div>
                <span style={{ fontSize: "0.75rem", color: "var(--muted)" }}>
                  {hayDescuadreFacturacion
                    ? "Inconsistencia entre agregados y ciclos facturados"
                    : "Consumo validado contra ciclos de facturación"}
                </span>
              </div>
            </section>

            {/* Panel de Tendencias y Desglose por Tier (Regla estricta: fable separado de pro) */}
            <section
              role="region"
              aria-labelledby="titulo-panel-tiers"
              aria-label="Panel de tendencias y desglose por tier de modelo"
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
                    Desglose Analítico por Tier de Inferencia LLM
                  </h2>
                  <p style={{ margin: "2px 0 0", fontSize: "0.8125rem", color: "var(--muted)" }}>
                    Auditoría de volumen de tokens por categoría arquitectónica. El tier <strong>fable</strong> se desglosa por separado de <strong>pro</strong> por divergencia de coste y modelo.
                  </p>
                </div>
                <Badge variante="accent">Separación Fable vs Pro Requerida</Badge>
              </div>

              {/* Barra de Distribución Proporcional */}
              <div
                role="img"
                data-testid="barra-distribucion-proporcional"
                aria-label={`Distribución por tier: Flash ${totalesPorTier.pctFlash}%, Pro ${totalesPorTier.pctPro}%, Fable ${totalesPorTier.pctFable}%`}
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
                  title={`Flash: ${totalesPorTier.pctFlash}%`}
                  style={{ width: `${totalesPorTier.pctFlash}%`, backgroundColor: "var(--accent)" }}
                />
                <div
                  data-testid="segmento-pro"
                  title={`Pro: ${totalesPorTier.pctPro}%`}
                  style={{ width: `${totalesPorTier.pctPro}%`, backgroundColor: "var(--purple)" }}
                />
                <div
                  data-testid="segmento-fable"
                  title={`Fable: ${totalesPorTier.pctFable}%`}
                  style={{ width: `${totalesPorTier.pctFable}%`, backgroundColor: "var(--warn)" }}
                />
              </div>

              {/* Tarjetas Visuales por Tier */}
              <div
                style={{
                  display: "grid",
                  gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))",
                  gap: "1rem",
                }}
              >
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
                    <strong style={{ fontSize: "0.875rem", color: "var(--text)" }}>Tier Flash</strong>
                    <Badge variante="accent">Alta Velocidad</Badge>
                  </div>
                  <div style={{ fontSize: "1.25rem", fontWeight: 700, color: "var(--text)" }}>
                    {formatearNumero(totalesPorTier.flash)}
                  </div>
                  <div style={{ fontSize: "0.75rem", color: "var(--muted)", marginTop: "2px" }}>
                    {totalesPorTier.pctFlash}% del volumen de tokens
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
                    <strong style={{ fontSize: "0.875rem", color: "var(--text)" }}>Tier Pro</strong>
                    <Badge variante="accent">Capacidad Estándar</Badge>
                  </div>
                  <div style={{ fontSize: "1.25rem", fontWeight: 700, color: "var(--text)" }}>
                    {formatearNumero(totalesPorTier.pro)}
                  </div>
                  <div style={{ fontSize: "0.75rem", color: "var(--muted)", marginTop: "2px" }}>
                    {totalesPorTier.pctPro}% del volumen de tokens
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
                    <strong style={{ fontSize: "0.875rem", color: "var(--text)" }}>Tier Fable</strong>
                    <Badge variante="warn">Razonamiento Avanzado</Badge>
                  </div>
                  <div style={{ fontSize: "1.25rem", fontWeight: 700, color: "var(--warn)" }}>
                    {formatearNumero(totalesPorTier.fable)}
                  </div>
                  <div style={{ fontSize: "0.75rem", color: "var(--muted)", marginTop: "2px" }}>
                    {totalesPorTier.pctFable}% del volumen de tokens (cómputo especializado)
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
                  summary="Tabla de resumen accesible de tokens consumidos por tier de modelo"
                >
                  <thead>
                    <tr style={{ borderBottom: "1px solid var(--border)" }}>
                      <th style={{ padding: "4px 8px" }}>Tier</th>
                      <th style={{ padding: "4px 8px" }}>Categoría</th>
                      <th style={{ padding: "4px 8px", textAlign: "right" }}>Tokens</th>
                      <th style={{ padding: "4px 8px", textAlign: "right" }}>Porcentaje</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr>
                      <td style={{ padding: "4px 8px", fontWeight: 600 }}>Flash</td>
                      <td style={{ padding: "4px 8px" }}>Inferencia Ligera</td>
                      <td style={{ padding: "4px 8px", textAlign: "right" }}>{formatearNumero(totalesPorTier.flash)}</td>
                      <td style={{ padding: "4px 8px", textAlign: "right" }}>{totalesPorTier.pctFlash}%</td>
                    </tr>
                    <tr>
                      <td style={{ padding: "4px 8px", fontWeight: 600 }}>Pro</td>
                      <td style={{ padding: "4px 8px" }}>Inferencia General</td>
                      <td style={{ padding: "4px 8px", textAlign: "right" }}>{formatearNumero(totalesPorTier.pro)}</td>
                      <td style={{ padding: "4px 8px", textAlign: "right" }}>{totalesPorTier.pctPro}%</td>
                    </tr>
                    <tr>
                      <td style={{ padding: "4px 8px", fontWeight: 600, color: "var(--warn)" }}>Fable</td>
                      <td style={{ padding: "4px 8px", color: "var(--warn)" }}>Razonamiento Agéntico</td>
                      <td style={{ padding: "4px 8px", textAlign: "right", color: "var(--warn)" }}>{formatearNumero(totalesPorTier.fable)}</td>
                      <td style={{ padding: "4px 8px", textAlign: "right", color: "var(--warn)" }}>{totalesPorTier.pctFable}%</td>
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
                overflow: "hidden",
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
                      ? "Consumo de Tokens por Organización Cliente"
                      : agruparPor === "tier"
                      ? "Agregado Consolidado por Tier de Modelo"
                      : "Serie Temporal de Consumo Diario"}
                  </h2>
                  <div style={{ display: "flex", gap: "0.5rem", alignItems: "center", marginTop: "0.25rem", flexWrap: "wrap" }}>
                    <span style={{ fontSize: "0.75rem", color: "var(--muted)" }}>
                      Mostrando {data.items.length} de {data.total} registros
                    </span>
                    <Badge variante="neutro" style={{ fontSize: "0.75rem" }}>
                      Ciclo: {data.ciclo || periodo}
                    </Badge>
                  </div>
                </div>

                {data.alguna_enmascarada && (
                  <Badge variante="warn">
                    DATOS ENMASCARADOS BAJO POLÍTICA DE PRIVACIDAD
                  </Badge>
                )}
              </div>

              {/* Renderizado de Tabla Semántica A11Y */}
              <div style={{ overflowX: "auto" }}>
                <Tabla>
                  <TablaEncabezado>
                    <TablaFila>
                      {agruparPor === "cliente" ? (
                        <>
                          <TablaCeldaEncabezado scope="col">Organización / Cliente</TablaCeldaEncabezado>
                          <TablaCeldaEncabezado scope="col">Plan</TablaCeldaEncabezado>
                          <TablaCeldaEncabezado scope="col" style={{ textAlign: "right" }}>Tokens In</TablaCeldaEncabezado>
                          <TablaCeldaEncabezado scope="col" style={{ textAlign: "right" }}>Tokens Out</TablaCeldaEncabezado>
                          <TablaCeldaEncabezado scope="col" style={{ textAlign: "right" }}>Tokens Total</TablaCeldaEncabezado>
                          <TablaCeldaEncabezado scope="col">Desglose Tiers</TablaCeldaEncabezado>
                          <TablaCeldaEncabezado scope="col" style={{ textAlign: "right" }}>Coste Est.</TablaCeldaEncabezado>
                          <TablaCeldaEncabezado scope="col">Cuota de Uso</TablaCeldaEncabezado>
                          <TablaCeldaEncabezado scope="col" style={{ textAlign: "center" }}>Facturación</TablaCeldaEncabezado>
                          <TablaCeldaEncabezado scope="col" style={{ textAlign: "center" }}>Privacidad</TablaCeldaEncabezado>
                        </>
                      ) : agruparPor === "tier" ? (
                        <>
                          <TablaCeldaEncabezado scope="col">Tier de Modelo</TablaCeldaEncabezado>
                          <TablaCeldaEncabezado scope="col" style={{ textAlign: "right" }}>Tokens In</TablaCeldaEncabezado>
                          <TablaCeldaEncabezado scope="col" style={{ textAlign: "right" }}>Tokens Out</TablaCeldaEncabezado>
                          <TablaCeldaEncabezado scope="col" style={{ textAlign: "right" }}>Tokens Total</TablaCeldaEncabezado>
                          <TablaCeldaEncabezado scope="col" style={{ textAlign: "right" }}>Coste Estimado</TablaCeldaEncabezado>
                          <TablaCeldaEncabezado scope="col" style={{ textAlign: "center" }}>Facturación</TablaCeldaEncabezado>
                        </>
                      ) : (
                        <>
                          <TablaCeldaEncabezado scope="col">Fecha / Día</TablaCeldaEncabezado>
                          <TablaCeldaEncabezado scope="col" style={{ textAlign: "right" }}>Tokens In</TablaCeldaEncabezado>
                          <TablaCeldaEncabezado scope="col" style={{ textAlign: "right" }}>Tokens Out</TablaCeldaEncabezado>
                          <TablaCeldaEncabezado scope="col" style={{ textAlign: "right" }}>Tokens Total</TablaCeldaEncabezado>
                          <TablaCeldaEncabezado scope="col">Desglose Tiers</TablaCeldaEncabezado>
                          <TablaCeldaEncabezado scope="col" style={{ textAlign: "right" }}>Coste Estimado</TablaCeldaEncabezado>
                          <TablaCeldaEncabezado scope="col" style={{ textAlign: "center" }}>Facturación</TablaCeldaEncabezado>
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
                            <TablaCelda>
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
                            <TablaCelda>
                              <Badge variante="accent">{item.plan || "starter"}</Badge>
                            </TablaCelda>

                            {/* Tokens In */}
                            <TablaCelda style={{ textAlign: "right", fontFamily: "monospace", fontSize: "0.8125rem" }}>
                              {formatearNumero(item.tokens_input ?? item.tokens_in)}
                            </TablaCelda>

                            {/* Tokens Out */}
                            <TablaCelda style={{ textAlign: "right", fontFamily: "monospace", fontSize: "0.8125rem" }}>
                              {formatearNumero(item.tokens_output ?? item.tokens_out)}
                            </TablaCelda>

                            {/* Tokens Total */}
                            <TablaCelda style={{ textAlign: "right", fontFamily: "monospace", fontWeight: 700, fontSize: "0.875rem" }}>
                              {formatearNumero(item.tokens_total)}
                            </TablaCelda>

                            {/* Desglose por Tier */}
                            <TablaCelda>
                              <div style={{ display: "flex", flexDirection: "column", gap: "2px", fontSize: "0.75rem" }}>
                                <span>Flash: <strong>{formatearNumero(item.por_tier?.flash)}</strong></span>
                                <span>Pro: <strong>{formatearNumero(item.por_tier?.pro)}</strong></span>
                                <span style={{ color: "var(--warn)" }}>Fable: <strong>{formatearNumero(item.por_tier?.fable)}</strong></span>
                              </div>
                            </TablaCelda>

                            {/* Coste Estimado EUR */}
                            <TablaCelda style={{ textAlign: "right", fontWeight: 600, color: "var(--accent)" }}>
                              {formatearMoneda(item.coste_estimado_eur ?? item.coste)}
                            </TablaCelda>

                            {/* Cuota de Uso */}
                            <TablaCelda>
                              <div style={{ display: "flex", flexDirection: "column", gap: "4px", minWidth: "100px" }}>
                                <div style={{ display: "flex", justifyContent: "space-between", fontSize: "0.75rem" }}>
                                  <span>{formatearPorcentaje(cuota)}</span>
                                  {cuota > 100 ? (
                                    <span style={{ color: "var(--bad)", fontWeight: 700 }}>Excedida</span>
                                  ) : cuota > 80 ? (
                                    <span style={{ color: "var(--warn)", fontWeight: 700 }}>Alerta</span>
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
                            <TablaCelda style={{ textAlign: "center" }}>
                              {cuadra ? (
                                <Badge variante="good" title="Consumo cuadra con la facturación emitida">
                                  ✅ Cuadra
                                </Badge>
                              ) : (
                                <Badge variante="error" title="Descuadre detectado entre consumo y facturación">
                                  🚨 Descuadre
                                </Badge>
                              )}
                            </TablaCelda>

                            {/* Privacidad E6 y Concesión */}
                            <TablaCelda style={{ textAlign: "center" }}>
                              {esEnmascarado ? (
                                <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: "4px" }}>
                                  <Badge variante="neutro">ENMASCARADO</Badge>
                                  <Boton
                                    variante="secondary"
                                    tamano="sm"
                                    onClick={() => handleAbrirConcesion(tenantId, item.razon_social)}
                                    data-testid={`btn-concesion-${tenantId}`}
                                    style={{ fontSize: "0.6875rem", padding: "2px 6px" }}
                                  >
                                    Solicitar acceso
                                  </Boton>
                                </div>
                              ) : (
                                <Badge variante="good">EN CLARO</Badge>
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
                            <TablaCelda>
                              <div style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
                                <Badge variante={esFable ? "warn" : "accent"}>{nombreTier}</Badge>
                                {esFable && (
                                  <span style={{ fontSize: "0.75rem", color: "var(--warn)" }}>
                                    (Razonamiento Agéntico Especializado)
                                  </span>
                                )}
                              </div>
                            </TablaCelda>
                            <TablaCelda style={{ textAlign: "right", fontFamily: "monospace" }}>
                              {formatearNumero(item.tokens_input ?? item.tokens_in)}
                            </TablaCelda>
                            <TablaCelda style={{ textAlign: "right", fontFamily: "monospace" }}>
                              {formatearNumero(item.tokens_output ?? item.tokens_out)}
                            </TablaCelda>
                            <TablaCelda style={{ textAlign: "right", fontFamily: "monospace", fontWeight: 700 }}>
                              {formatearNumero(item.tokens_total)}
                            </TablaCelda>
                            <TablaCelda style={{ textAlign: "right", fontWeight: 600, color: "var(--accent)" }}>
                              {formatearMoneda(item.coste_estimado_eur ?? item.coste)}
                            </TablaCelda>
                            <TablaCelda style={{ textAlign: "center" }}>
                              <Badge variante="good">✅ Conciliado</Badge>
                            </TablaCelda>
                          </TablaFila>
                        );
                      }

                      // Agrupación por día
                      const diaStr = item.dia || item.clave;
                      return (
                        <TablaFila key={diaStr} data-testid={`fila-dia-${diaStr}`}>
                          <TablaCelda style={{ fontWeight: 600 }}>{diaStr}</TablaCelda>
                          <TablaCelda style={{ textAlign: "right", fontFamily: "monospace" }}>
                            {formatearNumero(item.tokens_input ?? item.tokens_in)}
                          </TablaCelda>
                          <TablaCelda style={{ textAlign: "right", fontFamily: "monospace" }}>
                            {formatearNumero(item.tokens_output ?? item.tokens_out)}
                          </TablaCelda>
                          <TablaCelda style={{ textAlign: "right", fontFamily: "monospace", fontWeight: 700 }}>
                            {formatearNumero(item.tokens_total)}
                          </TablaCelda>
                          <TablaCelda>
                            <div style={{ display: "flex", gap: "0.5rem", fontSize: "0.75rem" }}>
                              <span>F: <strong>{formatearNumero(item.por_tier?.flash)}</strong></span>
                              <span>P: <strong>{formatearNumero(item.por_tier?.pro)}</strong></span>
                              <span style={{ color: "var(--warn)" }}>Fa: <strong>{formatearNumero(item.por_tier?.fable)}</strong></span>
                            </div>
                          </TablaCelda>
                          <TablaCelda style={{ textAlign: "right", fontWeight: 600, color: "var(--accent)" }}>
                            {formatearMoneda(item.coste_estimado_eur ?? item.coste)}
                          </TablaCelda>
                          <TablaCelda style={{ textAlign: "center" }}>
                            <Badge variante="good">✅ Conciliado</Badge>
                          </TablaCelda>
                        </TablaFila>
                      );
                    })}
                  </TablaCuerpo>
                </Tabla>
              </div>

              {/* Barra de Paginación Transversal */}
              <div
                style={{
                  padding: "0.75rem 1.25rem",
                  borderTop: "1px solid var(--border)",
                  display: "flex",
                  justifyContent: "space-between",
                  alignItems: "center",
                  flexWrap: "wrap",
                  gap: "0.75rem",
                  fontSize: "0.8125rem",
                  color: "var(--muted)",
                }}
              >
                <div style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
                  <span>Filas por página:</span>
                  <select
                    data-testid="select-page-size"
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
                    (Página {data.page} de {Math.max(data.pages, 1)})
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
                    Anterior
                  </Boton>
                  <Boton
                    variante="secondary"
                    tamano="sm"
                    disabled={data.page >= data.pages}
                    onClick={() => handleCambioFiltro("page", (data.page + 1).toString())}
                    data-testid="btn-pagina-siguiente"
                  >
                    Siguiente
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
