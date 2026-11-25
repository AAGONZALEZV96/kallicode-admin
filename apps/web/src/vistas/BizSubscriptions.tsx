/**
 * BizSubscriptions.tsx — Pantalla de Gestión de Suscripciones, Renovaciones y Upgrades
 *
 * Implementa el ticket [KC-ADM-B4-02] (Épica EAD4 / ADM-G08 / §18.19 - §18.20):
 * 1. Panel 1: Directorio y Radar de Renovaciones (/admin/v1/business/subscriptions).
 *    - Tabla de clientes con renovación próxima, alertas visuales (<= 15 y <= 30 días),
 *      cuota de uso, importes y filtros por estado, plan, rango de renovación y búsqueda debounced.
 * 2. Panel 2: Cola de Solicitudes de Upgrade (/admin/v1/business/upgrade-requests).
 *    - Solicitudes ordenadas por antigüedad (más antiguas primero), insignias de urgencia,
 *      transición de planes y filtros por estado y plan deseado.
 * 3. Enmascaramiento por defecto bajo política E6 con badges explícitos ("ENMASCARADO" / "EN CLARO")
 *    e integración contextual con SolicitudConcesionModal (POST /admin/v1/access-grants).
 * 4. Estados de interfaz B3-06 (ContenedorEstado, EstadoCarga, EstadoError con X-Trace-Id, EstadoVacio).
 * 5. Control de acceso RBAC estricto: staff_negocio y staff_admin permitidos; staff_soporte y staff_operaciones bloqueados.
 */

import React, { useState, useEffect, useCallback } from "react";
import { useSearchParams, Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { peticionApi, ApiError } from "../api/clienteApi";
import { useAuth } from "../estado/auth";
import { formatCurrencyEUR, formatDate, formatPercent } from "../i18n/formatters";
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

// ------------------------------------------------------------------ Tipos Suscripciones
export interface SuscripcionItem {
  tenant_id: string;
  razon_social: string;
  plan: string;
  estado: string;
  suscripcion_estado?: string;
  inicia_el: string;
  renueva_el: string;
  finaliza_el?: string | null;
  dias_para_renovacion: number;
  importe_mes: number;
  moneda: string;
  cuota_uso_pct?: number | null;
  enmascarado: boolean;
}

export interface SubscriptionsResponse {
  items: SuscripcionItem[];
  total: number;
  page: number;
  page_size: number;
  pages: number;
  frescura?: string;
  alguna_enmascarada?: boolean;
}

// ------------------------------------------------------------------ Tipos Upgrade Requests
export interface UpgradeRequestItem {
  solicitud_id: string;
  tenant_id: string;
  razon_social: string;
  plan_actual: string;
  plan_deseado: string;
  urgente: boolean;
  estado: string;
  comentario?: string;
  solicitado_el: string;
  cuota_uso_pct?: number | null;
  antiguedad_h: number;
  enmascarado: boolean;
}

export interface UpgradeRequestsResponse {
  items: UpgradeRequestItem[];
  total: number;
  page: number;
  page_size: number;
  pages: number;
  frescura?: string;
  alguna_enmascarada?: boolean;
}

export const BizSubscriptions: React.FC = () => {
  const { t, i18n } = useTranslation();
  const lang = i18n.resolvedLanguage || i18n.language;
  const { usuario } = useAuth();
  const [searchParams, setSearchParams] = useSearchParams();

  const opcionesPlan = [
    { valor: "todos", etiqueta: t("common.plans.all") },
    { valor: "starter", etiqueta: t("common.plans.starter") },
    { valor: "growth", etiqueta: t("common.plans.growth") },
    { valor: "enterprise", etiqueta: t("common.plans.enterprise") },
  ];

  const opcionesEstadoSubs = [
    { valor: "todos", etiqueta: t("common.statuses.all") },
    { valor: "activa", etiqueta: t("common.statuses.activa") },
    { valor: "periodo_gracia", etiqueta: t("common.statuses.periodo_gracia") },
    { valor: "suspendida", etiqueta: t("common.statuses.suspendida") },
    { valor: "finalizada", etiqueta: t("common.statuses.finalizada_baja") },
  ];

  const opcionesRangoRenovacion = [
    { valor: "todos", etiqueta: t("views.bizSubscriptions.renewals.windows.all") },
    { valor: "15", etiqueta: t("views.bizSubscriptions.renewals.windows.d15") },
    { valor: "30", etiqueta: t("views.bizSubscriptions.renewals.windows.d30") },
    { valor: "60", etiqueta: t("views.bizSubscriptions.renewals.windows.d60") },
    { valor: "90", etiqueta: t("views.bizSubscriptions.renewals.windows.d90") },
  ];

  const opcionesEstadoUpgrade = [
    { valor: "pendiente", etiqueta: t("views.bizSubscriptions.upgrades.statuses.pendiente") },
    { valor: "todos", etiqueta: t("views.bizSubscriptions.upgrades.statuses.todos") },
    { valor: "atendida", etiqueta: t("views.bizSubscriptions.upgrades.statuses.atendida") },
    { valor: "rechazada", etiqueta: t("views.bizSubscriptions.upgrades.statuses.rechazada") },
  ];

  const opcionesPageSize = [
    { valor: 10, etiqueta: t("common.pagination.perPageOption", { count: 10 }) },
    { valor: 25, etiqueta: t("common.pagination.perPageOption", { count: 25 }) },
    { valor: 50, etiqueta: t("common.pagination.perPageOption", { count: 50 }) },
    { valor: 100, etiqueta: t("common.pagination.perPageOption", { count: 100 }) },
  ];

  // Gestión de pestaña activa (sincronizada en URL: tab=renovaciones | tab=solicitudes)
  const tabActiva = searchParams.get("tab") === "solicitudes" ? "solicitudes" : "renovaciones";

  // Modal contextual de concesión de acceso (E6)
  const [modalConcesionAbierto, setModalConcesionAbierto] = useState<boolean>(false);
  const [tenantSeleccionadoConcesion, setTenantSeleccionadoConcesion] = useState<{
    id: string;
    nombre: string;
  } | null>(null);

  // Parámetros comunes y filtros para Suscripciones
  const pageSubs = Math.max(1, parseInt(searchParams.get("page") || "1", 10));
  const pageSizeSubs = Math.max(1, parseInt(searchParams.get("page_size") || "25", 10));
  const planSubs = searchParams.get("plan") || "todos";
  const estadoSubs = searchParams.get("estado") || "todos";
  const renuevaEnDiasSubs = searchParams.get("renueva_en_dias") || "todos";
  const orderBySubs = searchParams.get("order_by") || "renovacion-asc";
  const qSubs = searchParams.get("q") || "";

  // Filtros para Upgrade Requests
  const pageUpgrades = Math.max(1, parseInt(searchParams.get("page_upg") || "1", 10));
  const pageSizeUpgrades = Math.max(1, parseInt(searchParams.get("page_size_upg") || "25", 10));
  const estadoUpgrades = searchParams.get("estado_upg") || "pendiente";
  const planDeseadoUpgrades = searchParams.get("plan_deseado_upg") || "todos";

  // Búsqueda textual con debounce
  const [terminoBusqueda, setTerminoBusqueda] = useState<string>(qSubs);

  useEffect(() => {
    setTerminoBusqueda(qSubs);
  }, [qSubs]);

  const actualizarParams = useCallback(
    (nuevos: Record<string, string | number | null | undefined>) => {
      setSearchParams(
        (prev) => {
          const actual = new URLSearchParams(prev);
          Object.entries(nuevos).forEach(([k, v]) => {
            if (v === null || v === undefined || v === "") {
              actual.delete(k);
            } else if (k === "estado_upg") {
              actual.set(k, String(v));
            } else if (v === "todos") {
              actual.delete(k);
            } else {
              actual.set(k, String(v));
            }
          });
          return actual;
        },
        { replace: true }
      );
    },
    [setSearchParams]
  );

  // Debounce para búsqueda textual
  useEffect(() => {
    const timer = setTimeout(() => {
      if (terminoBusqueda !== qSubs) {
        actualizarParams({ q: terminoBusqueda, page: 1 });
      }
    }, 450);
    return () => clearTimeout(timer);
  }, [terminoBusqueda, qSubs, actualizarParams]);

  // ------------------------------------------------------------------ RBAC Check
  const rol = usuario?.role;
  const esRolAutorizado = rol === "staff_negocio" || rol === "staff_admin";

  // ------------------------------------------------------------------ Query 1: Suscripciones
  const {
    data: dataSubs,
    isLoading: cargandoSubs,
    error: errorSubsRaw,
    refetch: refetchSubs,
    isFetching: refrescandoSubs,
  } = useQuery<SubscriptionsResponse, ApiError>({
    queryKey: [
      "business-subscriptions",
      pageSubs,
      pageSizeSubs,
      planSubs,
      estadoSubs,
      renuevaEnDiasSubs,
      orderBySubs,
      qSubs,
    ],
    queryFn: () => {
      const params: Record<string, string | number> = {
        page: pageSubs,
        page_size: pageSizeSubs,
      };
      if (planSubs !== "todos") params.plan = planSubs;
      if (estadoSubs !== "todos") params.estado = estadoSubs;
      if (renuevaEnDiasSubs !== "todos") params.renueva_en_dias = Number(renuevaEnDiasSubs);
      if (orderBySubs) params.order_by = orderBySubs;
      if (qSubs) params.q = qSubs;

      return peticionApi<SubscriptionsResponse>("/admin/v1/business/subscriptions", { params });
    },
    enabled: esRolAutorizado && tabActiva === "renovaciones",
  });

  // ------------------------------------------------------------------ Query 2: Upgrades
  const {
    data: dataUpgrades,
    isLoading: cargandoUpgrades,
    error: errorUpgradesRaw,
    refetch: refetchUpgrades,
    isFetching: refrescandoUpgrades,
  } = useQuery<UpgradeRequestsResponse, ApiError>({
    queryKey: [
      "business-upgrade-requests",
      pageUpgrades,
      pageSizeUpgrades,
      estadoUpgrades,
      planDeseadoUpgrades,
    ],
    queryFn: () => {
      const params: Record<string, string | number> = {
        page: pageUpgrades,
        page_size: pageSizeUpgrades,
      };
      if (estadoUpgrades) params.estado = estadoUpgrades;
      if (planDeseadoUpgrades !== "todos") params.plan_deseado = planDeseadoUpgrades;

      return peticionApi<UpgradeRequestsResponse>("/admin/v1/business/upgrade-requests", { params });
    },
    enabled: esRolAutorizado && tabActiva === "solicitudes",
  });

  // Alternar ordenación en Suscripciones
  const alternarOrdenSubs = (campo: string) => {
    const descendente = orderBySubs === `${campo}-desc`;
    const nuevoOrden = descendente ? `${campo}-asc` : `${campo}-desc`;
    actualizarParams({ order_by: nuevoOrden, page: 1 });
  };

  const getIndicadorOrden = (campo: string) => {
    if (orderBySubs === `${campo}-asc`) return " ↑";
    if (orderBySubs === `${campo}-desc`) return " ↓";
    return "";
  };

  // Abrir modal de revelación
  const handleAbrirConcesion = (tId: string, nombre: string) => {
    setTenantSeleccionadoConcesion({ id: tId, nombre });
    setModalConcesionAbierto(true);
  };

  // ------------------------------------------------------------------ Bloqueo RBAC
  if (!esRolAutorizado) {
    return (
      <main style={{ padding: "1.5rem" }}>
        <div
          data-testid="error-403-rol"
          role="alert"
          style={{
            maxWidth: "640px",
            margin: "3rem auto",
            backgroundColor: "var(--card)",
            border: "1px solid var(--bad, #ef4444)",
            borderLeft: "6px solid var(--bad, #ef4444)",
            borderRadius: "var(--radius-md, 0.5rem)",
            padding: "1.5rem",
          }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: "0.75rem", marginBottom: "0.75rem" }}>
            <span style={{ fontSize: "1.75rem" }} aria-hidden="true">🚫</span>
            <h2 style={{ margin: 0, fontSize: "1.25rem", color: "var(--bad, #ef4444)" }}>
              {t("common.errors.http403.title")}
            </h2>
          </div>
          <p style={{ color: "var(--text)", margin: "0 0 1rem 0", fontSize: "0.9375rem" }}>
            {t("views.bizSubscriptions.rbacDenied")}
          </p>
          <div style={{ display: "flex", gap: "0.75rem" }}>
            <Link to="/ops/agents">
              <Boton variante="secondary" tamano="sm">
                {t("views.bizSubscriptions.goToOps")}
              </Boton>
            </Link>
          </div>
        </div>
      </main>
    );
  }

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        gap: "1.25rem",
        minHeight: "100%",
      }}
    >
      {/* Encabezado y Selector de Pestañas Concurrentes */}
      <header
        style={{
          display: "flex",
          flexWrap: "wrap",
          justifyContent: "space-between",
          alignItems: "center",
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
              display: "flex",
              alignItems: "center",
              gap: "0.5rem",
            }}
          >
            {t("views.bizSubscriptions.title")}
          </h1>
          <p style={{ color: "var(--muted)", margin: "0.25rem 0 0 0", fontSize: "0.875rem" }}>
            {t("views.bizSubscriptions.subtitle")}
          </p>
        </div>

        {/* Selector de Pestañas */}
        <div
          role="tablist"
          aria-label={t("views.bizSubscriptions.tabsAria")}
          style={{
            display: "flex",
            backgroundColor: "var(--surface)",
            padding: "0.25rem",
            borderRadius: "var(--radius-md, 0.5rem)",
            border: "1px solid var(--border)",
            gap: "0.25rem",
            overflowX: "auto",
            maxWidth: "100%",
            WebkitOverflowScrolling: "touch",
          }}
        >
          <button
            role="tab"
            aria-selected={tabActiva === "renovaciones"}
            data-testid="tab-renovaciones"
            onClick={() => actualizarParams({ tab: "renovaciones" })}
            style={{
              padding: "0.5rem 1rem",
              borderRadius: "var(--radius-sm, 0.375rem)",
              border: "none",
              backgroundColor: tabActiva === "renovaciones" ? "var(--surface2)" : "transparent",
              color: tabActiva === "renovaciones" ? "var(--text)" : "var(--muted)",
              fontWeight: tabActiva === "renovaciones" ? 600 : 400,
              fontSize: "0.875rem",
              cursor: "pointer",
              transition: "all 0.15s ease",
            }}
          >
            {t("views.bizSubscriptions.tabRenewals")}{" "}
            {dataSubs?.total !== undefined ? `(${dataSubs.total})` : ""}
          </button>
          <button
            role="tab"
            aria-selected={tabActiva === "solicitudes"}
            data-testid="tab-solicitudes"
            onClick={() => actualizarParams({ tab: "solicitudes" })}
            style={{
              padding: "0.5rem 1rem",
              borderRadius: "var(--radius-sm, 0.375rem)",
              border: "none",
              backgroundColor: tabActiva === "solicitudes" ? "var(--surface2)" : "transparent",
              color: tabActiva === "solicitudes" ? "var(--text)" : "var(--muted)",
              fontWeight: tabActiva === "solicitudes" ? 600 : 400,
              fontSize: "0.875rem",
              cursor: "pointer",
              transition: "all 0.15s ease",
            }}
          >
            {t("views.bizSubscriptions.tabUpgrades")}{" "}
            {dataUpgrades?.total !== undefined ? `(${dataUpgrades.total})` : ""}
          </button>
        </div>
      </header>

      {/* ---------------------------------------------------------------- PANEL 1: RENOVACIONES */}
      {tabActiva === "renovaciones" && (
        <section
          aria-label={t("views.bizSubscriptions.renewals.regionLabel")}
          style={{ display: "flex", flexDirection: "column", gap: "1rem" }}
        >
          {/* Barra de Filtros y Búsqueda */}
          <div
            style={{
              backgroundColor: "var(--card)",
              padding: "1rem",
              borderRadius: "var(--radius-md, 0.5rem)",
              border: "1px solid var(--border)",
              display: "flex",
              flexWrap: "wrap",
              alignItems: "center",
              gap: "1rem",
              justifyContent: "space-between",
            }}
          >
            <div style={{ display: "flex", flexWrap: "wrap", alignItems: "center", gap: "0.75rem", flex: 1 }}>
              <div style={{ minWidth: "200px", maxWidth: "320px", flex: 1 }}>
                <Input
                  id="filtro-busqueda-subs"
                  data-testid="input-busqueda-subs"
                  placeholder={t("views.bizSubscriptions.renewals.searchPlaceholder")}
                  value={terminoBusqueda}
                  onChange={(e) => setTerminoBusqueda(e.target.value)}
                  aria-label={t("views.bizSubscriptions.renewals.searchAria")}
                />
              </div>

              <div style={{ width: "160px" }}>
                <Select
                  id="filtro-plan-subs"
                  data-testid="select-plan-subs"
                  opciones={opcionesPlan}
                  value={planSubs}
                  onChange={(e) => actualizarParams({ plan: e.target.value, page: 1 })}
                  aria-label={t("views.bizSubscriptions.renewals.planAria")}
                />
              </div>

              <div style={{ width: "180px" }}>
                <Select
                  id="filtro-estado-subs"
                  data-testid="select-estado-subs"
                  opciones={opcionesEstadoSubs}
                  value={estadoSubs}
                  onChange={(e) => actualizarParams({ estado: e.target.value, page: 1 })}
                  aria-label={t("views.bizSubscriptions.renewals.statusAria")}
                />
              </div>

              <div style={{ width: "210px" }}>
                <Select
                  id="filtro-renovacion-subs"
                  data-testid="select-renovacion-subs"
                  opciones={opcionesRangoRenovacion}
                  value={renuevaEnDiasSubs}
                  onChange={(e) => actualizarParams({ renueva_en_dias: e.target.value, page: 1 })}
                  aria-label={t("views.bizSubscriptions.renewals.windowAria")}
                />
              </div>
            </div>

            <div style={{ display: "flex", alignItems: "center", gap: "0.75rem" }}>
              <Boton
                variante="ghost"
                tamano="sm"
                onClick={() => refetchSubs()}
                disabled={cargandoSubs || refrescandoSubs}
                aria-label={t("views.bizSubscriptions.renewals.refreshAria")}
              >
                {refrescandoSubs
                  ? t("common.actions.refreshing")
                  : t("views.bizSubscriptions.renewals.refreshLabel")}
              </Boton>
            </div>
          </div>

          {/* Contenedor de Estado para la Tabla de Renovaciones */}
          <ContenedorEstado
            cargando={cargandoSubs}
            error={errorSubsRaw}
            vacio={!cargandoSubs && (!dataSubs?.items || dataSubs.items.length === 0)}
            tipoCarga="tabla"
            filasCarga={5}
            columnasCarga={9}
            alReintentar={() => refetchSubs()}
            tituloVacio={t("views.bizSubscriptions.renewals.emptyTitle")}
            descripcionVacio={t("views.bizSubscriptions.renewals.emptyDescription")}
            alAccionarVacio={() =>
              actualizarParams({ plan: null, estado: null, renueva_en_dias: null, q: null, page: 1 })
            }
            textoAccionVacio={t("common.actions.clearFilters")}
          >
            {dataSubs && (
              <div
                style={{
                  backgroundColor: "var(--card)",
                  borderRadius: "var(--radius-md, 0.5rem)",
                  border: "1px solid var(--border)",
                  overflow: "hidden",
                }}
              >
                <div style={{ overflowX: "auto" }}>
                  <Tabla aria-label={t("views.bizSubscriptions.renewals.tableAria")}>
                    <TablaEncabezado>
                      <TablaFila>
                        <TablaCeldaEncabezado
                          onClick={() => alternarOrdenSubs("tenant_id")}
                          style={{ cursor: "pointer" }}
                        >
                          {t("views.bizSubscriptions.renewals.colTenant")}{getIndicadorOrden("tenant_id")}
                        </TablaCeldaEncabezado>
                        <TablaCeldaEncabezado
                          onClick={() => alternarOrdenSubs("nombre")}
                          style={{ cursor: "pointer" }}
                        >
                          {t("views.bizSubscriptions.renewals.colName")}{getIndicadorOrden("nombre")}
                        </TablaCeldaEncabezado>
                        <TablaCeldaEncabezado>{t("views.bizSubscriptions.renewals.colPlan")}</TablaCeldaEncabezado>
                        <TablaCeldaEncabezado>{t("views.bizSubscriptions.renewals.colStatus")}</TablaCeldaEncabezado>
                        <TablaCeldaEncabezado>{t("views.bizSubscriptions.renewals.colStart")}</TablaCeldaEncabezado>
                        <TablaCeldaEncabezado
                          onClick={() => alternarOrdenSubs("renovacion")}
                          style={{ cursor: "pointer" }}
                        >
                          {t("views.bizSubscriptions.renewals.colRenew")}{getIndicadorOrden("renovacion")}
                        </TablaCeldaEncabezado>
                        <TablaCeldaEncabezado>{t("views.bizSubscriptions.renewals.colDays")}</TablaCeldaEncabezado>
                        <TablaCeldaEncabezado
                          onClick={() => alternarOrdenSubs("importe")}
                          style={{ cursor: "pointer" }}
                        >
                          {t("views.bizSubscriptions.renewals.colAmount")}{getIndicadorOrden("importe")}
                        </TablaCeldaEncabezado>
                        <TablaCeldaEncabezado>{t("views.bizSubscriptions.renewals.colQuota")}</TablaCeldaEncabezado>
                      </TablaFila>
                    </TablaEncabezado>
                    <TablaCuerpo>
                      {dataSubs.items.map((sub) => {
                        const esCritica = sub.dias_para_renovacion <= 15;
                        const esAdvertencia = sub.dias_para_renovacion <= 30 && !esCritica;

                        return (
                          <TablaFila
                            key={sub.tenant_id}
                            data-testid={`fila-suscripcion-${sub.tenant_id}`}
                            style={{
                              backgroundColor: esCritica
                                ? "var(--bad-bg, rgba(239, 68, 68, 0.05))"
                                : esAdvertencia
                                ? "var(--warn-bg, rgba(245, 158, 11, 0.05))"
                                : "transparent",
                            }}
                          >
                            <TablaCelda>
                              <Link
                                to={`/business/customers/${sub.tenant_id}`}
                                style={{
                                  fontWeight: 600,
                                  color: "var(--accent, #38bdf8)",
                                  textDecoration: "none",
                                  fontFamily: "monospace",
                                }}
                              >
                                {sub.tenant_id}
                              </Link>
                            </TablaCelda>

                            <TablaCelda>
                              <div style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
                                <span>{sub.razon_social}</span>
                                {sub.enmascarado ? (
                                  <button
                                    onClick={() => handleAbrirConcesion(sub.tenant_id, sub.razon_social)}
                                    title={t("views.bizSubscriptions.maskedTooltip")}
                                    style={{
                                      background: "none",
                                      border: "none",
                                      padding: 0,
                                      cursor: "pointer",
                                    }}
                                    data-testid={`btn-revelar-${sub.tenant_id}`}
                                  >
                                    <Badge variante="warn">{t("common.states.masked")}</Badge>
                                  </button>
                                ) : (
                                  <Badge variante="good">{t("common.states.unmasked")}</Badge>
                                )}
                              </div>
                            </TablaCelda>

                            <TablaCelda>
                              <Badge
                                variante={
                                  sub.plan === "enterprise"
                                    ? "accent"
                                    : sub.plan === "growth"
                                    ? "good"
                                    : "neutro"
                                }
                              >
                                {sub.plan}
                              </Badge>
                            </TablaCelda>

                            <TablaCelda>
                              <Badge
                                variante={
                                  sub.estado === "activa"
                                    ? "good"
                                    : sub.estado === "periodo_gracia"
                                    ? "warn"
                                    : "bad"
                                }
                              >
                                {sub.estado}
                              </Badge>
                            </TablaCelda>

                            <TablaCelda style={{ fontSize: "0.8125rem", color: "var(--muted)" }}>
                              {formatDate(sub.inicia_el, undefined, lang)}
                            </TablaCelda>

                            <TablaCelda style={{ fontSize: "0.8125rem" }}>
                              {formatDate(sub.renueva_el, undefined, lang)}
                            </TablaCelda>

                            <TablaCelda>
                              <div style={{ display: "flex", alignItems: "center", gap: "0.375rem" }}>
                                <span style={{ fontWeight: 600 }}>
                                  {t("views.bizSubscriptions.renewals.daysShort", {
                                    days: sub.dias_para_renovacion,
                                  })}
                                </span>
                                {esCritica && (
                                  <Badge variante="bad" data-testid="alerta-renovacion-critica">
                                    {t("views.bizSubscriptions.renewals.critical15")}
                                  </Badge>
                                )}
                                {esAdvertencia && (
                                  <Badge variante="warn" data-testid="alerta-renovacion-aviso">
                                    {t("views.bizSubscriptions.renewals.warning30")}
                                  </Badge>
                                )}
                              </div>
                            </TablaCelda>

                            <TablaCelda style={{ fontWeight: 600 }}>
                              {formatCurrencyEUR(sub.importe_mes, sub.moneda, lang)}
                            </TablaCelda>

                            <TablaCelda>
                              {sub.cuota_uso_pct !== null && sub.cuota_uso_pct !== undefined ? (
                                <div style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
                                  <div
                                    style={{
                                      width: "60px",
                                      height: "6px",
                                      backgroundColor: "var(--surface2)",
                                      borderRadius: "3px",
                                      overflow: "hidden",
                                    }}
                                  >
                                    <div
                                      style={{
                                        width: `${Math.min(100, sub.cuota_uso_pct)}%`,
                                        height: "100%",
                                        backgroundColor:
                                          sub.cuota_uso_pct > 90
                                            ? "var(--bad)"
                                            : sub.cuota_uso_pct > 75
                                            ? "var(--warn)"
                                            : "var(--good)",
                                      }}
                                    />
                                  </div>
                                  <span style={{ fontSize: "0.75rem", color: "var(--muted)" }}>
                                    {formatPercent(sub.cuota_uso_pct, { decimals: 1, lang })}
                                  </span>
                                </div>
                              ) : (
                                <span style={{ color: "var(--muted)", fontSize: "0.8125rem" }}>
                                  {t("common.states.noData")}
                                </span>
                              )}
                            </TablaCelda>
                          </TablaFila>
                        );
                      })}
                    </TablaCuerpo>
                  </Tabla>
                </div>

                {/* Barra de Paginación Transversal */}
                <footer
                  style={{
                    padding: "0.75rem 1rem",
                    borderTop: "1px solid var(--border)",
                    display: "flex",
                    flexWrap: "wrap",
                    alignItems: "center",
                    justifyContent: "space-between",
                    gap: "1rem",
                    backgroundColor: "var(--surface)",
                  }}
                >
                  <div style={{ fontSize: "0.8125rem", color: "var(--muted)" }}>
                    {t("views.bizSubscriptions.renewals.showing", {
                      count: dataSubs.items.length,
                      total: dataSubs.total,
                      page: dataSubs.page,
                      pages: dataSubs.pages,
                    })}
                  </div>

                  <div style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
                    <div style={{ width: "120px" }}>
                      <Select
                        id="select-pagesize-subs"
                        data-testid="select-pagesize-subs"
                        opciones={opcionesPageSize}
                        value={pageSizeSubs}
                        onChange={(e) => actualizarParams({ page_size: Number(e.target.value), page: 1 })}
                        aria-label={t("common.pagination.itemsPerPage")}
                      />
                    </div>

                    <Boton
                      variante="secondary"
                      tamano="sm"
                      disabled={pageSubs <= 1}
                      onClick={() => actualizarParams({ page: pageSubs - 1 })}
                      aria-label={t("common.pagination.previousPage")}
                    >
                      {t("common.pagination.previous")}
                    </Boton>
                    <Boton
                      variante="secondary"
                      tamano="sm"
                      disabled={pageSubs >= dataSubs.pages}
                      onClick={() => actualizarParams({ page: pageSubs + 1 })}
                      aria-label={t("common.pagination.nextPage")}
                    >
                      {t("common.pagination.next")}
                    </Boton>
                  </div>
                </footer>
              </div>
            )}
          </ContenedorEstado>
        </section>
      )}

      {/* ---------------------------------------------------------------- PANEL 2: SOLICITUDES UPGRADE */}
      {tabActiva === "solicitudes" && (
        <section
          aria-label={t("views.bizSubscriptions.upgrades.regionLabel")}
          style={{ display: "flex", flexDirection: "column", gap: "1rem" }}
        >
          {/* Barra de Filtros de Solicitudes */}
          <div
            style={{
              backgroundColor: "var(--card)",
              padding: "1rem",
              borderRadius: "var(--radius-md, 0.5rem)",
              border: "1px solid var(--border)",
              display: "flex",
              flexWrap: "wrap",
              alignItems: "center",
              gap: "1rem",
              justifyContent: "space-between",
            }}
          >
            <div style={{ display: "flex", flexWrap: "wrap", alignItems: "center", gap: "0.75rem", flex: 1 }}>
              <div style={{ width: "220px" }}>
                <Select
                  id="filtro-estado-upg"
                  data-testid="select-estado-upg"
                  opciones={opcionesEstadoUpgrade}
                  value={estadoUpgrades}
                  onChange={(e) => actualizarParams({ estado_upg: e.target.value, page_upg: 1 })}
                  aria-label={t("views.bizSubscriptions.upgrades.statusAria")}
                />
              </div>

              <div style={{ width: "200px" }}>
                <Select
                  id="filtro-plan-deseado-upg"
                  data-testid="select-plan-deseado-upg"
                  opciones={opcionesPlan}
                  value={planDeseadoUpgrades}
                  onChange={(e) => actualizarParams({ plan_deseado_upg: e.target.value, page_upg: 1 })}
                  aria-label={t("views.bizSubscriptions.upgrades.desiredPlanAria")}
                />
              </div>

              <div style={{ fontSize: "0.8125rem", color: "var(--muted)" }}>
                {t("views.bizSubscriptions.upgrades.autoOrderHint")}
              </div>
            </div>

            <Boton
              variante="ghost"
              tamano="sm"
              onClick={() => refetchUpgrades()}
              disabled={cargandoUpgrades || refrescandoUpgrades}
              aria-label={t("views.bizSubscriptions.upgrades.refreshAria")}
            >
              {refrescandoUpgrades
                ? t("common.actions.refreshing")
                : t("views.bizSubscriptions.renewals.refreshLabel")}
            </Boton>
          </div>

          {/* Contenedor de Estado para Cola de Upgrades */}
          <ContenedorEstado
            cargando={cargandoUpgrades}
            error={errorUpgradesRaw}
            vacio={!cargandoUpgrades && (!dataUpgrades?.items || dataUpgrades.items.length === 0)}
            tipoCarga="tabla"
            filasCarga={4}
            columnasCarga={8}
            alReintentar={() => refetchUpgrades()}
            tituloVacio={t("views.bizSubscriptions.upgrades.emptyTitle")}
            descripcionVacio={t("views.bizSubscriptions.upgrades.emptyDescription")}
            alAccionarVacio={() => actualizarParams({ estado_upg: "todos", plan_deseado_upg: null, page_upg: 1 })}
            textoAccionVacio={t("views.bizSubscriptions.upgrades.emptyAction")}
          >
            {dataUpgrades && (
              <div
                style={{
                  backgroundColor: "var(--card)",
                  borderRadius: "var(--radius-md, 0.5rem)",
                  border: "1px solid var(--border)",
                  overflow: "hidden",
                }}
              >
                <div style={{ overflowX: "auto" }}>
                  <Tabla aria-label={t("views.bizSubscriptions.upgrades.tableAria")}>
                    <TablaEncabezado>
                      <TablaFila>
                        <TablaCeldaEncabezado>{t("views.bizSubscriptions.upgrades.colId")}</TablaCeldaEncabezado>
                        <TablaCeldaEncabezado>{t("views.bizSubscriptions.upgrades.colTenant")}</TablaCeldaEncabezado>
                        <TablaCeldaEncabezado>{t("views.bizSubscriptions.upgrades.colName")}</TablaCeldaEncabezado>
                        <TablaCeldaEncabezado>{t("views.bizSubscriptions.upgrades.colTransition")}</TablaCeldaEncabezado>
                        <TablaCeldaEncabezado>{t("views.bizSubscriptions.upgrades.colRequested")}</TablaCeldaEncabezado>
                        <TablaCeldaEncabezado>{t("views.bizSubscriptions.upgrades.colAge")}</TablaCeldaEncabezado>
                        <TablaCeldaEncabezado>{t("views.bizSubscriptions.upgrades.colPriority")}</TablaCeldaEncabezado>
                        <TablaCeldaEncabezado>{t("views.bizSubscriptions.upgrades.colStatus")}</TablaCeldaEncabezado>
                      </TablaFila>
                    </TablaEncabezado>
                    <TablaCuerpo>
                      {dataUpgrades.items.map((upg) => (
                        <TablaFila key={upg.solicitud_id} data-testid={`fila-upgrade-${upg.solicitud_id}`}>
                          <TablaCelda style={{ fontFamily: "monospace", fontSize: "0.8125rem" }}>
                            {upg.solicitud_id}
                          </TablaCelda>

                          <TablaCelda>
                            <Link
                              to={`/business/customers/${upg.tenant_id}`}
                              style={{
                                fontWeight: 600,
                                color: "var(--accent, #38bdf8)",
                                textDecoration: "none",
                                fontFamily: "monospace",
                              }}
                            >
                              {upg.tenant_id}
                            </Link>
                          </TablaCelda>

                          <TablaCelda>
                            <div style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
                              <span>{upg.razon_social}</span>
                              {upg.enmascarado ? (
                                <button
                                  onClick={() => handleAbrirConcesion(upg.tenant_id, upg.razon_social)}
                                  title={t("views.bizSubscriptions.maskedTooltip")}
                                  style={{
                                    background: "none",
                                    border: "none",
                                    padding: 0,
                                    cursor: "pointer",
                                  }}
                                  data-testid={`btn-revelar-upg-${upg.solicitud_id}`}
                                >
                                  <Badge variante="warn">{t("common.states.masked")}</Badge>
                                </button>
                              ) : (
                                <Badge variante="good">{t("common.states.unmasked")}</Badge>
                              )}
                            </div>
                          </TablaCelda>

                          <TablaCelda>
                            <div style={{ display: "flex", alignItems: "center", gap: "0.375rem" }}>
                              <Badge variante="neutro">{upg.plan_actual}</Badge>
                              <span style={{ color: "var(--muted)" }}>→</span>
                              <Badge variante="accent">{upg.plan_deseado}</Badge>
                            </div>
                          </TablaCelda>

                          <TablaCelda style={{ fontSize: "0.8125rem", color: "var(--muted)" }}>
                            {formatDate(upg.solicitado_el, undefined, lang)}
                          </TablaCelda>

                          <TablaCelda>
                            <span style={{ fontWeight: 600 }}>
                              {t("views.bizSubscriptions.upgrades.ageHours", { hours: upg.antiguedad_h })}
                            </span>
                          </TablaCelda>

                          <TablaCelda>
                            {upg.urgente ? (
                              <Badge variante="bad" data-testid="badge-urgente">
                                {t("views.bizSubscriptions.upgrades.urgent")}
                              </Badge>
                            ) : (
                              <Badge variante="neutro">{t("views.bizSubscriptions.upgrades.normal")}</Badge>
                            )}
                          </TablaCelda>

                          <TablaCelda>
                            <Badge
                              variante={
                                upg.estado === "pendiente"
                                  ? "warn"
                                  : upg.estado === "atendida"
                                  ? "good"
                                  : "bad"
                              }
                            >
                              {upg.estado}
                            </Badge>
                          </TablaCelda>
                        </TablaFila>
                      ))}
                    </TablaCuerpo>
                  </Tabla>
                </div>

                {/* Paginación de Solicitudes */}
                <footer
                  style={{
                    padding: "0.75rem 1rem",
                    borderTop: "1px solid var(--border)",
                    display: "flex",
                    flexWrap: "wrap",
                    alignItems: "center",
                    justifyContent: "space-between",
                    gap: "1rem",
                    backgroundColor: "var(--surface)",
                  }}
                >
                  <div style={{ fontSize: "0.8125rem", color: "var(--muted)" }}>
                    {t("views.bizSubscriptions.upgrades.showing", {
                      count: dataUpgrades.items.length,
                      total: dataUpgrades.total,
                      page: dataUpgrades.page,
                      pages: dataUpgrades.pages,
                    })}
                  </div>

                  <div style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
                    <Boton
                      variante="secondary"
                      tamano="sm"
                      disabled={pageUpgrades <= 1}
                      onClick={() => actualizarParams({ page_upg: pageUpgrades - 1 })}
                      aria-label={t("views.bizSubscriptions.upgrades.prevAria")}
                    >
                      {t("common.pagination.previous")}
                    </Boton>
                    <Boton
                      variante="secondary"
                      tamano="sm"
                      disabled={pageUpgrades >= dataUpgrades.pages}
                      onClick={() => actualizarParams({ page_upg: pageUpgrades + 1 })}
                      aria-label={t("views.bizSubscriptions.upgrades.nextAria")}
                    >
                      {t("common.pagination.next")}
                    </Boton>
                  </div>
                </footer>
              </div>
            )}
          </ContenedorEstado>
        </section>
      )}

      {/* Modal Reutilizable de Concesión de Acceso y Revelación E6 */}
      <SolicitudConcesionModal
        abierto={modalConcesionAbierto}
        alCerrar={() => setModalConcesionAbierto(false)}
        tenantId={tenantSeleccionadoConcesion?.id}
        razonSocial={tenantSeleccionadoConcesion?.nombre}
        onConcesionConcedida={() => {
          refetchSubs();
          refetchUpgrades();
        }}
      />
    </div>
  );
};
