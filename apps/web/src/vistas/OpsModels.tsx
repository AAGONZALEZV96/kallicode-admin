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
import { peticionApi } from "../api/clienteApi";
import { useOptionalAuth } from "../estado/auth";
import { useLiveRefresh } from "../hooks/useLiveRefresh";
import { ControlesLiveRefresh } from "../componentes/ControlesLiveRefresh";
import { ContenedorEstado } from "../componentes/ContenedorEstado";
import { Badge } from "../componentes/Badge";
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

function formatearTokens(tokens: number | undefined): string {
  if (tokens === undefined || !Number.isFinite(tokens)) return "—";
  if (tokens >= 1_000_000) return `${(tokens / 1_000_000).toFixed(1)} M`;
  if (tokens >= 1_000) return `${(tokens / 1_000).toFixed(1)} k`;
  return String(tokens);
}

function formatearEuro(importe: number | undefined): string {
  if (importe === undefined || !Number.isFinite(importe)) return "—";
  return `${importe.toFixed(2)} €`;
}

function calcularDeltaPorcentual(actual: number, previo: number | undefined): string | null {
  if (previo === undefined || !Number.isFinite(previo) || previo === 0) return null;
  const pct = ((actual - previo) / previo) * 100;
  const signo = pct > 0 ? "+" : "";
  return `${signo}${pct.toFixed(1)}%`;
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
      <div>
        <h2 style={{ fontSize: "15px", fontWeight: 650, margin: 0, color: "var(--text)" }}>
          {titulo}
        </h2>
        <p style={{ fontSize: "12px", color: "var(--muted)", margin: "4px 0 0 0" }}>
          {subtitulo}
        </p>
      </div>

      <div style={{ overflowX: "auto" }}>
        <Tabla densidad="alta">
          <TablaEncabezado>
            <TablaFila>
              <TablaCeldaEncabezado scope="col">Proveedor</TablaCeldaEncabezado>
              <TablaCeldaEncabezado scope="col">Modelo</TablaCeldaEncabezado>
              <TablaCeldaEncabezado scope="col">Tier</TablaCeldaEncabezado>
              <TablaCeldaEncabezado scope="col" numerico>
                Llamadas
              </TablaCeldaEncabezado>
              <TablaCeldaEncabezado scope="col" numerico>
                Disponibilidad %
              </TablaCeldaEncabezado>
              <TablaCeldaEncabezado scope="col" numerico>
                Latencia P50 (ms)
              </TablaCeldaEncabezado>
              <TablaCeldaEncabezado scope="col" numerico>
                Latencia P95 (ms)
              </TablaCeldaEncabezado>
              <TablaCeldaEncabezado scope="col" numerico>
                Tasa de Error %
              </TablaCeldaEncabezado>
              {mostrarComparativa && (
                <TablaCeldaEncabezado scope="col" numerico>
                  Delta vs período anterior
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
                  ? calcularDeltaPorcentual(m.llamadas, previo.llamadas)
                  : null;
              const deltaLatencia = previo
                ? calcularDeltaPorcentual(m.latencia_p95_ms, previo.latencia_p95_ms)
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
                  <TablaCelda>
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
                  <TablaCelda numerico>
                    {m.llamadas !== undefined && Number.isFinite(m.llamadas)
                      ? m.llamadas.toLocaleString("es-ES")
                      : "—"}
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
                      {m.disponibilidad_pct.toFixed(2)}%
                    </span>
                  </TablaCelda>
                  <TablaCelda numerico>
                    {m.latencia_p50_ms !== null && m.latencia_p50_ms !== undefined
                      ? `${m.latencia_p50_ms} ms`
                      : "—"}
                  </TablaCelda>
                  <TablaCelda numerico>{m.latencia_p95_ms} ms</TablaCelda>
                  <TablaCelda numerico>{m.tasa_error_pct.toFixed(2)}%</TablaCelda>
                  {mostrarComparativa && (
                    <TablaCelda numerico>
                      <span
                        data-testid={`delta-${m.modelo}`}
                        style={{ fontSize: "12px", color: "var(--muted)" }}
                      >
                        {deltaLlamadas ? `Llamadas ${deltaLlamadas}` : "—"}
                        {deltaLatencia ? ` · P95 ${deltaLatencia}` : ""}
                      </span>
                    </TablaCelda>
                  )}
                </TablaFila>
              );
            })}
          </TablaCuerpo>
        </Tabla>
      </div>
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

  const { data: healthData, refetch: refetchHealth } = useQuery<RespuestaHealth>({
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
          <Badge variante="error">ACCESO DENEGADO</Badge>
          <strong>403 ROL_STAFF_INSUFICIENTE</strong>
        </div>
        <p style={{ color: "var(--muted)", margin: 0 }}>
          El rol {usuario?.role} no tiene autorización para consultar la telemetría de modelos LLM y proveedores.
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
      className="view ops-models"
      style={{ padding: "24px", display: "flex", flexDirection: "column", gap: "20px" }}
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
            Métricas de Modelos LLM y Servicios Core
          </h1>
          <p style={{ fontSize: "0.8125rem", color: "var(--muted)", margin: "4px 0 0 0" }}>
            Disponibilidad, latencia, tasa de error, escalados entre tiers y segregación financiera
          </p>
        </div>

        <ControlesLiveRefresh hook={liveRefresh} />
      </header>

      {/* Filtros reactivos */}
      <section
        aria-label="Filtros de telemetría de modelos"
        className="card"
        style={{
          display: "flex",
          flexWrap: "wrap",
          alignItems: "flex-end",
          gap: "16px",
        }}
      >
        <div style={{ display: "flex", flexDirection: "column", gap: "6px" }}>
          <span style={{ fontSize: "12px", fontWeight: 600, color: "var(--muted)" }}>
            Ventana temporal
          </span>
          <div
            role="group"
            aria-label="Ventana temporal de modelos"
            data-testid="selector-ventana-models"
            style={{
              display: "inline-flex",
              borderRadius: "var(--radius-sm)",
              border: "1px solid var(--border)",
              overflow: "hidden",
              background: "var(--surface)",
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

        <div style={{ minWidth: "180px" }}>
          <Select
            id="ops-models-proveedor"
            etiqueta="Proveedor"
            data-testid="filtro-proveedor"
            value={proveedorFiltro}
            onChange={(e) => setProveedorFiltro(e.target.value)}
            opciones={[
              { valor: "todos", etiqueta: "Todos" },
              { valor: "anthropic", etiqueta: "Anthropic" },
              { valor: "google", etiqueta: "Google" },
              { valor: "deepseek", etiqueta: "DeepSeek" },
              { valor: "openai", etiqueta: "OpenAI" },
            ]}
          />
        </div>

        <div style={{ minWidth: "150px" }}>
          <Select
            id="ops-models-tier"
            etiqueta="Tier"
            data-testid="filtro-tier"
            value={tierFiltro}
            onChange={(e) => setTierFiltro(e.target.value)}
            opciones={[
              { valor: "todos", etiqueta: "Todos" },
              { valor: "flash", etiqueta: "Flash" },
              { valor: "pro", etiqueta: "Pro" },
              { valor: "fable", etiqueta: "Fable" },
            ]}
          />
        </div>

        <label
          style={{
            display: "inline-flex",
            alignItems: "center",
            gap: "8px",
            fontSize: "13px",
            cursor: "pointer",
            paddingBottom: "8px",
          }}
        >
          <input
            type="checkbox"
            data-testid="toggle-comparar-periodo"
            checked={compararPeriodo}
            onChange={(e) => setCompararPeriodo(e.target.checked)}
          />
          Comparar con período anterior
        </label>
      </section>

      {/* Salud de Servicios y Dependencias Core */}
      <section className="card" aria-label="Salud de dependencias e infraestructura" data-testid="panel-salud-servicios">
        <h2 style={{ fontSize: "14px", fontWeight: 650, margin: "0 0 12px 0" }}>
          Salud de Servicios y Dependencias Core
        </h2>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: "12px" }}>
          {[
            { clave: "postgres", etiqueta: "Postgres", ok: serviciosCore.postgres },
            { clave: "blob", etiqueta: "Blob Storage", ok: serviciosCore.blob },
            { clave: "telemetria", etiqueta: "Telemetría", ok: serviciosCore.telemetria },
            { clave: "agregados", etiqueta: "Agregados", ok: serviciosCore.agregados },
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
                {srv.ok ? "OPERATIVO" : "DEGRADADO"}
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
        mensajeCarga="Consultando métricas de modelos LLM y proveedores..."
        tituloError="Telemetría de modelos no disponible"
        tituloVacio="Sin métricas de modelos para el filtro aplicado"
        descripcionVacio="Ajusta el proveedor, el tier o la ventana temporal para visualizar resultados."
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
                Alerta crítica de disponibilidad (&lt; 99% en ventana de 1 hora):
              </strong>
              <ul style={{ margin: "6px 0 0 18px", fontSize: "13px" }}>
                {proveedoresDegradados1h.map((p) => (
                  <li key={`${p.proveedor}-${p.modelo}`}>
                    <strong>{p.proveedor}</strong> ({p.modelo}): {p.disponibilidad_pct.toFixed(2)}% de disponibilidad
                  </li>
                ))}
              </ul>
            </div>
          )}

          {/* Tarjetas de Escalados LLM */}
          <section
            aria-label="Escalados entre tiers LLM"
            style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", gap: "14px" }}
          >
            <article className="card" data-testid="kpi-escalado-flash-pro">
              <div style={{ fontSize: "12px", color: "var(--muted)" }}>Escalados Flash -&gt; Pro</div>
              <div style={{ fontSize: "24px", fontWeight: 700, color: "var(--accent)", marginTop: "4px" }}>
                {escalados.flash_a_pro}
              </div>
              {comparacionActiva && (
                <div style={{ fontSize: "12px", color: "var(--muted)", marginTop: "4px" }}>
                  vs anterior:{" "}
                  {calcularDeltaPorcentual(
                    escalados.flash_a_pro,
                    modelsData?.comparacion?.escalados.flash_a_pro
                  ) ?? "sin cambio"}
                </div>
              )}
            </article>

            <article className="card" data-testid="kpi-escalado-pro-fable">
              <div style={{ fontSize: "12px", color: "var(--muted)" }}>Escalados Pro -&gt; Fable</div>
              <div style={{ fontSize: "24px", fontWeight: 700, color: "var(--purple)", marginTop: "4px" }}>
                {escalados.pro_a_fable}
              </div>
              {comparacionActiva && (
                <div style={{ fontSize: "12px", color: "var(--muted)", marginTop: "4px" }}>
                  vs anterior:{" "}
                  {calcularDeltaPorcentual(
                    escalados.pro_a_fable,
                    modelsData?.comparacion?.escalados.pro_a_fable
                  ) ?? "sin cambio"}
                </div>
              )}
            </article>

            <article className="card" data-testid="kpi-escalado-humano">
              <div style={{ fontSize: "12px", color: "var(--muted)" }}>Escalados a Humano (Fallback)</div>
              <div style={{ fontSize: "24px", fontWeight: 700, color: "var(--warn)", marginTop: "4px" }}>
                {escalados.a_humano}
              </div>
              {comparacionActiva && (
                <div style={{ fontSize: "12px", color: "var(--muted)", marginTop: "4px" }}>
                  vs anterior:{" "}
                  {calcularDeltaPorcentual(
                    escalados.a_humano,
                    modelsData?.comparacion?.escalados.a_humano
                  ) ?? "sin cambio"}
                </div>
              )}
            </article>
          </section>

          {/* Desglose de Tokens Consumidos y Coste Estimado por Tier (sin mezclar Fable) */}
          <section
            aria-label="Tokens y coste estimado por tier"
            data-testid="desglose-costes-por-tier"
            style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", gap: "14px" }}
          >
            <article className="card" data-testid="card-tier-flash">
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                <span style={{ fontSize: "12px", fontWeight: 600, color: "var(--muted)" }}>
                  Consumo Tier Flash
                </span>
                <Badge style={estiloBadgeTier("flash")}>Flash</Badge>
              </div>
              <div style={{ fontSize: "20px", fontWeight: 700, marginTop: "6px" }}>
                {formatearTokens(tokensTier.flash)} tokens
              </div>
              <div style={{ fontSize: "13px", color: "var(--muted)", marginTop: "4px" }}>
                Coste estimado: <strong>{formatearEuro(costeTier.flash)}</strong>
              </div>
            </article>

            <article className="card" data-testid="card-tier-pro">
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                <span style={{ fontSize: "12px", fontWeight: 600, color: "var(--muted)" }}>
                  Consumo Tier Pro
                </span>
                <Badge style={estiloBadgeTier("pro")}>Pro</Badge>
              </div>
              <div style={{ fontSize: "20px", fontWeight: 700, marginTop: "6px" }}>
                {formatearTokens(tokensTier.pro)} tokens
              </div>
              <div style={{ fontSize: "13px", color: "var(--muted)", marginTop: "4px" }}>
                Coste estimado: <strong>{formatearEuro(costeTier.pro)}</strong>
              </div>
            </article>

            <article
              className="card"
              data-testid="card-tier-fable"
              style={{ border: "1px solid rgba(245, 158, 11, 0.55)" }}
            >
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                <span style={{ fontSize: "12px", fontWeight: 600, color: "var(--muted)" }}>
                  Consumo Tier Fable (Segregado)
                </span>
                <Badge style={estiloBadgeTier("fable")}>Fable</Badge>
              </div>
              <div style={{ fontSize: "20px", fontWeight: 700, marginTop: "6px" }}>
                {formatearTokens(tokensTier.fable)} tokens
              </div>
              <div style={{ fontSize: "13px", color: "var(--muted)", marginTop: "4px" }}>
                Coste independiente: <strong>{formatearEuro(costeTier.fable)}</strong>
              </div>
            </article>
          </section>

          {/* Tabla 1: Modelos Estándar (Flash y Pro) */}
          {modelosEstandar.length > 0 && (
            <TablaModelosSeccion
              testId="tabla-modelos-estandar"
              titulo="Rendimiento por Modelo y Proveedor — Tiers Estándar (Flash y Pro)"
              subtitulo="Ejecución operativa estándar agregada por ventana seleccionada, sin mezcla con Fable."
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
              titulo="Tier Fable — Razonamiento Avanzado (Segregación Estricta)"
              subtitulo="Reportado de forma independiente: sus llamadas, latencias y tarifas no se promedian con Flash ni Pro."
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
