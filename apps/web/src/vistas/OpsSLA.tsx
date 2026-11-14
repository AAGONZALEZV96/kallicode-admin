/**
 * OpsSLA.tsx — Pantalla de Cumplimiento de Niveles de Servicio y Reloj de Incidencias
 *
 * Conectada mediante TanStack Query a GET /admin/v1/ops/sla y al modal de explicabilidad
 * DetalleRelojSLA (GET /admin/v1/ops/sla/cases/{job_id}).
 */

import React, { useState, useCallback, useContext, useMemo } from "react";
import { QueryClient, QueryClientContext, QueryClientProvider, useQuery } from "@tanstack/react-query";
import { peticionApi } from "../api/clienteApi";
import { useOptionalAuth } from "../estado/auth";
import { useLiveRefresh } from "../hooks/useLiveRefresh";
import { ControlesLiveRefresh } from "../componentes/ControlesLiveRefresh";
import {
  Tabla,
  TablaEncabezado,
  TablaCuerpo,
  TablaFila,
  TablaCelda,
  TablaCeldaEncabezado,
} from "../componentes/Tabla";
import { Badge, BadgeVariante } from "../componentes/Badge";
import { Boton } from "../componentes/Boton";
import { Select } from "../componentes/Select";
import { ContenedorEstado } from "../componentes/ContenedorEstado";
import { DetalleRelojSLA, SlaResultado } from "../componentes/DetalleRelojSLA";

export interface SLACaso {
  job_id: string;
  ticket_id?: string | null;
  ticket_numero?: string | null;
  tenant_id: string;
  razon_social?: string | null;
  plan: string;
  etapa_actual?: string | null;
  objetivo_h: number | null;
  transcurrido_h: number;
  bruto_h?: number;
  pausa_total_h?: number;
  porcentaje_objetivo?: number;
  resultado: SlaResultado;
  enmascarado?: boolean;
}

export interface SlaResumen {
  casos_totales?: number;
  casos_evaluados?: number;
  casos_dentro?: number;
  casos_incumplidos?: number;
  casos_en_riesgo?: number;
  casos_en_curso?: number;
  cumplimiento_pct: number | null;
  tiempo_medio_h?: number | null;
  p95_h?: number | null;
  incumplidos: number;
  en_riesgo: number;
  total_evaluados?: number;
  evaluados?: number;
}

export interface SlaPlanDesglose {
  plan: string;
  objetivo_h: number | null;
  casos: number;
  casos_evaluados?: number;
  cumplimiento_pct: number | null;
  tiempo_medio_h?: number | null;
  p95_h: number | null;
  sin_definicion?: boolean;
}

export interface SlaTenantItem {
  tenant_id: string;
  razon_social?: string | null;
  plan?: string | null;
  objetivo_h?: number | null;
  casos: number;
  evaluados: number;
  incumplidos: number;
  en_riesgo: number;
  cumplimiento_pct?: number | null;
  tiempo_medio_h?: number | null;
  p95_h?: number | null;
}

export interface OpsSLADatos {
  ciclo?: string;
  frescura?: string;
  sin_definicion?: string[];
  resumen: SlaResumen;
  por_plan?: Record<string, SlaPlanDesglose>;
  casos_en_riesgo?: SLACaso[];
  casos?: SLACaso[];
  items?: SlaTenantItem[];
  total?: number;
  page?: number;
  page_size?: number;
  pages?: number;
}

export interface OpsSLAProps {
  obtenerDatos?: () => Promise<OpsSLADatos>;
  datosIniciales?: OpsSLADatos | null;
}

const LIMITE_FRESCURA_MS = 6 * 60 * 60 * 1000; // 6 horas
const ROLES_SLA_PERMITIDOS = new Set(["staff_operaciones", "staff_negocio", "staff_admin"]);

const PLANES_CANONICOS: Array<{
  clave: "starter" | "growth" | "enterprise";
  titulo: string;
  objetivoDefectoH: number;
}> = [
  { clave: "starter", titulo: "Starter", objetivoDefectoH: 72 },
  { clave: "growth", titulo: "Growth", objetivoDefectoH: 24 },
  { clave: "enterprise", titulo: "Enterprise", objetivoDefectoH: 8 },
];

const OPCIONES_PLAN = [
  { valor: "todos", etiqueta: "Todos los planes" },
  { valor: "starter", etiqueta: "Starter (72 h)" },
  { valor: "growth", etiqueta: "Growth (24 h)" },
  { valor: "enterprise", etiqueta: "Enterprise (8 h)" },
];

const OPCIONES_TAMANO_PAGINA = [
  { valor: "5", etiqueta: "5 por página" },
  { valor: "10", etiqueta: "10 por página" },
  { valor: "25", etiqueta: "25 por página" },
  { valor: "50", etiqueta: "50 por página" },
];

function obtenerCicloActual(): string {
  const ahora = new Date();
  const anio = ahora.getFullYear();
  const mes = String(ahora.getMonth() + 1).padStart(2, "0");
  return `${anio}-${mes}`;
}

function generarOpcionesCiclo(cicloActivo: string): Array<{ valor: string; etiqueta: string }> {
  const opciones: Array<{ valor: string; etiqueta: string }> = [];
  const vistos = new Set<string>();
  const base = new Date();
  for (let i = 0; i < 6; i++) {
    const fecha = new Date(base.getFullYear(), base.getMonth() - i, 1);
    const val = `${fecha.getFullYear()}-${String(fecha.getMonth() + 1).padStart(2, "0")}`;
    if (!vistos.has(val)) {
      vistos.add(val);
      opciones.push({ valor: val, etiqueta: i === 0 ? `${val} (Ciclo actual)` : val });
    }
  }
  if (!vistos.has(cicloActivo)) {
    opciones.unshift({ valor: cicloActivo, etiqueta: cicloActivo });
  }
  return opciones;
}

function formatearFrescuraRelativa(fechaIso?: string): { texto: string; obsoleta: boolean } {
  if (!fechaIso) {
    return { texto: "Actualización reciente", obsoleta: false };
  }
  const timestamp = new Date(fechaIso).getTime();
  if (isNaN(timestamp)) {
    return { texto: "Fecha de actualización no disponible", obsoleta: false };
  }
  const diffMs = Math.max(0, Date.now() - timestamp);
  const obsoleta = diffMs > LIMITE_FRESCURA_MS;
  const diffSegundos = Math.floor(diffMs / 1000);

  if (diffSegundos < 60) {
    return { texto: "Actualizado hace unos segundos", obsoleta };
  }
  const diffMinutos = Math.floor(diffSegundos / 60);
  if (diffMinutos < 60) {
    return { texto: `Actualizado hace ${diffMinutos} min`, obsoleta };
  }
  const diffHoras = Math.floor(diffMinutos / 60);
  if (diffHoras < 24) {
    return { texto: `Actualizado hace ${diffHoras} h`, obsoleta };
  }
  const diffDias = Math.floor(diffHoras / 24);
  return { texto: `Actualizado hace ${diffDias} d`, obsoleta };
}

function varianteResultado(resultado: SlaResultado): BadgeVariante {
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

function colorBarraCumplimiento(pct: number | null): string {
  if (pct === null) return "var(--muted, #94a3b8)";
  if (pct >= 95) return "var(--good, #22c55e)";
  if (pct >= 85) return "var(--warn, #f59e0b)";
  return "var(--bad, #ef4444)";
}

function colorBarraCaso(caso: SLACaso): string {
  if (caso.resultado === "incumplido") return "var(--bad, #ef4444)";
  if (caso.resultado === "en_riesgo") return "var(--warn, #f59e0b)";
  if (caso.objetivo_h && caso.objetivo_h > 0 && caso.transcurrido_h / caso.objetivo_h > 0.75) {
    return "var(--warn, #f59e0b)";
  }
  return "var(--good, #22c55e)";
}

const DATOS_DEFECTO: OpsSLADatos = {
  ciclo: obtenerCicloActual(),
  frescura: new Date(Date.now() - 15 * 60 * 1000).toISOString(),
  resumen: {
    casos_totales: 125,
    casos_evaluados: 120,
    cumplimiento_pct: 98.4,
    incumplidos: 2,
    casos_incumplidos: 2,
    en_riesgo: 4,
    casos_en_riesgo: 4,
    total_evaluados: 125,
  },
  por_plan: {
    starter: { plan: "starter", objetivo_h: 72, casos: 45, casos_evaluados: 42, cumplimiento_pct: 97.6, p95_h: 61.2 },
    growth: { plan: "growth", objetivo_h: 24, casos: 50, casos_evaluados: 48, cumplimiento_pct: 97.9, p95_h: 21.5 },
    enterprise: { plan: "enterprise", objetivo_h: 8, casos: 30, casos_evaluados: 30, cumplimiento_pct: 100.0, p95_h: 6.1 },
  },
  casos: [
    {
      job_id: "job_991823",
      ticket_id: "tkt_901",
      ticket_numero: "KC-901",
      tenant_id: "org_••••",
      razon_social: "E••••• Corp.",
      plan: "enterprise",
      objetivo_h: 8.0,
      transcurrido_h: 5.4,
      bruto_h: 6.4,
      pausa_total_h: 1.0,
      resultado: "dentro",
      enmascarado: true,
    },
    {
      job_id: "job_991824",
      ticket_id: "tkt_902",
      ticket_numero: "KC-902",
      tenant_id: "org_••••",
      razon_social: "A••••• S.L.",
      plan: "growth",
      objetivo_h: 24.0,
      transcurrido_h: 19.8,
      bruto_h: 23.8,
      pausa_total_h: 4.0,
      resultado: "en_riesgo",
      enmascarado: true,
    },
    {
      job_id: "job_991810",
      ticket_id: "tkt_903",
      ticket_numero: "KC-903",
      tenant_id: "org_••••",
      razon_social: "I••••• S.L.",
      plan: "starter",
      objetivo_h: 72.0,
      transcurrido_h: 75.2,
      bruto_h: 81.2,
      pausa_total_h: 6.0,
      resultado: "incumplido",
      enmascarado: true,
    },
  ],
  total: 3,
  page: 1,
  page_size: 10,
  pages: 1,
};

interface OpsSLAInternoProps extends OpsSLAProps {
  usarFallbackLocal?: boolean;
}

const OpsSLAInterno: React.FC<OpsSLAInternoProps> = ({
  obtenerDatos,
  datosIniciales,
  usarFallbackLocal = false,
}) => {
  const auth = useOptionalAuth();
  const usuario = auth?.usuario ?? null;

  const [ciclo, setCiclo] = useState<string>(obtenerCicloActual);
  const [planFiltro, setPlanFiltro] = useState<string>("todos");
  const [soloRiesgoOIncumplidos, setSoloRiesgoOIncumplidos] = useState<boolean>(false);
  const [page, setPage] = useState<number>(1);
  const [pageSize, setPageSize] = useState<number>(10);
  const [jobSeleccionado, setJobSeleccionado] = useState<string | null>(null);

  const rolNoAutorizado = Boolean(usuario) && !ROLES_SLA_PERMITIDOS.has(usuario?.role ?? "");

  const consultarSla = useCallback(async (): Promise<OpsSLADatos> => {
    if (obtenerDatos) {
      return obtenerDatos();
    }
    const params: Record<string, string | number | boolean> = {
      ciclo,
      page,
      page_size: pageSize,
    };
    if (planFiltro !== "todos") {
      params.plan = planFiltro;
    }
    if (soloRiesgoOIncumplidos) {
      params.solo_incumplidos = true;
    }
    return peticionApi<OpsSLADatos>("/admin/v1/ops/sla", { params });
  }, [obtenerDatos, ciclo, planFiltro, soloRiesgoOIncumplidos, page, pageSize]);

  const {
    data,
    isLoading,
    isFetching,
    error,
    refetch,
  } = useQuery<OpsSLADatos>({
    queryKey: ["ops-sla", ciclo, planFiltro, soloRiesgoOIncumplidos, page, pageSize, Boolean(obtenerDatos)],
    queryFn: consultarSla,
    enabled: !rolNoAutorizado && !usarFallbackLocal && datosIniciales === undefined,
    initialData:
      datosIniciales !== undefined
        ? datosIniciales ?? undefined
        : usarFallbackLocal
        ? DATOS_DEFECTO
        : undefined,
    placeholderData: (prev) => prev,
    staleTime: 15_000,
  });

  const liveRefresh = useLiveRefresh({
    intervaloMs: 30_000,
    ejecutarAlInicio: false,
    alRefrescar: async () => {
      if (!rolNoAutorizado) {
        await refetch();
      }
    },
    estaConsultando: isFetching,
    refrescarAlVolverVisible: true,
    pausarEnSegundoPlano: true,
    pausarEnPerdidaFoco: true,
  });

  const opcionesCiclo = useMemo(() => generarOpcionesCiclo(ciclo), [ciclo]);

  if (rolNoAutorizado) {
    return (
      <main
        className="view ops-sla"
        data-testid="ops-sla-rbac-bloqueado"
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
          El rol {usuario?.role} no tiene autorización para consultar el cumplimiento de acuerdos de servicio.
        </p>
      </main>
    );
  }

  const frescuraInfo = data
    ? formatearFrescuraRelativa(data.frescura)
    : { texto: "Sincronizando actualización...", obsoleta: false };
  const resumen = data?.resumen;
  const casosEvaluados =
    resumen?.casos_evaluados ?? resumen?.evaluados ?? resumen?.total_evaluados ?? 0;
  const casosTotales = resumen?.casos_totales ?? resumen?.total_evaluados ?? casosEvaluados;
  const casosEnRiesgoCount = resumen?.casos_en_riesgo ?? resumen?.en_riesgo ?? 0;
  const casosIncumplidosCount = resumen?.casos_incumplidos ?? resumen?.incumplidos ?? 0;
  const muestraInsuficiente = casosEvaluados < 5 || resumen?.cumplimiento_pct === null;

  // Lista unificada de casos: usa data.casos si viene del API/mock, o adapta casos_en_riesgo de B5-02
  const filasCasos: SLACaso[] = useMemo(() => {
    if (!data) return [];
    if (Array.isArray(data.casos) && data.casos.length > 0) {
      return data.casos;
    }
    if (Array.isArray(data.casos_en_riesgo) && data.casos_en_riesgo.length > 0) {
      return data.casos_en_riesgo.map((c) => {
        const bruto = c.bruto_h ?? c.transcurrido_h;
        return {
          ...c,
          pausa_total_h: c.pausa_total_h ?? Math.max(0, Number((bruto - c.transcurrido_h).toFixed(2))),
        };
      });
    }
    return [];
  }, [data]);

  const ticketsIncumplidos = useMemo(
    () =>
      filasCasos
        .filter((c) => c.resultado === "incumplido")
        .map((c) => c.ticket_numero || c.ticket_id || c.job_id),
    [filasCasos]
  );

  const totalRegistros = data?.total ?? filasCasos.length;
  const totalPaginas =
    data?.pages && data.pages > 0
      ? data.pages
      : Math.max(1, Math.ceil(totalRegistros / Math.max(1, pageSize)));

  const haySinDatos =
    Boolean(data) &&
    casosTotales === 0 &&
    filasCasos.length === 0 &&
    (!data?.items || data.items.length === 0);

  return (
    <div
      className="view ops-sla"
      aria-live="polite"
      style={{ display: "flex", flexDirection: "column", gap: "20px" }}
    >
      {/* Cabecera, indicador de frescura y refresco en vivo */}
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "flex-start",
          flexWrap: "wrap",
          gap: "12px",
        }}
      >
        <div>
          <h1 style={{ fontSize: "1.25rem", fontWeight: 700, margin: 0 }}>
            Cumplimiento de SLA e Incidentes de Servicio
          </h1>
          <p style={{ fontSize: "0.8125rem", color: "var(--muted)", margin: "4px 0 0 0" }}>
            Observabilidad operativa de acuerdos de nivel de servicio, pausas justificadas y reloj por caso.
          </p>
        </div>

        <div style={{ display: "flex", alignItems: "center", gap: "10px", flexWrap: "wrap" }}>
          <div
            data-testid="indicador-frescura-sla"
            style={{
              display: "flex",
              alignItems: "center",
              gap: "8px",
              padding: "6px 10px",
              borderRadius: "6px",
              border: `1px solid ${
                frescuraInfo.obsoleta ? "var(--warn, #f59e0b)" : "var(--border, #334155)"
              }`,
              backgroundColor: frescuraInfo.obsoleta
                ? "rgba(245, 158, 11, 0.12)"
                : "var(--surface2, #1e293b)",
              fontSize: "12px",
            }}
          >
            <Badge variante={frescuraInfo.obsoleta ? "warn" : "good"} punto>
              {frescuraInfo.obsoleta ? "Datos desactualizados (> 6 h)" : "Frescura operativa"}
            </Badge>
            <span style={{ color: frescuraInfo.obsoleta ? "var(--warn, #f59e0b)" : "var(--muted)" }}>
              {frescuraInfo.texto}
            </span>
          </div>

          <ControlesLiveRefresh hook={liveRefresh} />
        </div>
      </div>

      {/* Barra de filtros dinámicos */}
      <section
        aria-label="Filtros de cumplimiento SLA"
        className="card"
        style={{
          display: "flex",
          flexWrap: "wrap",
          gap: "14px",
          alignItems: "flex-end",
          justifyContent: "space-between",
        }}
      >
        <div style={{ display: "flex", flexWrap: "wrap", gap: "14px", alignItems: "flex-end" }}>
          <div style={{ minWidth: "180px" }}>
            <Select
              id="filtro-ciclo-sla"
              etiqueta="Ciclo comercial (AAAA-MM)"
              value={ciclo}
              onChange={(e) => {
                setCiclo(e.target.value);
                setPage(1);
              }}
              opciones={opcionesCiclo}
            />
          </div>

          <div style={{ minWidth: "190px" }}>
            <Select
              id="filtro-plan-sla"
              etiqueta="Plan comercial"
              value={planFiltro}
              onChange={(e) => {
                setPlanFiltro(e.target.value);
                setPage(1);
              }}
              opciones={OPCIONES_PLAN}
            />
          </div>

          <label
            htmlFor="filtro-solo-riesgo-sla"
            style={{
              display: "flex",
              alignItems: "center",
              gap: "8px",
              padding: "8px 10px",
              borderRadius: "6px",
              border: "1px solid var(--border, #334155)",
              backgroundColor: "var(--surface2, #1e293b)",
              fontSize: "13px",
              cursor: "pointer",
            }}
          >
            <input
              id="filtro-solo-riesgo-sla"
              type="checkbox"
              checked={soloRiesgoOIncumplidos}
              onChange={(e) => {
                setSoloRiesgoOIncumplidos(e.target.checked);
                setPage(1);
              }}
            />
            <span>Solo casos en riesgo o incumplidos</span>
          </label>
        </div>

        {(planFiltro !== "todos" || soloRiesgoOIncumplidos) && (
          <Boton
            variante="ghost"
            tamano="sm"
            onClick={() => {
              setPlanFiltro("todos");
              setSoloRiesgoOIncumplidos(false);
              setPage(1);
            }}
          >
            Restablecer filtros
          </Boton>
        )}
      </section>

      {/* Orquestación de estados (Carga, Error con X-Trace-Id, Vacío y Contenido) */}
      <ContenedorEstado
        cargando={isLoading && !data}
        error={error}
        vacio={haySinDatos}
        tipoCarga="tabla"
        filasCarga={5}
        columnasCarga={9}
        mensajeCarga="Cargando métricas y casos de cumplimiento SLA..."
        onReintentar={() => void refetch()}
        tituloError="Error al cargar el cumplimiento de acuerdos de servicio"
        tituloVacio="Sin casos de SLA para los filtros seleccionados"
        descripcionVacio="No se registran ejecuciones ni incidencias de nivel de servicio en el ciclo o plan elegido."
        alAccionarVacio={() => {
          setPlanFiltro("todos");
          setSoloRiesgoOIncumplidos(false);
          setCiclo(obtenerCicloActual());
          setPage(1);
        }}
        textoAccionVacio="Ver ciclo actual completo"
        dataTestIdCarga="ops-sla-loading"
        dataTestIdError="ops-sla-error"
        dataTestIdTrace="ops-sla-trace-id"
      >
        {data && (
          <div style={{ display: "flex", flexDirection: "column", gap: "20px" }}>
            {/* Tarjetas KPI de cabecera */}
            <section
              aria-label="Resumen ejecutivo de SLA"
              style={{
                display: "grid",
                gridTemplateColumns: "repeat(auto-fit, minmax(210px, 1fr))",
                gap: "14px",
              }}
            >
              <div className="card" data-testid="kpi-cumplimiento-global">
                <div style={{ fontSize: "12px", color: "var(--muted)" }}>Cumplimiento Global</div>
                <div
                  style={{
                    fontSize: "26px",
                    fontWeight: 700,
                    color: muestraInsuficiente
                      ? "var(--muted)"
                      : colorBarraCumplimiento(resumen?.cumplimiento_pct ?? null),
                  }}
                >
                  {muestraInsuficiente || resumen?.cumplimiento_pct == null
                    ? "N/A"
                    : `${resumen.cumplimiento_pct.toFixed(1)}%`}
                </div>
                <div style={{ fontSize: "11px", color: "var(--muted)", marginTop: "4px" }}>
                  {muestraInsuficiente
                    ? "Muestra insuficiente (mínimo 5 casos evaluados)"
                    : `${resumen?.casos_dentro ?? 0} dentro de objetivo sobre ${casosEvaluados} evaluados`}
                </div>
              </div>

              <div
                className="card"
                data-testid="kpi-casos-en-riesgo"
                style={{
                  borderColor:
                    casosEnRiesgoCount > 0 ? "var(--warn, #f59e0b)" : "var(--border, #334155)",
                  backgroundColor:
                    casosEnRiesgoCount > 0 ? "rgba(245, 158, 11, 0.08)" : undefined,
                }}
              >
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                  <span style={{ fontSize: "12px", color: "var(--muted)" }}>Casos en Riesgo</span>
                  {casosEnRiesgoCount > 0 && <Badge variante="warn">Alerta &gt; 75%</Badge>}
                </div>
                <div style={{ fontSize: "26px", fontWeight: 700, color: "var(--warn, #f59e0b)" }}>
                  {casosEnRiesgoCount}
                </div>
                <div style={{ fontSize: "11px", color: "var(--muted)", marginTop: "4px" }}>
                  Ejecuciones activas que superan el 75% del objetivo
                </div>
              </div>

              <div
                className="card"
                data-testid="kpi-casos-incumplidos"
                style={{
                  borderColor:
                    casosIncumplidosCount > 0 ? "var(--bad, #ef4444)" : "var(--border, #334155)",
                }}
              >
                <div style={{ fontSize: "12px", color: "var(--muted)" }}>Casos Incumplidos</div>
                <div style={{ fontSize: "26px", fontWeight: 700, color: "var(--bad, #ef4444)" }}>
                  {casosIncumplidosCount}
                </div>
                <div style={{ fontSize: "11px", color: "var(--muted)", marginTop: "4px" }}>
                  {ticketsIncumplidos.length > 0
                    ? `Tickets: ${ticketsIncumplidos.join(", ")}`
                    : "Sin tickets incumplidos en la vista actual"}
                </div>
              </div>

              <div className="card" data-testid="kpi-total-evaluados">
                <div style={{ fontSize: "12px", color: "var(--muted)" }}>Total Evaluados</div>
                <div style={{ fontSize: "26px", fontWeight: 700, color: "var(--text)" }}>
                  {casosEvaluados}
                </div>
                <div style={{ fontSize: "11px", color: "var(--muted)", marginTop: "4px" }}>
                  Volumen total del ciclo: {casosTotales} casos
                </div>
              </div>
            </section>

            {/* Panel superior: Desglose por plan comercial */}
            <section aria-label="Desglose de cumplimiento por plan comercial">
              <h2 style={{ fontSize: "14px", fontWeight: 650, margin: "0 0 10px 0" }}>
                Desglose por Plan Comercial
              </h2>
              <div
                style={{
                  display: "grid",
                  gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))",
                  gap: "14px",
                }}
              >
                {PLANES_CANONICOS.map(({ clave, titulo, objetivoDefectoH }) => {
                  const info = data.por_plan?.[clave];
                  const objetivo = info?.objetivo_h ?? objetivoDefectoH;
                  const pct = info?.cumplimiento_pct ?? null;
                  const p95 = info?.p95_h ?? null;
                  const casosPlan = info?.casos ?? 0;
                  const colorProgreso = colorBarraCumplimiento(pct);
                  const anchoProgreso = pct !== null ? Math.min(100, Math.max(0, pct)) : 0;

                  return (
                    <div
                      key={clave}
                      className="card"
                      data-testid={`plan-sla-${clave}`}
                      style={{ display: "flex", flexDirection: "column", gap: "8px" }}
                    >
                      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                        <strong>
                          {titulo} ({objetivo} horas)
                        </strong>
                        <Badge variante="neutro">{casosPlan} casos</Badge>
                      </div>

                      <div style={{ display: "flex", justifyContent: "space-between", fontSize: "13px" }}>
                        <span>
                          Cumplimiento:{" "}
                          <strong style={{ color: colorProgreso }}>
                            {pct !== null ? `${pct.toFixed(1)}%` : "N/A"}
                          </strong>
                        </span>
                        <span className="mono" style={{ color: "var(--muted)" }}>
                          p95: {p95 !== null ? `${p95.toFixed(1)} h` : "—"}
                        </span>
                      </div>

                      <div
                        role="progressbar"
                        aria-label={`Cumplimiento plan ${titulo}`}
                        aria-valuemin={0}
                        aria-valuemax={100}
                        aria-valuenow={pct ?? 0}
                        style={{
                          height: "8px",
                          borderRadius: "999px",
                          backgroundColor: "var(--surface2, #334155)",
                          overflow: "hidden",
                        }}
                      >
                        <div
                          style={{
                            width: `${anchoProgreso}%`,
                            height: "100%",
                            backgroundColor: colorProgreso,
                            transition: "width 0.25s ease",
                          }}
                        />
                      </div>
                    </div>
                  );
                })}
              </div>
            </section>

            {/* Tabla densa de casos y seguimiento de reloj */}
            <section className="card" aria-label="Tabla de casos y reloj SLA">
              <div
                style={{
                  display: "flex",
                  justifyContent: "space-between",
                  alignItems: "center",
                  flexWrap: "wrap",
                  gap: "10px",
                  marginBottom: "12px",
                }}
              >
                <h2 style={{ fontSize: "14px", fontWeight: 650, margin: 0 }}>
                  Seguimiento de Reloj por Caso ({totalRegistros})
                </h2>
                <span style={{ fontSize: "12px", color: "var(--muted)" }}>
                  Selecciona un Job ID para inspeccionar el desglose cronológico y las pausas justificadas.
                </span>
              </div>

              {filasCasos.length === 0 ? (
                <div style={{ padding: "24px", textAlign: "center", color: "var(--muted)", fontSize: "13px" }}>
                  No hay casos individuales que coincidan con el filtro aplicado.
                </div>
              ) : (
                <Tabla
                  densidad="alta"
                  aria-label="Casos de cumplimiento SLA y seguimiento del reloj"
                >
                  <TablaEncabezado>
                    <TablaFila>
                      <TablaCeldaEncabezado scope="col">Job ID</TablaCeldaEncabezado>
                      <TablaCeldaEncabezado scope="col">Ticket</TablaCeldaEncabezado>
                      <TablaCeldaEncabezado scope="col">Cliente / Tenant</TablaCeldaEncabezado>
                      <TablaCeldaEncabezado scope="col">Plan</TablaCeldaEncabezado>
                      <TablaCeldaEncabezado scope="col" numerico>
                        Objetivo SLA (h)
                      </TablaCeldaEncabezado>
                      <TablaCeldaEncabezado scope="col" numerico>
                        Transcurrido (h)
                      </TablaCeldaEncabezado>
                      <TablaCeldaEncabezado scope="col" numerico>
                        Bruto (h)
                      </TablaCeldaEncabezado>
                      <TablaCeldaEncabezado scope="col" numerico>
                        Pausas (h)
                      </TablaCeldaEncabezado>
                      <TablaCeldaEncabezado scope="col">Resultado</TablaCeldaEncabezado>
                    </TablaFila>
                  </TablaEncabezado>
                  <TablaCuerpo>
                    {filasCasos.map((c) => {
                      const bruto = c.bruto_h ?? c.transcurrido_h;
                      const pausas =
                        c.pausa_total_h ?? Math.max(0, Number((bruto - c.transcurrido_h).toFixed(2)));
                      const estaEnmascarado =
                        c.enmascarado ?? (c.razon_social?.includes("•") || c.tenant_id.includes("•"));
                      const ratioPct =
                        c.objetivo_h && c.objetivo_h > 0
                          ? Math.min(100, (c.transcurrido_h / c.objetivo_h) * 100)
                          : 0;

                      return (
                        <TablaFila key={c.job_id} data-testid={`fila-sla-${c.job_id}`}>
                          <TablaCelda>
                            <button
                              type="button"
                              onClick={() => setJobSeleccionado(c.job_id)}
                              className="mono"
                              style={{
                                background: "none",
                                border: "none",
                                padding: 0,
                                color: "var(--accent, #38bdf8)",
                                textDecoration: "underline",
                                cursor: "pointer",
                                fontWeight: 600,
                              }}
                              aria-label={`Ver desglose del reloj SLA para ${c.job_id}`}
                            >
                              {c.job_id}
                            </button>
                          </TablaCelda>
                          <TablaCelda>
                            <span className="mono">{c.ticket_numero || c.ticket_id || "—"}</span>
                          </TablaCelda>
                          <TablaCelda>
                            <div style={{ display: "flex", alignItems: "center", gap: "6px", flexWrap: "wrap" }}>
                              <span>{c.razon_social || c.tenant_id}</span>
                              <Badge variante={estaEnmascarado ? "masked" : "good"}>
                                {estaEnmascarado ? "ENMASCARADO" : "EN CLARO"}
                              </Badge>
                            </div>
                          </TablaCelda>
                          <TablaCelda>
                            <span style={{ textTransform: "capitalize", fontWeight: 500 }}>{c.plan}</span>
                          </TablaCelda>
                          <TablaCelda numerico>
                            {c.objetivo_h != null ? `${c.objetivo_h.toFixed(1)} h` : "—"}
                          </TablaCelda>
                          <TablaCelda numerico>
                            <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-end", gap: "4px" }}>
                              <span>{c.transcurrido_h.toFixed(1)} h</span>
                              <div
                                aria-hidden="true"
                                style={{
                                  width: "72px",
                                  height: "5px",
                                  borderRadius: "999px",
                                  backgroundColor: "var(--surface2, #334155)",
                                  overflow: "hidden",
                                }}
                              >
                                <div
                                  style={{
                                    width: `${ratioPct}%`,
                                    height: "100%",
                                    backgroundColor: colorBarraCaso(c),
                                  }}
                                />
                              </div>
                            </div>
                          </TablaCelda>
                          <TablaCelda numerico>{bruto.toFixed(1)} h</TablaCelda>
                          <TablaCelda numerico>{pausas.toFixed(1)} h</TablaCelda>
                          <TablaCelda>
                            <Badge variante={varianteResultado(c.resultado)} punto>
                              {c.resultado.toUpperCase()}
                            </Badge>
                          </TablaCelda>
                        </TablaFila>
                      );
                    })}
                  </TablaCuerpo>
                </Tabla>
              )}

              {/* Paginación transversal */}
              <div
                data-testid="paginacion-ops-sla"
                style={{
                  display: "flex",
                  justifyContent: "space-between",
                  alignItems: "center",
                  flexWrap: "wrap",
                  gap: "12px",
                  marginTop: "14px",
                  paddingTop: "12px",
                  borderTop: "1px solid var(--border, #334155)",
                  fontSize: "13px",
                }}
              >
                <div style={{ color: "var(--muted)" }}>
                  Mostrando página <strong>{page}</strong> de <strong>{totalPaginas}</strong> ·{" "}
                  <span>Total: {totalRegistros} casos</span>
                </div>

                <div style={{ display: "flex", alignItems: "center", gap: "10px", flexWrap: "wrap" }}>
                  <div style={{ width: "140px" }}>
                    <Select
                      id="paginacion-tamano-sla"
                      aria-label="Registros por página"
                      value={String(pageSize)}
                      onChange={(e) => {
                        setPageSize(Number(e.target.value));
                        setPage(1);
                      }}
                      opciones={OPCIONES_TAMANO_PAGINA}
                    />
                  </div>
                  <Boton
                    variante="secondary"
                    tamano="sm"
                    disabled={page <= 1}
                    onClick={() => setPage((p) => Math.max(1, p - 1))}
                  >
                    Anterior
                  </Boton>
                  <Boton
                    variante="secondary"
                    tamano="sm"
                    disabled={page >= totalPaginas}
                    onClick={() => setPage((p) => Math.min(totalPaginas, p + 1))}
                  >
                    Siguiente
                  </Boton>
                </div>
              </div>
            </section>
          </div>
        )}
      </ContenedorEstado>

      {/* Modal interactivo de explicabilidad del reloj SLA */}
      <DetalleRelojSLA
        jobId={jobSeleccionado}
        abierto={Boolean(jobSeleccionado)}
        alCerrar={() => setJobSeleccionado(null)}
      />
    </div>
  );
};

export const OpsSLA: React.FC<OpsSLAProps> = (props) => {
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
    return <OpsSLAInterno {...props} />;
  }

  return (
    <QueryClientProvider client={fallbackClient}>
      <OpsSLAInterno {...props} usarFallbackLocal={props.obtenerDatos === undefined} />
    </QueryClientProvider>
  );
};
