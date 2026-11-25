/**
 * OpsAgents.tsx — Pantalla de Estado de Agentes de Producción, Colas y Rendimiento
 *
 * Observabilidad operativa en tiempo real conectada mediante TanStack Query a:
 * - GET /admin/v1/ops/agents?ventana=...
 * - GET /admin/v1/ops/queues?incluir_dlq=...
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
import { formatDecimal, formatNumber } from "../i18n/formatters";
import { ControlesLiveRefresh } from "../componentes/ControlesLiveRefresh";
import { ContenedorEstado } from "../componentes/ContenedorEstado";
import { EstadoError } from "../componentes/EstadoError";
import { Badge, BadgeVariante } from "../componentes/Badge";
import { Boton } from "../componentes/Boton";
import { useInsideAdminLayout } from "../componentes/AdminLayout";
import {
  Tabla,
  TablaEncabezado,
  TablaCuerpo,
  TablaFila,
  TablaCelda,
  TablaCeldaEncabezado,
} from "../componentes/Tabla";

export type VentanaAgentes = "5m" | "1h" | "24h";

export type EtapaPipelineNombre =
  | "triage"
  | "design"
  | "build"
  | "qa"
  | "security"
  | "deploy";

export const ETAPAS_CANONICAS: readonly EtapaPipelineNombre[] = [
  "triage",
  "design",
  "build",
  "qa",
  "security",
  "deploy",
];

const VENTANAS_PERMITIDAS: readonly VentanaAgentes[] = ["5m", "1h", "24h"];
const ROLES_OPERACIONES_PERMITIDOS = new Set(["staff_operaciones", "staff_admin"]);
const UMBRAL_TELEMETRIA_OBSOLETA_S = 300; // 5 minutos

export interface TelemetriaEstado {
  disponible: boolean;
  antiguedad_s: number | null;
  desde?: string | null;
}

export interface LineasEstado {
  activas: number | null;
  mantenimiento: number | null;
  libres: number | null;
}

export interface EtapaEstado {
  etapa?: string;
  nombre?: string;
  agentes_total?: number | null;
  agentes_ocupados?: number | null;
  agentes_caidos?: number | null;
  jobs_completados?: number | null;
  duracion_p95_s?: number | null;
  // Compatibilidad con formato heredado (opsVistas.test.tsx)
  activos?: number | null;
  ocupados?: number | null;
  caidos?: number | null;
  jobs_en_curso?: number | null;
}

export interface AlertaOperativaAgents {
  tipo?: string;
  etapa?: string | null;
  linea?: string | null;
  mensaje?: string | null;
  valor?: number | null;
  umbral?: number | null;
}

export interface ColaEstado {
  nombre: string;
  pendientes?: number | null;
  reclamados?: number | null;
  fallidos?: number | null;
  profundidad?: number | null;
  no_confirmados?: number | null;
  dlq?: number | null;
  antiguedad_max_s: number | null;
  umbral_atencion_s?: number | null;
  estado: "normal" | "atencion" | "critico" | string;
}

export interface RespuestaOpsAgents {
  ventana?: string;
  telemetria: TelemetriaEstado;
  agentes_total?: number | null;
  agentes_ocupados?: number | null;
  agentes_caidos?: number | null;
  jobs_completados?: number | null;
  duracion_p95_s?: number | null;
  lineas: LineasEstado | null;
  etapas: EtapaEstado[] | null;
  alertas?: AlertaOperativaAgents[];
}

export interface ResumenColas {
  criticas: number;
  atencion: number;
  pendientes_total: number;
  fallidos_total: number;
}

export interface RespuestaOpsQueues {
  telemetria_desde?: string | null;
  resumen?: ResumenColas;
  colas: ColaEstado[];
}

/** Contrato de compatibilidad con pruebas heredadas sin TanStack Query padre */
export interface OpsAgentsDatos {
  ventana?: VentanaAgentes;
  telemetria: TelemetriaEstado;
  lineas: LineasEstado | null;
  etapas: EtapaEstado[] | null;
  colas: ColaEstado[];
  alertas?: AlertaOperativaAgents[];
}

export interface OpsAgentsProps {
  datosIniciales?: OpsAgentsDatos;
  obtenerAgentes?: (ventana: VentanaAgentes) => Promise<RespuestaOpsAgents>;
  obtenerColas?: (incluirDlq: boolean) => Promise<RespuestaOpsQueues>;
}

const DATOS_AGENTES_FALLBACK: RespuestaOpsAgents = {
  ventana: "1h",
  telemetria: { disponible: true, antiguedad_s: 4 },
  agentes_total: 25,
  agentes_ocupados: 18,
  agentes_caidos: 1,
  jobs_completados: 142,
  duracion_p95_s: 38.5,
  lineas: { activas: 12, mantenimiento: 1, libres: 5 },
  etapas: [
    { etapa: "triage", agentes_total: 4, agentes_ocupados: 2, agentes_caidos: 0, jobs_completados: 42, duracion_p95_s: 12.4 },
    { etapa: "design", agentes_total: 4, agentes_ocupados: 3, agentes_caidos: 0, jobs_completados: 28, duracion_p95_s: 26.8 },
    { etapa: "build", agentes_total: 8, agentes_ocupados: 6, agentes_caidos: 1, jobs_completados: 36, duracion_p95_s: 54.2 },
    { etapa: "qa", agentes_total: 4, agentes_ocupados: 3, agentes_caidos: 0, jobs_completados: 19, duracion_p95_s: 41.0 },
    { etapa: "security", agentes_total: 3, agentes_ocupados: 2, agentes_caidos: 0, jobs_completados: 11, duracion_p95_s: 33.5 },
    { etapa: "deploy", agentes_total: 2, agentes_ocupados: 2, agentes_caidos: 0, jobs_completados: 6, duracion_p95_s: 48.0 },
  ],
  alertas: [
    {
      tipo: "agentes_caidos",
      etapa: "build",
      mensaje: "1 agente sin latido en etapa build",
      valor: 1,
      umbral: 0,
    },
  ],
};

const DATOS_COLAS_FALLBACK: RespuestaOpsQueues = {
  resumen: {
    criticas: 1,
    atencion: 1,
    pendientes_total: 104,
    fallidos_total: 2,
  },
  colas: [
    {
      nombre: "kc:inbox",
      pendientes: 14,
      reclamados: 3,
      fallidos: 0,
      antiguedad_max_s: 12,
      umbral_atencion_s: 60,
      estado: "normal",
    },
    {
      nombre: "cola_generacion",
      pendientes: 78,
      reclamados: 12,
      fallidos: 0,
      antiguedad_max_s: 75,
      umbral_atencion_s: 60,
      estado: "atencion",
    },
    {
      nombre: "kc:dlq",
      pendientes: 2,
      reclamados: 0,
      fallidos: 2,
      antiguedad_max_s: 320,
      umbral_atencion_s: 0,
      estado: "critico",
    },
  ],
};

function calcularAntiguedadEfectiva(telemetria?: TelemetriaEstado): number | null {
  if (!telemetria || !telemetria.disponible) return null;
  if (typeof telemetria.antiguedad_s === "number" && Number.isFinite(telemetria.antiguedad_s)) {
    return Math.max(0, Math.round(telemetria.antiguedad_s));
  }
  if (telemetria.desde) {
    const ms = Date.now() - new Date(telemetria.desde).getTime();
    if (Number.isFinite(ms)) {
      return Math.max(0, Math.round(ms / 1000));
    }
  }
  return null;
}

function valorMetrica(
  telemetriaActiva: boolean,
  valor: number | null | undefined,
  lang?: string
): string {
  if (!telemetriaActiva || valor === null || valor === undefined || !Number.isFinite(valor)) {
    return "—";
  }
  return formatNumber(valor, undefined, lang);
}

function prioridadEstadoCola(estado: string): number {
  const normalizado = estado.toLowerCase();
  if (normalizado === "critico") return 3;
  if (normalizado === "atencion") return 2;
  return 1;
}

function badgeEstadoCola(
  estado: string,
  t: (key: string) => string
): { variante: BadgeVariante; etiqueta: string } {
  const normalizado = estado.toLowerCase();
  if (normalizado === "critico") {
    return { variante: "error", etiqueta: t("views.opsAgents.queues.statuses.critico") };
  }
  if (normalizado === "atencion") {
    return { variante: "advertencia", etiqueta: t("views.opsAgents.queues.statuses.atencion") };
  }
  return { variante: "exito", etiqueta: t("views.opsAgents.queues.statuses.normal") };
}

interface EtapaNormalizada {
  etapa: string;
  agentes_total: number | null;
  agentes_ocupados: number | null;
  agentes_caidos: number | null;
  jobs_completados: number | null;
  duracion_p95_s: number | null;
}

function normalizarEtapasPipeline(
  etapasPayload: EtapaEstado[] | null | undefined,
  telemetriaActiva: boolean
): EtapaNormalizada[] {
  const mapa = new Map<string, EtapaEstado>();
  if (Array.isArray(etapasPayload)) {
    for (const item of etapasPayload) {
      const clave = (item.etapa ?? item.nombre ?? "").toLowerCase();
      if (clave) {
        mapa.set(clave, item);
      }
    }
  }

  const nombres = [...ETAPAS_CANONICAS] as string[];
  for (const clave of mapa.keys()) {
    if (!nombres.includes(clave)) {
      nombres.push(clave);
    }
  }

  return nombres.map((nombre) => {
    const raw = mapa.get(nombre);
    if (!telemetriaActiva || !raw) {
      return {
        etapa: nombre,
        agentes_total: null,
        agentes_ocupados: null,
        agentes_caidos: null,
        jobs_completados: null,
        duracion_p95_s: null,
      };
    }

    return {
      etapa: nombre,
      agentes_total: raw.agentes_total ?? raw.activos ?? null,
      agentes_ocupados: raw.agentes_ocupados ?? raw.ocupados ?? null,
      agentes_caidos: raw.agentes_caidos ?? raw.caidos ?? null,
      jobs_completados: raw.jobs_completados ?? raw.jobs_en_curso ?? null,
      duracion_p95_s: raw.duracion_p95_s ?? null,
    };
  });
}

interface OpsAgentsInternoProps extends OpsAgentsProps {
  usarFallbackLocal?: boolean;
}

const OpsAgentsInterno: React.FC<OpsAgentsInternoProps> = ({
  datosIniciales,
  obtenerAgentes,
  obtenerColas,
  usarFallbackLocal = false,
}) => {
  const { t, i18n } = useTranslation();
  const lang = i18n.resolvedLanguage || i18n.language;
  const insideLayout = useInsideAdminLayout();
  const RbacTag: React.ElementType = insideLayout ? "div" : "main";
  const auth = useOptionalAuth();
  const usuario = auth?.usuario ?? null;

  const formatearAntiguedadRelativa = (segundos: number | null): string => {
    if (segundos === null) return t("views.opsAgents.telemetry.noTelemetry");
    if (segundos < 60) return t("views.opsAgents.telemetry.secondsAgo", { count: segundos });
    const minutos = Math.round(segundos / 60);
    if (minutos < 60) return t("views.opsAgents.telemetry.minutesAgo", { count: minutos });
    const horas = Math.round(minutos / 60);
    return t("views.opsAgents.telemetry.hoursAgo", { count: horas });
  };

  const [ventana, setVentana] = useState<VentanaAgentes>(
    datosIniciales?.ventana ?? "1h"
  );
  const [incluirDlq, setIncluirDlq] = useState<boolean>(true);
  const [mostrarTodasColumnas, setMostrarTodasColumnas] = useState<boolean>(false);

  const rolNoAutorizado =
    Boolean(usuario) && !ROLES_OPERACIONES_PERMITIDOS.has(usuario?.role ?? "");

  const initialAgentsData: RespuestaOpsAgents | undefined = useMemo(() => {
    if (datosIniciales) {
      return {
        ventana: datosIniciales.ventana ?? "1h",
        telemetria: datosIniciales.telemetria,
        lineas: datosIniciales.lineas,
        etapas: datosIniciales.etapas,
        alertas: datosIniciales.alertas ?? [],
      };
    }
    if (usarFallbackLocal) {
      return DATOS_AGENTES_FALLBACK;
    }
    return undefined;
  }, [datosIniciales, usarFallbackLocal]);

  const initialQueuesData: RespuestaOpsQueues | undefined = useMemo(() => {
    if (datosIniciales) {
      return {
        colas: datosIniciales.colas ?? [],
      };
    }
    if (usarFallbackLocal) {
      return DATOS_COLAS_FALLBACK;
    }
    return undefined;
  }, [datosIniciales, usarFallbackLocal]);

  const consultarAgentes = useCallback(async (): Promise<RespuestaOpsAgents> => {
    if (obtenerAgentes) {
      return obtenerAgentes(ventana);
    }
    return peticionApi<RespuestaOpsAgents>("/admin/v1/ops/agents", {
      params: { ventana },
    });
  }, [obtenerAgentes, ventana]);

  const consultarColas = useCallback(async (): Promise<RespuestaOpsQueues> => {
    if (obtenerColas) {
      return obtenerColas(incluirDlq);
    }
    return peticionApi<RespuestaOpsQueues>("/admin/v1/ops/queues", {
      params: { incluir_dlq: incluirDlq },
    });
  }, [obtenerColas, incluirDlq]);

  const habilitadoQuery =
    !rolNoAutorizado && !usarFallbackLocal && datosIniciales === undefined;

  const {
    data: agentesData,
    isLoading: isLoadingAgentes,
    isFetching: isFetchingAgentes,
    error: errorAgentes,
    refetch: refetchAgentes,
  } = useQuery<RespuestaOpsAgents>({
    queryKey: ["ops-agents", ventana, Boolean(obtenerAgentes)],
    queryFn: consultarAgentes,
    enabled: habilitadoQuery,
    initialData: initialAgentsData,
    placeholderData: (prev) => prev,
    staleTime: 10_000,
  });

  const {
    data: colasData,
    isLoading: isLoadingColas,
    isFetching: isFetchingColas,
    error: errorColas,
    refetch: refetchColas,
  } = useQuery<RespuestaOpsQueues>({
    queryKey: ["ops-queues", incluirDlq, Boolean(obtenerColas)],
    queryFn: consultarColas,
    enabled: habilitadoQuery,
    initialData: initialQueuesData,
    placeholderData: (prev) => prev,
    staleTime: 10_000,
  });

  const refrescarTodo = useCallback(async () => {
    if (rolNoAutorizado || !habilitadoQuery) return;
    await Promise.all([refetchAgentes(), refetchColas()]);
  }, [rolNoAutorizado, habilitadoQuery, refetchAgentes, refetchColas]);

  const liveRefresh = useLiveRefresh({
    intervaloMs: 15_000,
    ejecutarAlInicio: false,
    alRefrescar: refrescarTodo,
    estaConsultando: isFetchingAgentes || isFetchingColas,
    refrescarAlVolverVisible: true,
    peticionesPorCiclo: 2,
    pausarEnSegundoPlano: true,
    pausarEnPerdidaFoco: true,
  });

  const etapasNormalizadas = useMemo(() => {
    const telemetriaOk = Boolean(agentesData?.telemetria?.disponible) && !errorAgentes;
    return normalizarEtapasPipeline(agentesData?.etapas, telemetriaOk);
  }, [agentesData, errorAgentes]);

  const colasOrdenadas = useMemo(() => {
    const base = colasData?.colas ?? [];
    const filtradas = incluirDlq
      ? base
      : base.filter((c) => !c.nombre.toLowerCase().includes("dlq") && (c.fallidos ?? c.dlq ?? 0) === 0);

    return [...filtradas].sort((a, b) => {
      const diffPrioridad = prioridadEstadoCola(b.estado) - prioridadEstadoCola(a.estado);
      if (diffPrioridad !== 0) return diffPrioridad;
      const profA = a.pendientes ?? a.profundidad ?? 0;
      const profB = b.pendientes ?? b.profundidad ?? 0;
      return profB - profA;
    });
  }, [colasData, incluirDlq]);

  const cargaInicial = isLoadingAgentes && isLoadingColas;
  const errorTotal = errorAgentes && (errorColas || !colasData) ? errorAgentes : null;

  const telemetriaDisponible =
    Boolean(agentesData?.telemetria?.disponible) && !errorAgentes;
  const antiguedadS = calcularAntiguedadEfectiva(agentesData?.telemetria);
  const telemetriaObsoleta =
    telemetriaDisponible &&
    antiguedadS !== null &&
    antiguedadS > UMBRAL_TELEMETRIA_OBSOLETA_S;

  const alertasEtapaSet = new Set(
    (agentesData?.alertas ?? [])
      .map((a) => a.etapa?.toLowerCase())
      .filter((e): e is string => Boolean(e))
  );

  // Totales de agentes: usa campos de nivel raíz o suma de etapas si no vienen informados
  const totalAgentes = useMemo(() => {
    if (!telemetriaDisponible) return null;
    if (typeof agentesData?.agentes_total === "number") return agentesData.agentes_total;
    if (!agentesData?.etapas) return null;
    return etapasNormalizadas.reduce((acc, e) => acc + (e.agentes_total ?? 0), 0);
  }, [telemetriaDisponible, agentesData, etapasNormalizadas]);

  const agentesOcupados = useMemo(() => {
    if (!telemetriaDisponible) return null;
    if (typeof agentesData?.agentes_ocupados === "number") return agentesData.agentes_ocupados;
    if (!agentesData?.etapas) return null;
    return etapasNormalizadas.reduce((acc, e) => acc + (e.agentes_ocupados ?? 0), 0);
  }, [telemetriaDisponible, agentesData, etapasNormalizadas]);

  const agentesCaidos = useMemo(() => {
    if (!telemetriaDisponible) return null;
    if (typeof agentesData?.agentes_caidos === "number") return agentesData.agentes_caidos;
    if (!agentesData?.etapas) return null;
    return etapasNormalizadas.reduce((acc, e) => acc + (e.agentes_caidos ?? 0), 0);
  }, [telemetriaDisponible, agentesData, etapasNormalizadas]);

  // Totales de colas
  const colasDisponible = Boolean(colasData) && !errorColas;
  const totalPendientesColas = colasDisponible
    ? colasData?.resumen?.pendientes_total ??
      colasOrdenadas.reduce((acc, c) => acc + (c.pendientes ?? c.profundidad ?? 0), 0)
    : null;
  const totalFallidosColas = colasDisponible
    ? colasData?.resumen?.fallidos_total ??
      colasOrdenadas.reduce((acc, c) => acc + (c.fallidos ?? c.dlq ?? 0), 0)
    : null;
  const totalColasAlerta = colasDisponible
    ? colasData?.resumen
      ? (colasData.resumen.criticas ?? 0) + (colasData.resumen.atencion ?? 0)
      : colasOrdenadas.filter((c) => c.estado === "critico" || c.estado === "atencion").length
    : null;

  if (rolNoAutorizado) {
    return (
      <RbacTag
        className="view ops-agents"
        data-testid="ops-agents-rbac-bloqueado"
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
          {t("views.opsAgents.rbacDenied", { role: usuario?.role })}
        </p>
      </RbacTag>
    );
  }

  return (
    <div className="ops-agents kc-view-container">
      {/* Cabecera */}
      <header
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "flex-start",
          flexWrap: "wrap",
          gap: "16px",
        }}
      >
        <div>
          <h1 style={{ fontSize: "20px", fontWeight: 700, margin: 0, color: "var(--text)" }}>
            {t("views.opsAgents.title")}
          </h1>
          <p style={{ margin: "4px 0 0", fontSize: "13px", color: "var(--muted)" }}>
            {t("views.opsAgents.subtitle")}
          </p>
        </div>

        <div className="kc-toolbar-actions">
          <div
            role="group"
            aria-label={t("views.opsAgents.windowGroupAria")}
            data-testid="selector-ventana-agents"
            className="kc-tabs-scroll"
            style={{
              borderRadius: "var(--radius-sm)",
              border: "1px solid var(--border)",
              background: "var(--surface)",
            }}
          >
            {VENTANAS_PERMITIDAS.map((v) => {
              const activa = ventana === v;
              return (
                <button
                  key={v}
                  type="button"
                  data-testid={`btn-ventana-${v}`}
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

          <ControlesLiveRefresh hook={liveRefresh} />
        </div>
      </header>

      <ContenedorEstado
        cargando={cargaInicial}
        error={errorTotal}
        vacio={false}
        tipoCarga="kpis"
        tarjetasCarga={4}
        mensajeCarga={t("views.opsAgents.loadingMessage")}
        tituloError={t("views.opsAgents.errorTitle")}
        dataTestIdCarga="ops-agents-loading"
        dataTestIdError="ops-agents-error"
        dataTestIdTrace="ops-agents-trace-id"
        alReintentar={refrescarTodo}
        reintentando={isFetchingAgentes || isFetchingColas}
      >
        {/* Indicador de estado y frescura de telemetría */}
        <section
          aria-label={t("views.opsAgents.telemetry.regionLabel")}
          data-testid="indicador-telemetria"
          style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
            flexWrap: "wrap",
            gap: "12px",
            padding: "10px 14px",
            borderRadius: "var(--radius-sm)",
            border: "1px solid var(--border)",
            background: "var(--surface)",
          }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
            {!telemetriaDisponible ? (
              <Badge variante="error" punto>
                {t("views.opsAgents.telemetry.down")}
              </Badge>
            ) : telemetriaObsoleta ? (
              <Badge variante="advertencia" punto>
                {t("views.opsAgents.telemetry.stale")}
              </Badge>
            ) : (
              <Badge variante="exito" punto>
                {t("views.opsAgents.telemetry.available")}
              </Badge>
            )}
            <span style={{ fontSize: "13px", color: "var(--muted)" }}>
              {t("views.opsAgents.telemetry.windowSuffix", {
                relative: formatearAntiguedadRelativa(antiguedadS),
                window: ventana,
              })}
            </span>
          </div>

          {(agentesData?.alertas?.length ?? 0) > 0 && telemetriaDisponible && (
            <Badge variante="advertencia">
              {t("views.opsAgents.telemetry.activeAlertsCount", {
                count: agentesData?.alertas?.length ?? 0,
              })}
            </Badge>
          )}
        </section>

        {/* Banner explícito si telemetría no está disponible */}
        {!telemetriaDisponible && (
          <div
            data-testid="banner-sin-telemetria"
            role="alert"
            style={{
              padding: "14px 16px",
              borderRadius: "var(--radius-sm)",
              border: "1px solid var(--bad)",
              background: "var(--bad-bg)",
              color: "var(--text)",
              display: "flex",
              flexDirection: "column",
              gap: "8px",
            }}
          >
            <strong style={{ fontSize: "14px" }}>
              {t("views.opsAgents.telemetry.bannerTitle")}
            </strong>
            <span style={{ fontSize: "13px", color: "var(--muted)" }}>
              {t("views.opsAgents.telemetry.bannerSubtitle")}
            </span>
            {errorAgentes && (
              <EstadoError
                error={errorAgentes}
                compacto
                data-testid="ops-agents-partial-error"
                dataTestIdTrace="ops-agents-partial-trace-id"
                alReintentar={() => {
                  void refetchAgentes();
                }}
                reintentando={isFetchingAgentes}
              />
            )}
          </div>
        )}

        {/* Alerta visual cuando la telemetría supera los 5 minutos */}
        {telemetriaObsoleta && (
          <div
            data-testid="banner-telemetria-desactualizada"
            role="alert"
            style={{
              padding: "12px 16px",
              borderRadius: "var(--radius-sm)",
              border: "1px solid var(--warn)",
              background: "var(--warn-bg)",
              color: "var(--text)",
              fontSize: "13px",
            }}
          >
            <strong>{t("views.opsAgents.telemetry.staleBannerPrefix")}</strong>{" "}
            {t("views.opsAgents.telemetry.staleBannerBody", {
              relative: formatearAntiguedadRelativa(antiguedadS),
            })}
          </div>
        )}

        {/* Tarjetas de cabecera: Líneas de Producción, Agentes y Colas */}
        <section
          aria-label={t("views.opsAgents.summary.regionLabel")}
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))",
            gap: "16px",
          }}
        >
          {/* Líneas de Producción */}
          <article
            className="card"
            data-testid="kpi-lineas"
            style={{ padding: "16px", border: "1px solid var(--border)", borderRadius: "var(--radius-md)", background: "var(--surface)" }}
          >
            <div style={{ fontSize: "12px", fontWeight: 600, color: "var(--muted)", textTransform: "uppercase" }}>
              {t("views.opsAgents.summary.linesTitle")}
            </div>
            <div style={{ fontSize: "24px", fontWeight: 700, marginTop: "6px", color: "var(--text)" }}>
              {t("views.opsAgents.summary.linesActive", {
                count: valorMetrica(telemetriaDisponible, agentesData?.lineas?.activas, lang),
              })}
            </div>
            <div style={{ marginTop: "8px", fontSize: "13px", color: "var(--muted)", display: "flex", gap: "12px" }}>
              <span>
                {t("views.opsAgents.summary.linesMaintenance")}{" "}
                <strong>{valorMetrica(telemetriaDisponible, agentesData?.lineas?.mantenimiento, lang)}</strong>
              </span>
              <span>
                {t("views.opsAgents.summary.linesFree")}{" "}
                <strong>{valorMetrica(telemetriaDisponible, agentesData?.lineas?.libres, lang)}</strong>
              </span>
            </div>
          </article>

          {/* Resumen de Agentes */}
          <article
            className="card"
            data-testid="kpi-agentes"
            style={{ padding: "16px", border: "1px solid var(--border)", borderRadius: "var(--radius-md)", background: "var(--surface)" }}
          >
            <div style={{ fontSize: "12px", fontWeight: 600, color: "var(--muted)", textTransform: "uppercase" }}>
              {t("views.opsAgents.summary.agentsTitle")}
            </div>
            <div style={{ fontSize: "24px", fontWeight: 700, marginTop: "6px", color: "var(--text)" }}>
              {t("views.opsAgents.summary.agentsBusy", {
                busy: valorMetrica(telemetriaDisponible, agentesOcupados, lang),
                total: valorMetrica(telemetriaDisponible, totalAgentes, lang),
              })}
            </div>
            <div style={{ marginTop: "8px", fontSize: "13px", color: "var(--muted)", display: "flex", gap: "12px", alignItems: "center" }}>
              <span>
                {t("views.opsAgents.summary.agentsTotal")}{" "}
                <strong>{valorMetrica(telemetriaDisponible, totalAgentes, lang)}</strong>
              </span>
              <span>
                {t("views.opsAgents.summary.agentsDown")}{" "}
                <strong style={{ color: (agentesCaidos ?? 0) > 0 && telemetriaDisponible ? "var(--bad)" : "inherit" }}>
                  {valorMetrica(telemetriaDisponible, agentesCaidos, lang)}
                </strong>
              </span>
            </div>
          </article>

          {/* Resumen de Colas */}
          <article
            className="card"
            data-testid="kpi-colas"
            style={{ padding: "16px", border: "1px solid var(--border)", borderRadius: "var(--radius-md)", background: "var(--surface)" }}
          >
            <div style={{ fontSize: "12px", fontWeight: 600, color: "var(--muted)", textTransform: "uppercase" }}>
              {t("views.opsAgents.summary.queuesTitle")}
            </div>
            <div style={{ fontSize: "24px", fontWeight: 700, marginTop: "6px", color: "var(--text)" }}>
              {t("views.opsAgents.summary.queuesPending", {
                count: valorMetrica(colasDisponible, totalPendientesColas, lang),
              })}
            </div>
            <div style={{ marginTop: "8px", fontSize: "13px", color: "var(--muted)", display: "flex", gap: "12px" }}>
              <span>
                {t("views.opsAgents.summary.queuesFailed")}{" "}
                <strong>{valorMetrica(colasDisponible, totalFallidosColas, lang)}</strong>
              </span>
              <span>
                {t("views.opsAgents.summary.queuesAttention")}{" "}
                <strong>{valorMetrica(colasDisponible, totalColasAlerta, lang)}</strong>
              </span>
            </div>
          </article>
        </section>

        {/* Alertas activas declaradas */}
        {telemetriaDisponible && (agentesData?.alertas?.length ?? 0) > 0 && (
          <section
            aria-label={t("views.opsAgents.alerts.regionLabel")}
            data-testid="lista-alertas-etapas"
            style={{
              padding: "12px 16px",
              borderRadius: "var(--radius-sm)",
              border: "1px solid var(--warn)",
              background: "var(--warn-bg)",
              display: "flex",
              flexDirection: "column",
              gap: "6px",
            }}
          >
            <strong style={{ fontSize: "13px" }}>{t("views.opsAgents.alerts.title")}</strong>
            <ul style={{ margin: 0, paddingLeft: "18px", fontSize: "13px" }}>
              {agentesData?.alertas?.map((alerta, idx) => (
                <li key={`${alerta.etapa ?? "global"}-${idx}`}>
                  {alerta.etapa ? <strong>{alerta.etapa}: </strong> : null}
                  {alerta.mensaje ||
                    t("views.opsAgents.alerts.thresholdExceeded", {
                      type: alerta.tipo ?? t("views.opsAgents.alerts.defaultType"),
                    })}
                </li>
              ))}
            </ul>
          </section>
        )}

        {/* Panel por Etapa del Pipeline */}
        <section aria-label={t("views.opsAgents.stages.regionLabel")}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "12px" }}>
            <h2 style={{ fontSize: "16px", fontWeight: 600, margin: 0 }}>
              {t("views.opsAgents.stages.title")}
            </h2>
            {!telemetriaDisponible && (
              <Badge variante="neutro">{t("views.opsAgents.stages.noTelemetryBadge")}</Badge>
            )}
          </div>

          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))",
              gap: "12px",
            }}
          >
            {etapasNormalizadas.map((etapa) => {
              const tieneAlerta =
                telemetriaDisponible &&
                (alertasEtapaSet.has(etapa.etapa.toLowerCase()) ||
                  (etapa.agentes_caidos ?? 0) > 0);

              return (
                <article
                  key={etapa.etapa}
                  data-testid={`etapa-${etapa.etapa}`}
                  style={{
                    padding: "14px",
                    borderRadius: "var(--radius-md)",
                    border: tieneAlerta ? "1px solid var(--warn)" : "1px solid var(--border)",
                    background: "var(--surface)",
                    display: "flex",
                    flexDirection: "column",
                    gap: "8px",
                  }}
                >
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                    <strong style={{ fontSize: "14px", color: "var(--text)" }}>
                      {etapa.etapa}
                    </strong>
                    {tieneAlerta ? (
                      <Badge variante="advertencia">{t("views.opsAgents.stages.badgeAlert")}</Badge>
                    ) : !telemetriaDisponible ? (
                      <Badge variante="neutro">{t("views.opsAgents.stages.badgeNoTelemetry")}</Badge>
                    ) : (
                      <Badge variante="exito">{t("views.opsAgents.stages.badgeOperational")}</Badge>
                    )}
                  </div>

                  <dl
                    style={{
                      display: "grid",
                      gridTemplateColumns: "1fr auto",
                      rowGap: "4px",
                      columnGap: "8px",
                      margin: 0,
                      fontSize: "13px",
                    }}
                  >
                    <dt style={{ color: "var(--muted)" }}>{t("views.opsAgents.stages.totalAgents")}</dt>
                    <dd style={{ margin: 0, fontWeight: 600 }}>
                      {valorMetrica(telemetriaDisponible, etapa.agentes_total, lang)}
                    </dd>

                    <dt style={{ color: "var(--muted)" }}>{t("views.opsAgents.stages.busy")}</dt>
                    <dd style={{ margin: 0, fontWeight: 600 }}>
                      {valorMetrica(telemetriaDisponible, etapa.agentes_ocupados, lang)}
                    </dd>

                    <dt style={{ color: "var(--muted)" }}>{t("views.opsAgents.stages.down")}</dt>
                    <dd
                      style={{
                        margin: 0,
                        fontWeight: 600,
                        color: tieneAlerta && (etapa.agentes_caidos ?? 0) > 0 ? "var(--bad)" : "inherit",
                      }}
                    >
                      {valorMetrica(telemetriaDisponible, etapa.agentes_caidos, lang)}
                    </dd>

                    <dt style={{ color: "var(--muted)" }}>{t("views.opsAgents.stages.completedJobs")}</dt>
                    <dd style={{ margin: 0, fontWeight: 600 }}>
                      {valorMetrica(telemetriaDisponible, etapa.jobs_completados, lang)}
                    </dd>

                    <dt style={{ color: "var(--muted)" }}>{t("views.opsAgents.stages.p95Duration")}</dt>
                    <dd style={{ margin: 0, fontWeight: 600 }}>
                      {telemetriaDisponible && typeof etapa.duracion_p95_s === "number"
                        ? t("views.opsAgents.stages.secondsValue", {
                            seconds: formatDecimal(etapa.duracion_p95_s, 1, lang),
                          })
                        : t("common.states.noData")}
                    </dd>
                  </dl>
                </article>
              );
            })}
          </div>
        </section>

        {/* Tabla Densa de Colas del Pipeline */}
        <section
          aria-label={t("views.opsAgents.queues.regionLabel")}
          style={{
            padding: "16px",
            borderRadius: "var(--radius-md)",
            border: "1px solid var(--border)",
            background: "var(--surface)",
            display: "flex",
            flexDirection: "column",
            gap: "12px",
          }}
        >
          <div
            style={{
              display: "flex",
              justifyContent: "space-between",
              alignItems: "center",
              flexWrap: "wrap",
              gap: "12px",
            }}
          >
            <h2 style={{ fontSize: "16px", fontWeight: 600, margin: 0 }}>
              {t("views.opsAgents.queues.title")}
            </h2>

            <div className="kc-toolbar-actions">
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
                  data-testid="toggle-incluir-dlq"
                  checked={incluirDlq}
                  onChange={(e) => setIncluirDlq(e.target.checked)}
                />
                {t("views.opsAgents.queues.includeDlq")}
              </label>
            </div>
          </div>

          <ContenedorEstado
            cargando={isLoadingColas && !colasData}
            error={errorColas}
            vacio={!errorColas && colasOrdenadas.length === 0}
            tipoCarga="tabla"
            filasCarga={4}
            columnasCarga={6}
            tituloError={t("views.opsAgents.queues.errorTitle")}
            dataTestIdError="ops-queues-error"
            dataTestIdTrace="ops-queues-trace-id"
            tituloVacio={t("views.opsAgents.queues.emptyTitle")}
            descripcionVacio={t("views.opsAgents.queues.emptyDescription")}
            compacto
            alReintentar={() => {
              void refetchColas();
            }}
            reintentando={isFetchingColas}
          >
            <Tabla
              data-testid="tabla-colas-ops"
              densidad="alta"
              mostrarTodasColumnas={mostrarTodasColumnas}
            >
              <TablaEncabezado>
                <TablaFila>
                  <TablaCeldaEncabezado scope="col" fija>{t("views.opsAgents.queues.colQueue")}</TablaCeldaEncabezado>
                  <TablaCeldaEncabezado scope="col">{t("views.opsAgents.queues.colPending")}</TablaCeldaEncabezado>
                  <TablaCeldaEncabezado scope="col" prioridad="media">{t("views.opsAgents.queues.colClaimed")}</TablaCeldaEncabezado>
                  <TablaCeldaEncabezado scope="col">{t("views.opsAgents.queues.colFailed")}</TablaCeldaEncabezado>
                  <TablaCeldaEncabezado scope="col" prioridad="baja">{t("views.opsAgents.queues.colMaxAge")}</TablaCeldaEncabezado>
                  <TablaCeldaEncabezado scope="col">{t("views.opsAgents.queues.colStatus")}</TablaCeldaEncabezado>
                </TablaFila>
              </TablaEncabezado>
              <TablaCuerpo>
                {colasOrdenadas.map((cola) => {
                  const pendientes = cola.pendientes ?? cola.profundidad ?? null;
                  const reclamados = cola.reclamados ?? cola.no_confirmados ?? null;
                  const fallidos = cola.fallidos ?? cola.dlq ?? null;
                  const badge = badgeEstadoCola(cola.estado, t);

                  return (
                    <TablaFila key={cola.nombre} data-testid={`fila-cola-${cola.nombre}`}>
                      <TablaCelda fija>
                        <strong>{cola.nombre}</strong>
                      </TablaCelda>
                      <TablaCelda>
                        {pendientes !== null ? formatNumber(pendientes, undefined, lang) : t("common.states.noData")}
                      </TablaCelda>
                      <TablaCelda prioridad="media">
                        {reclamados !== null ? formatNumber(reclamados, undefined, lang) : t("common.states.noData")}
                      </TablaCelda>
                      <TablaCelda>
                        {fallidos !== null ? formatNumber(fallidos, undefined, lang) : t("common.states.noData")}
                      </TablaCelda>
                      <TablaCelda prioridad="baja">
                        {cola.antiguedad_max_s !== null && cola.antiguedad_max_s !== undefined
                          ? t("views.opsAgents.queues.secondsValue", {
                              seconds: formatNumber(cola.antiguedad_max_s, undefined, lang),
                            })
                          : t("common.states.noData")}
                      </TablaCelda>
                      <TablaCelda>
                        <Badge variante={badge.variante} punto>
                          {badge.etiqueta}
                        </Badge>
                      </TablaCelda>
                    </TablaFila>
                  );
                })}
              </TablaCuerpo>
            </Tabla>
          </ContenedorEstado>
        </section>
      </ContenedorEstado>
    </div>
  );
};

export const OpsAgents: React.FC<OpsAgentsProps> = (props) => {
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
    return <OpsAgentsInterno {...props} />;
  }

  return (
    <QueryClientProvider client={fallbackClient}>
      <OpsAgentsInterno
        {...props}
        usarFallbackLocal={
          props.obtenerAgentes === undefined && props.obtenerColas === undefined
        }
      />
    </QueryClientProvider>
  );
};
