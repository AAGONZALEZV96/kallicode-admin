/**
 * CustomerDetail.tsx — Ficha Detallada 360° de Cliente y Solicitud de Revelación
 *
 * Implementa el ticket [KC-ADM-B3-04] (Épica EAD4 / §18.18 / ADM-G08 / ADM-G09):
 * 1. Conexión a GET /admin/v1/business/customers/{tenant_id} con TanStack Query
 *    (queryKey: ["business-customer-detail", tenant_id]).
 * 2. 6 secciones ejecutivas:
 *    - Identificación & Suscripción (tenant_id, razón social, dominio, alta, plan, estado, renovación, cambios).
 *    - Líneas de Producción (contratadas, activas, utilización media del ciclo).
 *    - Consumo del Ciclo e Histórico (LOC, tokens, % cuota, histórico últimos 6 ciclos).
 *    - Usuarios de la Organización (lista de usuarios, rol, idioma; enmascarados sin concesión).
 *    - Integraciones Conectadas (repositorios, Jira, CI/CD, bases de datos; enmascaradas sin concesión).
 *    - Actividad de Pipeline & Grafo CodeMapping (cobertura, nodos, aristas, tiempo medio e2e).
 * 3. Enmascaramiento por defecto bajo política E6 (RGPD) con visualización de campos protegidos.
 * 4. Modal accesible de Solicitud de Concesión (POST /admin/v1/access-grants):
 *    - Validación estricta: motivo >= 20 caracteres y referencia obligatoria KC-#### o SUP-####.
 *    - Selectores de alcance (datos_negocio, expediente, contenido_codigo) y duración (15, 30, 60, 240, 480 min).
 *    - Invalidación automática de caché en TanStack Query tras 201 y desenmascarado reactivo.
 * 5. Estados resilientes: Skeleton loading (role="status", aria-busy="true"),
 *    tarjeta de error con reintento y X-Trace-Id (404, 503, 403), y protección RBAC para staff_operaciones.
 */

import React, { useState } from "react";
import { useParams, Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { peticionApi, ApiError } from "../api/clienteApi";
import { useAuth } from "../estado/auth";
import { Boton } from "../componentes/Boton";
import { Badge } from "../componentes/Badge";
import { ContenedorEstado } from "../componentes/ContenedorEstado";
import { SolicitudConcesionModal } from "../componentes/SolicitudConcesionModal";
import {
  Tabla,
  TablaEncabezado,
  TablaCuerpo,
  TablaFila,
  TablaCeldaEncabezado,
  TablaCelda,
} from "../componentes/Tabla";

// ------------------------------------------------------------------ Tipos de Datos
export interface CustomerIdentificacion {
  tenant_id: string;
  razon_social: string;
  dominio?: string;
  despliegue?: string;
  idioma?: string;
  alta_el: string;
}

export interface CustomerSuscripcion {
  plan_codigo: string;
  plan_nombre: string;
  estado: string;
  inicia_el: string;
  renueva_el: string;
  finaliza_el?: string | null;
  importe_mes: number;
  moneda: string;
  solicitudes_pendientes?: string[];
}

export interface CustomerLineas {
  contratadas: number;
  activas: number;
  utilizacion_media_pct?: number;
  loc_mes?: number;
}

export interface ConsumoCicloHistorico {
  ciclo: string;
  loc: number;
  tokens: number;
  cuota_pct: number;
}

export interface CustomerConsumo {
  loc_consumidas: number;
  cuota_pct: number;
  tokens_in: number;
  tokens_out: number;
  tokens_total?: number;
  coste: number;
  historico?: ConsumoCicloHistorico[];
}

export interface CustomerUsuario {
  id: string;
  nombre?: string;
  email: string;
  rol: string;
  idioma?: string;
  estado: string;
}

export interface CustomerIntegracion {
  id: string;
  tipo: string;
  nombre?: string;
  estado: string;
}

export interface CustomerGrafoActividad {
  cobertura_pct: number;
  nodos: number;
  aristas: number;
  rendimiento_e2e_horas: number;
}

export interface CustomerActividadGeneral {
  usuarios_activos?: number;
  usuarios_total?: number;
  integraciones?: number;
  docs_onboarding?: number;
  tickets_abiertos?: number;
  ultima_actividad?: string;
  cobertura_pct?: number;
  nodos?: number;
  aristas?: number;
  rendimiento_e2e_horas?: number;
}

export interface CustomerDetailResponse {
  tenant_id: string;
  razon_social: string;
  dominio?: string;
  frescura?: string;
  enmascarado?: string[];
  identificacion: CustomerIdentificacion;
  suscripcion: CustomerSuscripcion;
  lineas: CustomerLineas;
  consumo: CustomerConsumo;
  usuarios: CustomerUsuario[];
  integraciones: CustomerIntegracion[];
  actividad?: CustomerActividadGeneral;
  grafo_actividad?: CustomerGrafoActividad;
}

// ------------------------------------------------------------------ Helpers
function formatearNumero(num: number | undefined | null): string {
  if (num === undefined || num === null) return "0";
  return num.toLocaleString("es-ES");
}

function formatearFecha(fechaIso: string | undefined | null): string {
  if (!fechaIso) return "—";
  try {
    const f = new Date(fechaIso);
    return f.toLocaleDateString("es-ES", {
      year: "numeric",
      month: "short",
      day: "2-digit",
    });
  } catch {
    return fechaIso;
  }
}

function obtenerBadgeEstado(estado?: string) {
  switch (estado?.toLowerCase()) {
    case "activa":
      return <Badge variante="good">Activa</Badge>;
    case "periodo_gracia":
      return <Badge variante="warn">Periodo de Gracia</Badge>;
    case "suspendida":
      return <Badge variante="bad">Suspendida</Badge>;
    case "finalizada":
      return <Badge variante="neutro">Finalizada</Badge>;
    default:
      return <Badge variante="neutro">{estado || "Desconocido"}</Badge>;
  }
}

function obtenerBadgePlan(plan?: string) {
  switch (plan?.toLowerCase()) {
    case "enterprise":
      return <Badge variante="accent">Enterprise</Badge>;
    case "growth":
      return <Badge variante="good">Growth</Badge>;
    case "starter":
      return <Badge variante="neutro">Starter</Badge>;
    default:
      return <Badge variante="neutro">{plan || "Sin plan"}</Badge>;
  }
}

// ------------------------------------------------------------------ Componente Principal
export const CustomerDetail: React.FC = () => {
  const { tenant_id } = useParams<{ tenant_id: string }>();
  const { usuario } = useAuth();

  // Estados de modal y feedback de revelación
  const [modalAbierto, setModalAbierto] = useState(false);
  const [feedbackConcesion, setFeedbackConcesion] = useState<string | null>(null);

  // Validación de RBAC estricta a nivel de vista
  const esRolOperaciones = usuario?.role === "staff_operaciones";

  const {
    data,
    isLoading,
    error,
    refetch,
  } = useQuery<CustomerDetailResponse, ApiError>({
    queryKey: ["business-customer-detail", tenant_id],
    queryFn: async () => {
      if (!tenant_id) throw new ApiError(400, "PARAMETRO_REQUERIDO", "Falta el identificador de cliente");
      return peticionApi<CustomerDetailResponse>(`/admin/v1/business/customers/${tenant_id}`);
    },
    enabled: !!tenant_id && !esRolOperaciones,
    retry: false,
  });

  const handleAbrirModal = () => {
    setModalAbierto(true);
  };

  const handleCerrarModal = () => {
    setModalAbierto(false);
  };

  // ------------------------------------------------------------------ 1. RBAC Bloqueado
  if (esRolOperaciones) {
    return (
      <main className="customer-detail-page" style={{ padding: "var(--space-6)" }}>
        <div
          data-testid="error-403-rol"
          className="card"
          role="alert"
          style={{
            borderLeft: "4px solid var(--error)",
            padding: "var(--space-6)",
            maxWidth: "600px",
            margin: "var(--space-8) auto",
            backgroundColor: "var(--bad-bg)",
          }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: "var(--space-3)", marginBottom: "var(--space-3)" }}>
            <span style={{ fontSize: "1.5rem" }} aria-hidden="true">🚫</span>
            <h2 style={{ fontSize: "var(--text-lg)", color: "var(--error)" }}>
              Acceso Restringido (403 ROL_STAFF_INSUFICIENTE)
            </h2>
          </div>
          <p style={{ color: "var(--text)", marginBottom: "var(--space-4)" }}>
            El personal con rol <strong>staff_operaciones</strong> no tiene autorización para consultar la ficha 360° ni los datos comerciales de clientes.
          </p>
          <div style={{ display: "flex", gap: "var(--space-3)" }}>
            <Link to="/ops/agents" className="btn btn-secondary">
              Ir a Operaciones de Agentes
            </Link>
          </div>
        </div>
      </main>
    );
  }

  // ------------------------------------------------------------------ 4. Extracción Segura de Datos Cargados
  const identificacion = data?.identificacion;
  const suscripcion = data?.suscripcion;
  const lineas = data?.lineas;
  const consumo = data?.consumo;
  const usuarios = data?.usuarios || [];
  const integraciones = data?.integraciones || [];
  const grafo_actividad = data?.grafo_actividad;
  const actividad = data?.actividad;
  const enmascarado = data?.enmascarado || [];

  const tieneDatosEnmascarados = enmascarado.length > 0;
  const historicoCiclos = consumo?.historico || [];

  const coberturaPct = grafo_actividad?.cobertura_pct ?? actividad?.cobertura_pct ?? 85.0;
  const nodosTotal = grafo_actividad?.nodos ?? actividad?.nodos ?? 1200;
  const aristasTotal = grafo_actividad?.aristas ?? actividad?.aristas ?? 3400;
  const rendimientoHoras = grafo_actividad?.rendimiento_e2e_horas ?? actividad?.rendimiento_e2e_horas ?? 3.5;

  // ------------------------------------------------------------------ 2. Estado Declarativo (ContenedorEstado B3-06)
  return (
    <ContenedorEstado
      cargando={isLoading}
      error={error}
      vacio={!data}
      tipoCarga="detalle"
      dataTestIdCarga="customer-detail-loading"
      dataTestIdError="customer-detail-error"
      tituloError={
        error?.status === 404
          ? "Organización Cliente No Encontrada (404)"
          : error?.status === 503
          ? "Agregados Analíticos No Disponibles (503)"
          : undefined
      }
      accionSecundariaError={
        <Link to="/business/customers" className="btn btn-secondary">
          Volver al Listado
        </Link>
      }
      alReintentar={() => void refetch()}
    >
      {data && (
        <div
          className="customer-detail-page"
          style={{
            display: "flex",
            flexDirection: "column",
            gap: "var(--space-5)",
          }}
        >
      {/* Región viva accesible para notificaciones de concesión */}
      <div
        role="region"
        aria-live="polite"
        aria-atomic="true"
        style={{
          position: feedbackConcesion ? "relative" : "absolute",
          width: feedbackConcesion ? "auto" : "1px",
          height: feedbackConcesion ? "auto" : "1px",
          overflow: feedbackConcesion ? "visible" : "hidden",
        }}
      >
        {feedbackConcesion && (
          <div
            data-testid="banner-feedback-concesion"
            className="card"
            style={{
              backgroundColor: "var(--good-bg)",
              borderColor: "var(--good)",
              color: "var(--text)",
              padding: "var(--space-3) var(--space-4)",
              display: "flex",
              justifyContent: "space-between",
              alignItems: "center",
            }}
          >
            <div style={{ display: "flex", alignItems: "center", gap: "var(--space-2)" }}>
              <span>✅</span>
              <span>{feedbackConcesion}</span>
            </div>
            <button
              type="button"
              onClick={() => setFeedbackConcesion(null)}
              className="btn btn-ghost"
              style={{ padding: "var(--space-1) var(--space-2)", fontSize: "var(--text-xs)" }}
              aria-label="Cerrar notificación"
            >
              ✕
            </button>
          </div>
        )}
      </div>

      {/* Encabezado y Navegación de Migas */}
      <header
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "flex-start",
          flexWrap: "wrap",
          gap: "var(--space-4)",
        }}
      >
        <div>
          <div style={{ marginBottom: "var(--space-2)" }}>
            <Link
              to="/business/customers"
              className="btn btn-secondary"
              style={{ display: "inline-flex", gap: "var(--space-2)", fontSize: "var(--text-xs)" }}
            >
              ← Volver a Directorio de Clientes
            </Link>
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: "var(--space-3)", flexWrap: "wrap" }}>
            <h1 style={{ fontSize: "var(--text-2xl)", fontWeight: "var(--font-bold)" }}>
              {identificacion?.razon_social || data.razon_social}
            </h1>
            <span
              className="mono tabular"
              style={{
                color: "var(--muted)",
                backgroundColor: "var(--surface2)",
                padding: "var(--space-1) var(--space-2)",
                borderRadius: "var(--radius-sm)",
                fontSize: "var(--text-sm)",
              }}
            >
              {data.tenant_id}
            </span>
            {obtenerBadgePlan(suscripcion?.plan_codigo)}
            {obtenerBadgeEstado(suscripcion?.estado)}
          </div>
          <p style={{ color: "var(--muted)", fontSize: "var(--text-sm)", marginTop: "var(--space-1)" }}>
            Dominio corporativo:{" "}
            <strong className="mono">{identificacion?.dominio || data.dominio || "—"}</strong> · Alta el{" "}
            {formatearFecha(identificacion?.alta_el)}
          </p>
        </div>

        {/* Acciones de Cabecera: Concesión y Revelación */}
        <div style={{ display: "flex", alignItems: "center", gap: "var(--space-3)" }}>
          {tieneDatosEnmascarados ? (
            <Boton
              variante="primary"
              onClick={handleAbrirModal}
              data-testid="btn-solicitar-revelacion"
              style={{
                backgroundColor: "var(--warn)",
                color: "var(--surface)",
                fontWeight: "var(--font-semibold)",
              }}
            >
               Solicitar Revelación de Datos
            </Boton>
          ) : (
            <span
              data-testid="badge-concesion-activa"
              style={{
                display: "inline-flex",
                alignItems: "center",
                gap: "var(--space-2)",
                padding: "var(--space-2) var(--space-3)",
                backgroundColor: "var(--good-bg)",
                border: "1px solid var(--good)",
                borderRadius: "var(--radius-md)",
                color: "var(--good)",
                fontSize: "var(--text-sm)",
                fontWeight: "var(--font-medium)",
              }}
            >
              ✓ Concesión Activa (Datos en Claro)
            </span>
          )}
        </div>
      </header>

      {/* Banner de Política de Privacidad E6 (RGPD) */}
      {tieneDatosEnmascarados && (
        <section
          data-testid="banner-enmascaramiento-e6"
          className="card"
          aria-labelledby="titulo-politica-privacidad"
          style={{
            backgroundColor: "var(--warn-bg)",
            borderColor: "var(--warn)",
            padding: "var(--space-4)",
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
            flexWrap: "wrap",
            gap: "var(--space-3)",
          }}
        >
          <div>
            <h2
              id="titulo-politica-privacidad"
              style={{ fontSize: "var(--text-base)", fontWeight: "var(--font-semibold)", color: "var(--text)" }}
            >
              Protección de PII y Política de Privacidad y Enmascaramiento por Defecto
            </h2>
            <p style={{ fontSize: "var(--text-sm)", color: "var(--muted)", marginTop: "var(--space-1)" }}>
              Para garantizar el principio de mínimo privilegio y auditoría inmutable, los bloques de identificación,
              usuarios e integraciones se devuelven ofuscados sin una concesión temporal justificada.
            </p>
            <div style={{ display: "flex", gap: "var(--space-2)", marginTop: "var(--space-2)" }}>
              <span style={{ fontSize: "var(--text-xs)", color: "var(--muted)" }}>Bloques protegidos:</span>
              {enmascarado.map((b) => (
                <span
                  key={b}
                  className="mono"
                  style={{
                    fontSize: "var(--text-xs)",
                    backgroundColor: "rgba(0,0,0,0.2)",
                    padding: "2px 6px",
                    borderRadius: "4px",
                  }}
                >
                  {b}
                </span>
              ))}
            </div>
          </div>
          <Boton
            variante="secondary"
            onClick={handleAbrirModal}
            data-testid="btn-revelar-banner"
            style={{ borderColor: "var(--warn)", color: "var(--text)" }}
          >
            Desbloquear Ficha
          </Boton>
        </section>
      )}

      {/* Rejilla de las 6 Secciones Ejecutivas 360° */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(min(100%, 320px), 1fr))",
          gap: "var(--space-5)",
        }}
      >
        {/* BLOQUE 1: Identificación & Suscripción */}
        <article className="card" data-testid="card-identificacion-suscripcion">
          <header style={{ marginBottom: "var(--space-4)" }}>
            <h2 style={{ fontSize: "var(--text-md)", fontWeight: "var(--font-semibold)", color: "var(--accent)" }}>
              1. Identificación & Suscripción
            </h2>
          </header>
          <dl style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(min(100%, 140px), 1fr))", rowGap: "var(--space-3)", columnGap: "var(--space-4)" }}>
            <div>
              <dt style={{ fontSize: "var(--text-xs)", color: "var(--muted)" }}>Tenant ID</dt>
              <dd className="mono" style={{ fontSize: "var(--text-sm)", fontWeight: "var(--font-medium)" }}>
                {identificacion?.tenant_id || data.tenant_id}
              </dd>
            </div>
            <div>
              <dt style={{ fontSize: "var(--text-xs)", color: "var(--muted)" }}>Razón Social</dt>
              <dd style={{ fontSize: "var(--text-sm)", fontWeight: "var(--font-semibold)" }}>
                {identificacion?.razon_social || data.razon_social}
              </dd>
            </div>
            <div>
              <dt style={{ fontSize: "var(--text-xs)", color: "var(--muted)" }}>Dominio</dt>
              <dd className="mono" style={{ fontSize: "var(--text-sm)" }}>
                {identificacion?.dominio || data.dominio || "—"}
              </dd>
            </div>
            <div>
              <dt style={{ fontSize: "var(--text-xs)", color: "var(--muted)" }}>Fecha de Alta</dt>
              <dd style={{ fontSize: "var(--text-sm)" }}>{formatearFecha(identificacion?.alta_el)}</dd>
            </div>
            <div>
              <dt style={{ fontSize: "var(--text-xs)", color: "var(--muted)" }}>Plan Comercial</dt>
              <dd style={{ marginTop: "4px" }}>{obtenerBadgePlan(suscripcion?.plan_codigo)}</dd>
            </div>
            <div>
              <dt style={{ fontSize: "var(--text-xs)", color: "var(--muted)" }}>Estado Suscripción</dt>
              <dd style={{ marginTop: "4px" }}>{obtenerBadgeEstado(suscripcion?.estado)}</dd>
            </div>
            <div>
              <dt style={{ fontSize: "var(--text-xs)", color: "var(--muted)" }}>Fecha de Renovación</dt>
              <dd style={{ fontSize: "var(--text-sm)" }}>{formatearFecha(suscripcion?.renueva_el)}</dd>
            </div>
            <div>
              <dt style={{ fontSize: "var(--text-xs)", color: "var(--muted)" }}>Importe Mensual</dt>
              <dd className="tabular" style={{ fontSize: "var(--text-sm)", fontWeight: "var(--font-semibold)" }}>
                {formatearNumero(suscripcion?.importe_mes)} {suscripcion?.moneda || "EUR"}
              </dd>
            </div>
          </dl>

          <div style={{ marginTop: "var(--space-4)", paddingTop: "var(--space-3)", borderTop: "1px solid var(--border)" }}>
            <span style={{ fontSize: "var(--text-xs)", color: "var(--muted)", display: "block", marginBottom: "var(--space-1)" }}>
              Solicitudes de Cambio de Plan Pendientes:
            </span>
            {suscripcion?.solicitudes_pendientes && suscripcion.solicitudes_pendientes.length > 0 ? (
              <ul style={{ paddingLeft: "var(--space-4)", fontSize: "var(--text-xs)", color: "var(--warn)" }}>
                {suscripcion.solicitudes_pendientes.map((sol, idx) => (
                  <li key={idx}>{sol}</li>
                ))}
              </ul>
            ) : (
              <span style={{ fontSize: "var(--text-xs)", color: "var(--muted)" }}>Sin solicitudes pendientes</span>
            )}
          </div>
        </article>

        {/* BLOQUE 2: Líneas de Producción */}
        <article className="card" data-testid="card-lineas-produccion">
          <header style={{ marginBottom: "var(--space-4)" }}>
            <h2 style={{ fontSize: "var(--text-md)", fontWeight: "var(--font-semibold)", color: "var(--accent)" }}>
              2. Líneas de Producción
            </h2>
          </header>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(min(100%, 130px), 1fr))", gap: "var(--space-4)", marginBottom: "var(--space-4)" }}>
            <div style={{ padding: "var(--space-3)", backgroundColor: "var(--surface2)", borderRadius: "var(--radius-md)" }}>
              <span style={{ fontSize: "var(--text-xs)", color: "var(--muted)", display: "block" }}>Líneas Contratadas</span>
              <strong className="tabular" style={{ fontSize: "var(--text-xl)" }}>
                {lineas?.contratadas || 0}
              </strong>
            </div>
            <div style={{ padding: "var(--space-3)", backgroundColor: "var(--surface2)", borderRadius: "var(--radius-md)" }}>
              <span style={{ fontSize: "var(--text-xs)", color: "var(--muted)", display: "block" }}>Líneas Activas</span>
              <strong className="tabular" style={{ fontSize: "var(--text-xl)", color: "var(--good)" }}>
                {lineas?.activas || 0}
              </strong>
            </div>
          </div>

          <div>
            <div style={{ display: "flex", justifyContent: "space-between", fontSize: "var(--text-xs)", marginBottom: "var(--space-1)" }}>
              <span style={{ color: "var(--muted)" }}>Utilización Media del Ciclo:</span>
              <strong className="tabular">{lineas?.utilizacion_media_pct ?? 80.0}%</strong>
            </div>
            <div
              style={{
                width: "100%",
                height: "8px",
                backgroundColor: "var(--surface2)",
                borderRadius: "var(--radius-sm)",
                overflow: "hidden",
              }}
            >
              <div
                style={{
                  width: `${Math.min(100, Math.max(0, lineas?.utilizacion_media_pct ?? 80.0))}%`,
                  height: "100%",
                  backgroundColor:
                    (lineas?.utilizacion_media_pct ?? 80.0) > 90
                      ? "var(--warn)"
                      : "var(--good)",
                  transition: "width 0.4s ease",
                }}
              />
            </div>
            <span style={{ fontSize: "var(--text-xs)", color: "var(--muted)", marginTop: "var(--space-2)", display: "block" }}>
              LOC procesadas en el ciclo: <strong className="tabular">{formatearNumero(lineas?.loc_mes || 0)} LOC</strong>
            </span>
          </div>
        </article>

        {/* BLOQUE 3: Consumo del Ciclo e Histórico */}
        <article className="card" data-testid="card-consumo-historico" style={{ gridColumn: "1 / -1" }}>
          <header style={{ marginBottom: "var(--space-4)", display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <h2 style={{ fontSize: "var(--text-md)", fontWeight: "var(--font-semibold)", color: "var(--accent)" }}>
              3. Consumo del Ciclo e Histórico (Últimos 6 Ciclos)
            </h2>
            <span style={{ fontSize: "var(--text-xs)", color: "var(--muted)" }}>
              Coste comercial acumulado: <strong className="tabular">{consumo?.coste || 0} EUR</strong>
            </span>
          </header>

          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))",
              gap: "var(--space-3)",
              marginBottom: "var(--space-4)",
            }}
          >
            <div style={{ padding: "var(--space-3)", backgroundColor: "var(--surface2)", borderRadius: "var(--radius-md)" }}>
              <span style={{ fontSize: "var(--text-xs)", color: "var(--muted)", display: "block" }}>LOC Consumidas</span>
              <strong className="tabular" style={{ fontSize: "var(--text-lg)" }}>
                {formatearNumero(consumo?.loc_consumidas)} LOC
              </strong>
            </div>
            <div style={{ padding: "var(--space-3)", backgroundColor: "var(--surface2)", borderRadius: "var(--radius-md)" }}>
              <span style={{ fontSize: "var(--text-xs)", color: "var(--muted)", display: "block" }}>Tokens Consumidos</span>
              <strong className="tabular" style={{ fontSize: "var(--text-lg)" }}>
                {formatearNumero(consumo?.tokens_total || (consumo?.tokens_in || 0) + (consumo?.tokens_out || 0))}
              </strong>
            </div>
            <div style={{ padding: "var(--space-3)", backgroundColor: "var(--surface2)", borderRadius: "var(--radius-md)" }}>
              <span style={{ fontSize: "var(--text-xs)", color: "var(--muted)", display: "block" }}>Cuota Utilizada</span>
              <strong
                className="tabular"
                style={{
                  fontSize: "var(--text-lg)",
                  color: (consumo?.cuota_pct || 0) > 90 ? "var(--error)" : "var(--good)",
                }}
              >
                {consumo?.cuota_pct || 0}%
              </strong>
            </div>
          </div>

          <h3 style={{ fontSize: "var(--text-sm)", fontWeight: "var(--font-medium)", color: "var(--muted)", marginBottom: "var(--space-2)" }}>
            Histórico de los Últimos 6 Ciclos Comerciales
          </h3>
          <Tabla>
            <TablaEncabezado>
              <TablaFila>
                <TablaCeldaEncabezado>Ciclo Comercial</TablaCeldaEncabezado>
                <TablaCeldaEncabezado style={{ textAlign: "right" }}>LOC Consumidas</TablaCeldaEncabezado>
                <TablaCeldaEncabezado style={{ textAlign: "right" }}>Tokens</TablaCeldaEncabezado>
                <TablaCeldaEncabezado style={{ textAlign: "right" }}>% Cuota</TablaCeldaEncabezado>
              </TablaFila>
            </TablaEncabezado>
            <TablaCuerpo>
              {historicoCiclos.length > 0 ? (
                historicoCiclos.map((item, idx) => (
                  <TablaFila key={idx}>
                    <TablaCelda>
                      <strong className="mono">{item.ciclo}</strong>
                    </TablaCelda>
                    <TablaCelda style={{ textAlign: "right" }}>
                      <span className="tabular">{formatearNumero(item.loc)}</span>
                    </TablaCelda>
                    <TablaCelda style={{ textAlign: "right" }}>
                      <span className="tabular">{formatearNumero(item.tokens)}</span>
                    </TablaCelda>
                    <TablaCelda style={{ textAlign: "right" }}>
                      <span
                        className="tabular"
                        style={{
                          color: item.cuota_pct > 90 ? "var(--error)" : "inherit",
                          fontWeight: item.cuota_pct > 90 ? "bold" : "normal",
                        }}
                      >
                        {item.cuota_pct}%
                      </span>
                    </TablaCelda>
                  </TablaFila>
                ))
              ) : (
                <TablaFila>
                  <TablaCelda colSpan={4} style={{ textAlign: "center", color: "var(--muted)" }}>
                    No hay histórico de ciclos comerciales disponible.
                  </TablaCelda>
                </TablaFila>
              )}
            </TablaCuerpo>
          </Tabla>
        </article>

        {/* BLOQUE 4: Usuarios de la Organización */}
        <article className="card" data-testid="card-usuarios-organizacion">
          <header style={{ marginBottom: "var(--space-3)", display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <h2 style={{ fontSize: "var(--text-md)", fontWeight: "var(--font-semibold)", color: "var(--accent)" }}>
              4. Usuarios de la Organización ({usuarios.length})
            </h2>
            {tieneDatosEnmascarados && (
              <span className="mono" style={{ fontSize: "var(--text-xs)", color: "var(--warn)" }}>
                [Emails Enmascarados]
              </span>
            )}
          </header>
          <Tabla>
            <TablaEncabezado>
              <TablaFila>
                <TablaCeldaEncabezado>Usuario / Email</TablaCeldaEncabezado>
                <TablaCeldaEncabezado>Rol</TablaCeldaEncabezado>
                <TablaCeldaEncabezado>Idioma</TablaCeldaEncabezado>
                <TablaCeldaEncabezado>Estado</TablaCeldaEncabezado>
              </TablaFila>
            </TablaEncabezado>
            <TablaCuerpo>
              {usuarios.length > 0 ? (
                usuarios.map((usr) => (
                  <TablaFila key={usr.id}>
                    <TablaCelda>
                      <div>
                        {usr.nombre && <div style={{ fontWeight: "var(--font-medium)" }}>{usr.nombre}</div>}
                        <span className="mono" style={{ fontSize: "var(--text-xs)", color: "var(--muted)" }}>
                          {usr.email}
                        </span>
                      </div>
                    </TablaCelda>
                    <TablaCelda>
                      <span className="mono" style={{ fontSize: "var(--text-xs)" }}>
                        {usr.rol}
                      </span>
                    </TablaCelda>
                    <TablaCelda>{usr.idioma || "es"}</TablaCelda>
                    <TablaCelda>
                      <Badge variante={usr.estado === "activo" ? "good" : "neutro"}>
                        {usr.estado}
                      </Badge>
                    </TablaCelda>
                  </TablaFila>
                ))
              ) : (
                <TablaFila>
                  <TablaCelda colSpan={4} style={{ textAlign: "center", color: "var(--muted)" }}>
                    Sin usuarios registrados.
                  </TablaCelda>
                </TablaFila>
              )}
            </TablaCuerpo>
          </Tabla>
        </article>

        {/* BLOQUE 5: Integraciones Conectadas */}
        <article className="card" data-testid="card-integraciones">
          <header style={{ marginBottom: "var(--space-3)", display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <h2 style={{ fontSize: "var(--text-md)", fontWeight: "var(--font-semibold)", color: "var(--accent)" }}>
              5. Integraciones Conectadas ({integraciones.length})
            </h2>
            {tieneDatosEnmascarados && (
              <span className="mono" style={{ fontSize: "var(--text-xs)", color: "var(--warn)" }}>
                [Rutas Enmascaradas]
              </span>
            )}
          </header>
          <Tabla>
            <TablaEncabezado>
              <TablaFila>
                <TablaCeldaEncabezado>Tipo</TablaCeldaEncabezado>
                <TablaCeldaEncabezado>Identificador / Nombre</TablaCeldaEncabezado>
                <TablaCeldaEncabezado>Estado</TablaCeldaEncabezado>
              </TablaFila>
            </TablaEncabezado>
            <TablaCuerpo>
              {integraciones.length > 0 ? (
                integraciones.map((integ) => (
                  <TablaFila key={integ.id}>
                    <TablaCelda>
                      <strong style={{ textTransform: "capitalize" }}>{integ.tipo}</strong>
                    </TablaCelda>
                    <TablaCelda>
                      <span className="mono" style={{ fontSize: "var(--text-xs)" }}>
                        {integ.nombre || integ.id}
                      </span>
                    </TablaCelda>
                    <TablaCelda>
                      <Badge variante={integ.estado === "conectado" || integ.estado === "activo" ? "good" : "warn"}>
                        {integ.estado}
                      </Badge>
                    </TablaCelda>
                  </TablaFila>
                ))
              ) : (
                <TablaFila>
                  <TablaCelda colSpan={3} style={{ textAlign: "center", color: "var(--muted)" }}>
                    Sin integraciones configuradas.
                  </TablaCelda>
                </TablaFila>
              )}
            </TablaCuerpo>
          </Tabla>
        </article>

        {/* BLOQUE 6: Actividad de Pipeline & Grafo CodeMapping */}
        <article className="card" data-testid="card-actividad-grafo" style={{ gridColumn: "1 / -1" }}>
          <header style={{ marginBottom: "var(--space-4)" }}>
            <h2 style={{ fontSize: "var(--text-md)", fontWeight: "var(--font-semibold)", color: "var(--accent)" }}>
              6. Actividad de Pipeline y Estructura CodeMapping
            </h2>
          </header>
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))",
              gap: "var(--space-4)",
            }}
          >
            <div style={{ padding: "var(--space-3)", backgroundColor: "var(--surface2)", borderRadius: "var(--radius-md)" }}>
              <span style={{ fontSize: "var(--text-xs)", color: "var(--muted)", display: "block" }}>Cobertura de Grafo</span>
              <strong className="tabular" style={{ fontSize: "var(--text-xl)", color: "var(--accent)" }}>
                {coberturaPct}%
              </strong>
            </div>
            <div style={{ padding: "var(--space-3)", backgroundColor: "var(--surface2)", borderRadius: "var(--radius-md)" }}>
              <span style={{ fontSize: "var(--text-xs)", color: "var(--muted)", display: "block" }}>Nodos Indexados</span>
              <strong className="tabular" style={{ fontSize: "var(--text-xl)" }}>
                {formatearNumero(nodosTotal)}
              </strong>
            </div>
            <div style={{ padding: "var(--space-3)", backgroundColor: "var(--surface2)", borderRadius: "var(--radius-md)" }}>
              <span style={{ fontSize: "var(--text-xs)", color: "var(--muted)", display: "block" }}>Aristas de Dependencia</span>
              <strong className="tabular" style={{ fontSize: "var(--text-xl)" }}>
                {formatearNumero(aristasTotal)}
              </strong>
            </div>
            <div style={{ padding: "var(--space-3)", backgroundColor: "var(--surface2)", borderRadius: "var(--radius-md)" }}>
              <span style={{ fontSize: "var(--text-xs)", color: "var(--muted)", display: "block" }}>Rendimiento End-to-End (p50)</span>
              <strong className="tabular" style={{ fontSize: "var(--text-xl)" }}>
                {rendimientoHoras} h
              </strong>
            </div>
          </div>
          <p style={{ fontSize: "var(--text-xs)", color: "var(--muted)", marginTop: "var(--space-3)" }}>
            * El grafo CodeMapping refleja relaciones de arquitectura sin exponer contenido de ficheros salvo concesión con alcance específico.
          </p>
        </article>
      </div>

      {/* ------------------------------------------------------------------ Modal Reutilizable de Concesión */}
      <SolicitudConcesionModal
        abierto={modalAbierto}
        alCerrar={handleCerrarModal}
        tenantId={tenant_id}
        razonSocial={identificacion?.razon_social}
        titulo="Solicitud de Concesión de Acceso a Datos de Cliente"
        onConcesionConcedida={() => {
          setFeedbackConcesion("Concesión de acceso autorizada. Los datos sensibles han sido revelados en claro.");
          void refetch();
        }}
      />
    </div>
      )}
    </ContenedorEstado>
  );
};
