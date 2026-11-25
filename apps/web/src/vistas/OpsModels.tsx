/**
 * OpsModels.tsx — Pantalla de Observabilidad de Modelos LLM, Escalados y Dependencias Core
 *
 * Conectada mediante TanStack Query a GET /admin/v1/ops/models (y opcionalmente a
 * GET /admin/v1/health para salud de dependencias), aplicando segregación estricta del tier Fable.
 */

import React, { useState, useCallback, useContext, useMemo } from "react";
import {
  QueryClient,
  QueryClientContext,
  QueryClientProvider,
  useQuery,
} from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { peticionApi } from "../api/clienteApi";
import { useOptionalAuth } from "../estado/auth";
import { useLiveRefresh } from "../hooks/useLiveRefresh";
import { formatCurrencyEUR, formatNumber, formatPercent, formatTokens } from "../i18n/formatters";
import { ControlesLiveRefresh } from "../componentes/ControlesLiveRefresh";
import { ContenedorEstado } from "../componentes/ContenedorEstado";
import { Badge } from "../componentes/Badge";
import { Boton } from "../componentes/Boton";
import { Select } from "../componentes/Select";
import {
  Tabla,
  TablaEncabezado,
  TablaCuerpo,
  TablaFila,
  TablaCelda,
  TablaCeldaEncabezado,
} from "../componentes/Tabla";

export type VentanaModelos = "1h" | "24h" | "7d" | "30d";
export type TierModelo = "flash" | "pro" | "fable";

const VENTANAS_MODELOS: readonly VentanaModelos[] = ["1h", "24h", "7d", "30d"];
const ROLES_MODELOS_PERMITIDOS = new Set([
  "staff_operaciones",
  "staff_negocio",
  "staff_admin",
]);
const UMBRAL_DISPONIBILIDAD_1H = 99.0;

export interface ModeloMetrica {
  proveedor: string;
  modelo: string;
  tier: TierModelo;
  llamadas?: number;
  disponibilidad_pct: number;
  latencia_p50_ms?: number | null;
  latencia_p95_ms: number;
  tasa_error_pct: number;
}

export interface EscaladosLlm {
  flash_a_pro: number;
  pro_a_fable: number;
  a_humano: number;
}

export interface ServiciosCoreEstado {
  postgres: boolean;
  blob: boolean;
  telemetria: boolean;
  agregados: boolean;
}

export interface ComparacionModelos {
  periodo: string;
  escalados: EscaladosLlm;
  proveedores: ModeloMetrica[];
}

export interface RespuestaOpsModels {
  ventana?: string;
  telemetria_desde?: string | null;
  proveedores?: ModeloMetrica[];
  modelos: ModeloMetrica[];
  escalados: EscaladosLlm;
  tokens_por_tier?: Record<string, number>;
  coste_por_tier?: Record<string, number>;
  degradados?: string[] | null;
  comparacion?: ComparacionModelos | null;
  servicios?: ServiciosCoreEstado;
}

export interface RespuestaHealth {
  estado: "ok" | "degradado" | "no_disponible" | string;
  dependencias?: {
    postgres?: boolean;
    lectura_analitica?: boolean;
    cache?: boolean;
    telemetria?: boolean;
    agregados?: boolean;
  };
}

/** Contrato de compatibilidad con pruebas legadas sin QueryClientProvider padre */
export interface OpsModelsDatos {
  ventana?: VentanaModelos;
  modelos: ModeloMetrica[];
  escalados: EscaladosLlm;
  servicios: ServiciosCoreEstado;
  tokens_por_tier?: Record<string, number>;
  coste_por_tier?: Record<string, number>;
}

export interface OpsModelsProps {
  obtenerDatos?: (filtros?: {
    ventana: VentanaModelos;
    proveedor: string;
    tier: string;
    compararCon: boolean;
  }) => Promise<RespuestaOpsModels>;
  datosIniciales?: OpsModelsDatos | null;
}

const DATOS_DEFECTO: OpsModelsDatos = {
  ventana: "24h",
  modelos: [
    {
      proveedor: "Google Gemini",
      modelo: "gemini-2.5-flash",
      tier: "flash",
      llamadas: 42500,
      disponibilidad_pct: 99.98,
      latencia_p50_ms: 180,
      latencia_p95_ms: 420,
      tasa_error_pct: 0.05,
    },
    {
      proveedor: "Google Gemini",
      modelo: "gemini-2.5-pro",
      tier: "pro",
      llamadas: 11200,
      disponibilidad_pct: 99.85,
      latencia_p50_ms: 650,
      latencia_p95_ms: 1250,
      tasa_error_pct: 0.12,
    },
    {
      proveedor: "Anthropic",
      modelo: "claude-3-7-sonnet",
      tier: "fable",
      llamadas: 1850,
      disponibilidad_pct: 99.92,
      latencia_p50_ms: 920,
      latencia_p95_ms: 1840,
      tasa_error_pct: 0.08,
    },
  ],
  escalados: {
    flash_a_pro: 142,
    pro_a_fable: 18,
    a_humano: 3,
  },
  tokens_por_tier: {
    flash: 80_000_000,
    pro: 35_000_000,
    fable: 10_000_000,
  },
  coste_por_tier: {
    flash: 120.5,
    pro: 310.2,
    fable: 450.0,
  },
  servicios: {
    postgres: true,
    blob: true,
    telemetria: true,
    agregados: true,
  },
};

function calcularDeltaPorcentual(
  actual: number,
  previo: number | undefined,
  lang?: string
): string | null {
  if (previo === undefined || !Number.isFinite(previo) || previo === 0) return null;
  const pct = ((actual - previo) / previo) * 100;
  return formatPercent(pct, { decimals: 1, includeSign: true, lang });
}

function estiloBadgeTier(tier: TierModelo): React.CSSProperties {
  if (tier === "flash") {
    return {
      backgroundColor: "rgba(14, 165, 233, 0.16)",
      color: "#0284c7",
      border: "1px solid rgba(14, 165, 233, 0.4)",
    };
  }
  if (tier === "pro") {
    return {
      backgroundColor: "rgba(139, 92, 246, 0.16)",
      color: "#7c3aed",
      border: "1px solid rgba(139, 92, 246, 0.4)",
    };
  }
  return {
    backgroundColor: "rgba(245, 158, 11, 0.18)",
    color: "#d97706",
    border: "1px solid rgba(245, 158, 11, 0.45)",
  };
}

interface TablaModelosSeccionProps {
  testId: string;
  titulo: string;
  subtitulo: string;
  modelos: ModeloMetrica[];
  ventana: VentanaModelos;
  comparacion: ComparacionModelos | null | undefined;
  mostrarComparativa: boolean;
}

const TablaModelosSeccion: React.FC<TablaModelosSeccionProps> = ({
  testId,
  titulo,
  subtitulo,
  modelos,
  ventana,
  comparacion,
  mostrarComparativa,
}) => {
  const { t, i18n } = useTranslation();
  const lang = i18n.resolvedLanguage || i18n.language;
  const [mostrarTodasColumnas, setMostrarTodasColumnas] = useState<boolean>(false);

  const prevPorModelo = useMemo(() => {
    const mapa = new Map<string, ModeloMetrica>();
    for (const prev of comparacion?.proveedores ?? []) {
      mapa.set(prev.modelo, prev);
    }
    return mapa;
  }, [comparacion]);

  return (
    <section
      className="card"
      data-testid={testId}
      aria-label={titulo}
      style={{ display: "flex", flexDirection: "column", gap: "12px" }}
    >
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", flexWrap: "wrap", gap: "8px" }}>
        <div>
          <h2 style={{ fontSize: "15px", fontWeight: 650, margin: 0, color: "var(--text)" }}>
            {titulo}
          </h2>
          <p style={{ fontSize: "12px", color: "var(--muted)", margin: "4px 0 0 0" }}>
            {subtitulo}
          </p>
        </div>

        <Boton
          variante="ghost"
          tamano="sm"
          className="kc-columns-toggle"
          data-testid={`toggle-columnas-${testId}`}
          aria-pressed={mostrarTodasColumnas}
          aria-label={t("components.table.toggleColumnsAria")}
          onClick={() => setMostrarTodasColumnas((prev) => !prev)}
        >
          {mostrarTodasColumnas
            ? t("components.table.compactColumns")
            : t("components.table.showAllColumns")}
        </Boton>
      </div>

      <Tabla densidad="alta" mostrarTodasColumnas={mostrarTodasColumnas}>
        <TablaEncabezado>
          <TablaFila>
            <TablaCeldaEncabezado scope="col" fija>{t("views.opsModels.tables.colProvider")}</TablaCeldaEncabezado>
            <TablaCeldaEncabezado scope="col">{t("views.opsModels.tables.colModel")}</TablaCeldaEncabezado>
            <TablaCeldaEncabezado scope="col">{t("views.opsModels.tables.colTier")}</TablaCeldaEncabezado>
            <TablaCeldaEncabezado scope="col" numerico prioridad="baja">
              {t("views.opsModels.tables.colCalls")}
            </TablaCeldaEncabezado>
            <TablaCeldaEncabezado scope="col" numerico>
              {t("views.opsModels.tables.colAvailability")}
            </TablaCeldaEncabezado>
            <TablaCeldaEncabezado scope="col" numerico prioridad="baja">
              {t("views.opsModels.tables.colLatencyP50")}
            </TablaCeldaEncabezado>
            <TablaCeldaEncabezado scope="col" numerico>
              {t("views.opsModels.tables.colLatencyP95")}
            </TablaCeldaEncabezado>
            <TablaCeldaEncabezado scope="col" numerico prioridad="media">
              {t("views.opsModels.tables.colErrorRate")}
            </TablaCeldaEncabezado>
            {mostrarComparativa && (
              <TablaCeldaEncabezado scope="col" numerico prioridad="baja">
                {t("views.opsModels.tables.colDelta")}
              </TablaCeldaEncabezado>
            )}
          </TablaFila>
        </TablaEncabezado>
        <TablaCuerpo>
          {modelos.map((m) => {
            const degradado =
              ventana === "1h" && m.disponibilidad_pct < UMBRAL_DISPONIBILIDAD_1H;
            const previo = prevPorModelo.get(m.modelo);
            const deltaLlamadas =
              previo && m.llamadas !== undefined
                ? calcularDeltaPorcentual(m.llamadas, previo.llamadas, lang)
                : null;
            const deltaLatencia = previo
              ? calcularDeltaPorcentual(m.latencia_p95_ms, previo.latencia_p95_ms, lang)
              : null;

            return (
              <TablaFila
                key={`${m.proveedor}-${m.modelo}-${m.tier}`}
                data-testid={`fila-modelo-${m.modelo}`}
                style={
                  degradado
                    ? { backgroundColor: "var(--bad-bg)" }
                    : undefined
                }
              >
                <TablaCelda fija>
                  <strong>{m.proveedor}</strong>
                </TablaCelda>
                <TablaCelda>
                  <code className="mono">{m.modelo}</code>
                </TablaCelda>
                <TablaCelda>
                  <Badge
                    variante={
                      m.tier === "fable"
                        ? "advertencia"
                        : m.tier === "pro"
                        ? "enmascarado"
                        : "accent"
                    }
                    style={estiloBadgeTier(m.tier)}
                  >
                    {m.tier.toUpperCase()}
                  </Badge>
                </TablaCelda>
                <TablaCelda numerico prioridad="baja">
                  {m.llamadas !== undefined && Number.isFinite(m.llamadas)
                    ? formatNumber(m.llamadas, undefined, lang)
                    : t("common.states.noData")}
                </TablaCelda>
                <TablaCelda numerico>
                  <span
                    style={{
                      color: degradado
                        ? "var(--bad)"
                        : m.disponibilidad_pct >= 99.9
                        ? "var(--good)"
                        : "var(--warn)",
                      fontWeight: 600,
                    }}
                  >
                    {formatPercent(m.disponibilidad_pct, { decimals: 2, lang })}
                  </span>
                </TablaCelda>
                <TablaCelda numerico prioridad="baja">
                  {m.latencia_p50_ms !== null && m.latencia_p50_ms !== undefined
                    ? t("views.opsModels.tables.msValue", {
                        ms: formatNumber(m.latencia_p50_ms, undefined, lang),
                      })
                    : t("common.states.noData")}
                </TablaCelda>
                <TablaCelda numerico>
                  {t("views.opsModels.tables.msValue", {
                    ms: formatNumber(m.latencia_p95_ms, undefined, lang),
                  })}
                </TablaCelda>
                <TablaCelda numerico prioridad="media">
                  {formatPercent(m.tasa_error_pct, { decimals: 2, lang })}
                </TablaCelda>
                {mostrarComparativa && (
                  <TablaCelda numerico prioridad="baja">
                    <span
                      data-testid={`delta-${m.modelo}`}
                      style={{ fontSize: "12px", color: "var(--muted)" }}
                    >
                      {deltaLlamadas
                        ? t("views.opsModels.tables.deltaCalls", { delta: deltaLlamadas })
                        : t("common.states.noData")}
                      {deltaLatencia
                        ? ` · ${t("views.opsModels.tables.deltaP95", { delta: deltaLatencia })}`
                        : ""}
                    </span>
                  </TablaCelda>
                )}
              </TablaFila>
            );
          })}
        </TablaCuerpo>
      </Tabla>
    </section>
  );
};

interface OpsModelsInternoProps extends OpsModelsProps {
  usarFallbackLocal?: boolean;
}

const OpsModelsInterno: React.FC<OpsModelsInternoProps> = ({
  obtenerDatos,
  datosIniciales,
  usarFallbackLocal = false,
}) => {
  const { t, i18n } = useTranslation();
  const lang = i18n.resolvedLanguage || i18n.language;
  const auth = useOptionalAuth();
  const usuario = auth?.usuario ?? null;

  const [ventana, setVentana] = useState<VentanaModelos>(
    datosIniciales?.ventana ?? "24h"
  );
  const [proveedorFiltro, setProveedorFiltro] = useState<string>("todos");
  const [tierFiltro, setTierFiltro] = useState<string>("todos");
  const [compararPeriodo, setCompararPeriodo] = useState<boolean>(false);

  const rolNoAutorizado =
    Boolean(usuario) && !ROLES_MODELOS_PERMITIDOS.has(usuario?.role ?? "");

  const datosInicialesResueltos: RespuestaOpsModels | undefined = useMemo(() => {
    if (datosIniciales) {
      return {
        ventana: datosIniciales.ventana ?? "24h",
        modelos: datosIniciales.modelos,
        proveedores: datosIniciales.modelos,
        escalados: datosIniciales.escalados,
        tokens_por_tier: datosIniciales.tokens_por_tier,
        coste_por_tier: datosIniciales.coste_por_tier,
        servicios: datosIniciales.servicios,
      };
    }
    if (usarFallbackLocal) {
      return {
        ventana: DATOS_DEFECTO.ventana ?? "24h",
        modelos: DATOS_DEFECTO.modelos,
        proveedores: DATOS_DEFECTO.modelos,
        escalados: DATOS_DEFECTO.escalados,
        tokens_por_tier: DATOS_DEFECTO.tokens_por_tier,
        coste_por_tier: DATOS_DEFECTO.coste_por_tier,
        servicios: DATOS_DEFECTO.servicios,
      };
    }
    return undefined;
  }, [datosIniciales, usarFallbackLocal]);

  const consultarModelos = useCallback(async (): Promise<RespuestaOpsModels> => {
    if (obtenerDatos) {
      return obtenerDatos({
        ventana,
        proveedor: proveedorFiltro,
        tier: tierFiltro,
        compararCon: compararPeriodo,
      });
    }
    const params: Record<string, string | boolean> = { ventana };
    if (proveedorFiltro !== "todos") {
      params.proveedor = proveedorFiltro;
    }
    if (tierFiltro !== "todos") {
      params.tier = tierFiltro;
    }
    if (compararPeriodo) {
      params.comparar_con = "periodo_anterior";
    }
    return peticionApi<RespuestaOpsModels>("/admin/v1/ops/models", { params });
  }, [obtenerDatos, ventana, proveedorFiltro, tierFiltro, compararPeriodo]);

  const habilitadoQuery =
    !rolNoAutorizado &&
    !usarFallbackLocal &&
    (datosIniciales === undefined || Boolean(obtenerDatos));

  const {
    data: modelsData,
    isLoading: isLoadingModels,
    isFetching: isFetchingModels,
    error: errorModels,
    refetch: refetchModels,
  } = useQuery<RespuestaOpsModels>({
    queryKey: [
      "ops-models",
      ventana,
      proveedorFiltro,
      tierFiltro,
      compararPeriodo,
      Boolean(obtenerDatos),
    ],
    queryFn: consultarModelos,
    enabled: habilitadoQuery,
    initialData: datosInicialesResueltos,
    placeholderData: (prev) => prev,
    staleTime: 10_000,
  });

  const {
    data: healthData,
    isFetching: isFetchingHealth,
    refetch: refetchHealth,
  } = useQuery<RespuestaHealth>({
    queryKey: ["ops-health"],
    queryFn: () => peticionApi<RespuestaHealth>("/admin/v1/health"),
    enabled: habilitadoQuery && !obtenerDatos,
    retry: false,
    staleTime: 15_000,
  });

  const refrescarTodo = useCallback(async () => {
    if (rolNoAutorizado || !habilitadoQuery) return;
    await Promise.all([
      refetchModels(),
      !obtenerDatos ? refetchHealth() : Promise.resolve(),
    ]);
  }, [rolNoAutorizado, habilitadoQuery, refetchModels, refetchHealth, obtenerDatos]);

  const liveRefresh = useLiveRefresh({
    intervaloMs: 15_000,
    ejecutarAlInicio: false,
    alRefrescar: refrescarTodo,
    estaConsultando: isFetchingModels || isFetchingHealth,
    refrescarAlVolverVisible: true,
    peticionesPorCiclo: !obtenerDatos ? 2 : 1,
    pausarEnSegundoPlano: true,
    pausarEnPerdidaFoco: true,
  });

  const listaModelos = useMemo(() => {
    const origen = modelsData?.modelos?.length
      ? modelsData.modelos
      : modelsData?.proveedores ?? [];
    return origen.filter((m) => {
      if (
        proveedorFiltro !== "todos" &&
        m.proveedor.toLowerCase() !== proveedorFiltro.toLowerCase()
      ) {
        return false;
      }
      if (tierFiltro !== "todos" && m.tier !== tierFiltro) {
        return false;
      }
      return true;
    });
  }, [modelsData, proveedorFiltro, tierFiltro]);

  // Regla de oro inviolable: Fable siempre segregado de Flash y Pro
  const modelosEstandar = useMemo(
    () => listaModelos.filter((m) => m.tier === "flash" || m.tier === "pro"),
    [listaModelos]
  );

  const modelosFable = useMemo(
    () => listaModelos.filter((m) => m.tier === "fable"),
    [listaModelos]
  );

  const proveedoresDegradados1h = useMemo(() => {
    if (ventana !== "1h") return [];
    return listaModelos.filter((m) => m.disponibilidad_pct < UMBRAL_DISPONIBILIDAD_1H);
  }, [ventana, listaModelos]);

  const serviciosCore: ServiciosCoreEstado = useMemo(() => {
    if (datosIniciales?.servicios || modelsData?.servicios) {
      const s = datosIniciales?.servicios ?? modelsData?.servicios!;
      return {
        postgres: s.postgres,
        blob: s.blob,
        telemetria: s.telemetria,
        agregados: s.agregados,
      };
    }
    if (healthData?.dependencias) {
      return {
        postgres: healthData.dependencias.postgres ?? true,
        blob: healthData.dependencias.cache ?? true,
        telemetria: healthData.dependencias.telemetria ?? !errorModels,
        agregados: healthData.dependencias.agregados ?? !errorModels,
      };
    }
    const ok = !errorModels;
    return {
      postgres: ok,
      blob: ok,
      telemetria: ok,
      agregados: ok,
    };
  }, [datosIniciales, modelsData, healthData, errorModels]);

  if (rolNoAutorizado) {
    return (
      <main
        className="view ops-models"
        data-testid="ops-models-rbac-bloqueado"
        role="alert"
        style={{
          padding: "1.5rem",
          backgroundColor: "var(--bad-bg)",
          borderRadius: "var(--radius-md)",
          border: "1px solid var(--bad)",
          color: "var(--text)",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: "0.5rem", marginBottom: "0.5rem" }}>
          <Badge variante="error">{t("common.errors.accessDeniedBadge")}</Badge>
          <strong>{t("common.errors.accessDeniedCode")}</strong>
        </div>
        <p style={{ color: "var(--muted)", margin: 0 }}>
          {t("views.opsModels.rbacDenied", { role: usuario?.role })}
        </p>
      </main>
    );
  }

  if (datosIniciales === null) return null;

  const escalados = modelsData?.escalados ?? {
    flash_a_pro: 0,
    pro_a_fable: 0,
    a_humano: 0,
  };
  const tokensTier = modelsData?.tokens_por_tier ?? {};
  const costeTier = modelsData?.coste_por_tier ?? {};
  const comparacionActiva = Boolean(compararPeriodo && modelsData?.comparacion);

  return (
    <div
      className="view ops-models kc-view-container"
    >
      {/* Cabecera y controles de refresco en vivo */}
      <header
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "flex-start",
          flexWrap: "wrap",
          gap: "12px",
        }}
      >
        <div>
          <h1 style={{ fontSize: "1.25rem", fontWeight: 700, margin: 0, color: "var(--text)" }}>
            {t("views.opsModels.title")}
          </h1>
          <p style={{ fontSize: "0.8125rem", color: "var(--muted)", margin: "4px 0 0 0" }}>
            {t("views.opsModels.subtitle")}
          </p>
        </div>

        <ControlesLiveRefresh hook={liveRefresh} />
      </header>

      {/* Filtros reactivos */}
      <section
        aria-label={t("views.opsModels.filters.regionLabel")}
        className="card kc-filter-bar"
      >
        <div className="kc-filter-item" style={{ display: "flex", flexDirection: "column", gap: "6px" }}>
          <span style={{ fontSize: "12px", fontWeight: 600, color: "var(--muted)" }}>
            {t("views.opsModels.filters.windowLabel")}
          </span>
          <div
            role="group"
            aria-label={t("views.opsModels.filters.windowAria")}
            data-testid="selector-ventana-models"
            className="kc-tabs-scroll"
            style={{
              borderRadius: "var(--radius-sm)",
              border: "1px solid var(--border)",
              background: "var(--surface)",
              width: "fit-content",
            }}
          >
            {VENTANAS_MODELOS.map((v) => {
              const activa = ventana === v;
              return (
                <button
                  key={v}
                  type="button"
                  data-testid={`btn-ventana-models-${v}`}
                  aria-pressed={activa}
                  onClick={() => setVentana(v)}
                  style={{
                    padding: "6px 12px",
                    border: "none",
                    cursor: "pointer",
                    fontSize: "13px",
                    fontWeight: activa ? 600 : 500,
                    background: activa ? "var(--accent)" : "transparent",
                    color: activa ? "var(--surface)" : "var(--text)",
                  }}
                >
                  {v}
                </button>
              );
            })}
          </div>
        </div>

        <div className="kc-filter-item">
          <Select
            id="ops-models-proveedor"
            etiqueta={t("views.opsModels.filters.providerLabel")}
            data-testid="filtro-proveedor"
            value={proveedorFiltro}
            onChange={(e) => setProveedorFiltro(e.target.value)}
            opciones={[
              { valor: "todos", etiqueta: t("views.opsModels.filters.all") },
              { valor: "anthropic", etiqueta: "Anthropic" },
              { valor: "google", etiqueta: "Google" },
              { valor: "deepseek", etiqueta: "DeepSeek" },
              { valor: "openai", etiqueta: "OpenAI" },
            ]}
          />
        </div>

        <div className="kc-filter-item">
          <Select
            id="ops-models-tier"
            etiqueta={t("views.opsModels.filters.tierLabel")}
            data-testid="filtro-tier"
            value={tierFiltro}
            onChange={(e) => setTierFiltro(e.target.value)}
            opciones={[
              { valor: "todos", etiqueta: t("views.opsModels.filters.all") },
              { valor: "flash", etiqueta: "Flash" },
              { valor: "pro", etiqueta: "Pro" },
              { valor: "fable", etiqueta: "Fable" },
            ]}
          />
        </div>

        <div className="kc-filter-actions" style={{ paddingBottom: "4px" }}>
          <label
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: "8px",
              fontSize: "13px",
              cursor: "pointer",
            }}
          >
            <input
              type="checkbox"
              data-testid="toggle-comparar-periodo"
              checked={compararPeriodo}
              onChange={(e) => setCompararPeriodo(e.target.checked)}
            />
            {t("views.opsModels.filters.comparePrevious")}
          </label>
        </div>
      </section>

      {/* Salud de Servicios y Dependencias Core */}
      <section
        className="card"
        aria-label={t("views.opsModels.health.regionLabel")}
        data-testid="panel-salud-servicios"
      >
        <h2 style={{ fontSize: "14px", fontWeight: 650, margin: "0 0 12px 0" }}>
          {t("views.opsModels.health.title")}
        </h2>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: "12px" }}>
          {[
            { clave: "postgres", etiqueta: t("views.opsModels.health.services.postgres"), ok: serviciosCore.postgres },
            { clave: "blob", etiqueta: t("views.opsModels.health.services.blob"), ok: serviciosCore.blob },
            { clave: "telemetria", etiqueta: t("views.opsModels.health.services.telemetria"), ok: serviciosCore.telemetria },
            { clave: "agregados", etiqueta: t("views.opsModels.health.services.agregados"), ok: serviciosCore.agregados },
          ].map((srv) => (
            <div
              key={srv.clave}
              data-testid={`servicio-${srv.clave}`}
              style={{
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
                padding: "10px 14px",
                backgroundColor: "var(--surface2)",
                borderRadius: "var(--radius-md)",
              }}
            >
              <span style={{ fontSize: "13px", fontWeight: 500 }}>{srv.etiqueta}</span>
              <Badge variante={srv.ok ? "good" : "bad"} punto>
                {srv.ok ? t("views.opsModels.health.operational") : t("views.opsModels.health.degraded")}
              </Badge>
            </div>
          ))}
        </div>
      </section>

      {/* Bloque principal de telemetría bajo ContenedorEstado */}
      <ContenedorEstado
        cargando={isLoadingModels && !modelsData}
        error={errorModels}
        vacio={!errorModels && listaModelos.length === 0}
        tipoCarga="tabla"
        filasCarga={5}
        columnasCarga={8}
        mensajeCarga={t("views.opsModels.loadingMessage")}
        tituloError={t("views.opsModels.errorTitle")}
        tituloVacio={t("views.opsModels.emptyTitle")}
        descripcionVacio={t("views.opsModels.emptyDescription")}
        dataTestIdCarga="ops-models-loading"
        dataTestIdError="ops-models-error"
        dataTestIdTrace="ops-models-trace-id"
        alReintentar={refrescarTodo}
        reintentando={isFetchingModels}
      >
        <div style={{ display: "flex", flexDirection: "column", gap: "20px" }}>
          {/* Alerta crítica si algún proveedor cae por debajo de 99% en ventana 1h */}
          {proveedoresDegradados1h.length > 0 && (
            <div
              role="alert"
              data-testid="alerta-disponibilidad-1h"
              style={{
                padding: "14px 16px",
                borderRadius: "var(--radius-md)",
                border: "1px solid var(--bad)",
                backgroundColor: "var(--bad-bg)",
                color: "var(--text)",
              }}
            >
              <strong style={{ fontSize: "14px" }}>
                {t("views.opsModels.availabilityAlert.title")}
              </strong>
              <ul style={{ margin: "6px 0 0 18px", fontSize: "13px" }}>
                {proveedoresDegradados1h.map((p) => (
                  <li key={`${p.proveedor}-${p.modelo}`}>
                    <strong>{p.proveedor}</strong> ({p.modelo}):{" "}
                    {t("views.opsModels.availabilityAlert.item", {
                      availability: formatPercent(p.disponibilidad_pct, { decimals: 2, lang }),
                    })}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {/* Tarjetas de Escalados LLM */}
          <section
            aria-label={t("views.opsModels.escalations.regionLabel")}
            style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", gap: "14px" }}
          >
            <article className="card" data-testid="kpi-escalado-flash-pro">
              <div style={{ fontSize: "12px", color: "var(--muted)" }}>
                {t("views.opsModels.escalations.flashToPro")}
              </div>
              <div style={{ fontSize: "24px", fontWeight: 700, color: "var(--accent)", marginTop: "4px" }}>
                {formatNumber(escalados.flash_a_pro, undefined, lang)}
              </div>
              {comparacionActiva && (
                <div style={{ fontSize: "12px", color: "var(--muted)", marginTop: "4px" }}>
                  {t("views.opsModels.escalations.vsPrevious", {
                    delta:
                      calcularDeltaPorcentual(
                        escalados.flash_a_pro,
                        modelsData?.comparacion?.escalados.flash_a_pro,
                        lang
                      ) ?? t("views.opsModels.escalations.noChange"),
                  })}
                </div>
              )}
            </article>

            <article className="card" data-testid="kpi-escalado-pro-fable">
              <div style={{ fontSize: "12px", color: "var(--muted)" }}>
                {t("views.opsModels.escalations.proToFable")}
              </div>
              <div style={{ fontSize: "24px", fontWeight: 700, color: "var(--purple)", marginTop: "4px" }}>
                {formatNumber(escalados.pro_a_fable, undefined, lang)}
              </div>
              {comparacionActiva && (
                <div style={{ fontSize: "12px", color: "var(--muted)", marginTop: "4px" }}>
                  {t("views.opsModels.escalations.vsPrevious", {
                    delta:
                      calcularDeltaPorcentual(
                        escalados.pro_a_fable,
                        modelsData?.comparacion?.escalados.pro_a_fable,
                        lang
                      ) ?? t("views.opsModels.escalations.noChange"),
                  })}
                </div>
              )}
            </article>

            <article className="card" data-testid="kpi-escalado-humano">
              <div style={{ fontSize: "12px", color: "var(--muted)" }}>
                {t("views.opsModels.escalations.toHuman")}
              </div>
              <div style={{ fontSize: "24px", fontWeight: 700, color: "var(--warn)", marginTop: "4px" }}>
                {formatNumber(escalados.a_humano, undefined, lang)}
              </div>
              {comparacionActiva && (
                <div style={{ fontSize: "12px", color: "var(--muted)", marginTop: "4px" }}>
                  {t("views.opsModels.escalations.vsPrevious", {
                    delta:
                      calcularDeltaPorcentual(
                        escalados.a_humano,
                        modelsData?.comparacion?.escalados.a_humano,
                        lang
                      ) ?? t("views.opsModels.escalations.noChange"),
                  })}
                </div>
              )}
            </article>
          </section>

          {/* Desglose de Tokens Consumidos y Coste Estimado por Tier (sin mezclar Fable) */}
          <section
            aria-label={t("views.opsModels.tiers.regionLabel")}
            data-testid="desglose-costes-por-tier"
            style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", gap: "14px" }}
          >
            <article className="card" data-testid="card-tier-flash">
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                <span style={{ fontSize: "12px", fontWeight: 600, color: "var(--muted)" }}>
                  {t("views.opsModels.tiers.flashTitle")}
                </span>
                <Badge style={estiloBadgeTier("flash")}>Flash</Badge>
              </div>
              <div style={{ fontSize: "20px", fontWeight: 700, marginTop: "6px" }}>
                {t("views.opsModels.tiers.tokensSuffix", {
                  tokens: formatTokens(tokensTier.flash, { compact: true, lang }),
                })}
              </div>
              <div style={{ fontSize: "13px", color: "var(--muted)", marginTop: "4px" }}>
                {t("views.opsModels.tiers.estimatedCost")}{" "}
                <strong>{formatCurrencyEUR(costeTier.flash, "EUR", lang)}</strong>
              </div>
            </article>

            <article className="card" data-testid="card-tier-pro">
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                <span style={{ fontSize: "12px", fontWeight: 600, color: "var(--muted)" }}>
                  {t("views.opsModels.tiers.proTitle")}
                </span>
                <Badge style={estiloBadgeTier("pro")}>Pro</Badge>
              </div>
              <div style={{ fontSize: "20px", fontWeight: 700, marginTop: "6px" }}>
                {t("views.opsModels.tiers.tokensSuffix", {
                  tokens: formatTokens(tokensTier.pro, { compact: true, lang }),
                })}
              </div>
              <div style={{ fontSize: "13px", color: "var(--muted)", marginTop: "4px" }}>
                {t("views.opsModels.tiers.estimatedCost")}{" "}
                <strong>{formatCurrencyEUR(costeTier.pro, "EUR", lang)}</strong>
              </div>
            </article>

            <article
              className="card"
              data-testid="card-tier-fable"
              style={{ border: "1px solid rgba(245, 158, 11, 0.55)" }}
            >
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                <span style={{ fontSize: "12px", fontWeight: 600, color: "var(--muted)" }}>
                  {t("views.opsModels.tiers.fableTitle")}
                </span>
                <Badge style={estiloBadgeTier("fable")}>Fable</Badge>
              </div>
              <div style={{ fontSize: "20px", fontWeight: 700, marginTop: "6px" }}>
                {t("views.opsModels.tiers.tokensSuffix", {
                  tokens: formatTokens(tokensTier.fable, { compact: true, lang }),
                })}
              </div>
              <div style={{ fontSize: "13px", color: "var(--muted)", marginTop: "4px" }}>
                {t("views.opsModels.tiers.independentCost")}{" "}
                <strong>{formatCurrencyEUR(costeTier.fable, "EUR", lang)}</strong>
              </div>
            </article>
          </section>

          {/* Tabla 1: Modelos Estándar (Flash y Pro) */}
          {modelosEstandar.length > 0 && (
            <TablaModelosSeccion
              testId="tabla-modelos-estandar"
              titulo={t("views.opsModels.tables.standardTitle")}
              subtitulo={t("views.opsModels.tables.standardSubtitle")}
              modelos={modelosEstandar}
              ventana={ventana}
              comparacion={modelsData?.comparacion}
              mostrarComparativa={comparacionActiva}
            />
          )}

          {/* Tabla 2: Tier Fable estrictamente segregado */}
          {modelosFable.length > 0 && (
            <TablaModelosSeccion
              testId="seccion-fable-segregada"
              titulo={t("views.opsModels.tables.fableTitle")}
              subtitulo={t("views.opsModels.tables.fableSubtitle")}
              modelos={modelosFable}
              ventana={ventana}
              comparacion={modelsData?.comparacion}
              mostrarComparativa={comparacionActiva}
            />
          )}
        </div>
      </ContenedorEstado>
    </div>
  );
};

export const OpsModels: React.FC<OpsModelsProps> = (props) => {
  const parentClient = useContext(QueryClientContext);
  const fallbackClient = useMemo(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            retry: false,
          },
        },
      }),
    []
  );

  if (parentClient) {
    return <OpsModelsInterno {...props} />;
  }

  return (
    <QueryClientProvider client={fallbackClient}>
      <OpsModelsInterno
        {...props}
        usarFallbackLocal={props.obtenerDatos === undefined}
      />
    </QueryClientProvider>
  );
};
