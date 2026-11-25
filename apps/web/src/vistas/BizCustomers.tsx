/**
 * BizCustomers.tsx — Pantalla de Listado Paginado de Clientes (§18.17 / §18.23)
 *
 * Expone la tabla densa de organizaciones cliente conectada a /admin/v1/business/customers:
 * 1. Columnas completas: tenant_id, razon_social, plan, estado, lineas_contratadas,
 *    consumo_ciclo (LOC, tokens, % cuota), ultima_actividad y badge de enmascarado.
 * 2. Barra de filtros (plan, estado), búsqueda por texto con debounce (q) y ordenación
 *    por allowlist autorizada (-asc, -desc).
 * 3. Barra de paginación transversal (items, total, page, page_size, pages) sincronizada con URL.
 * 4. Navegación directa hacia /business/customers/:tenant_id y acción contextual de revelación (E6).
 * 5. Skeleton loading accesible (role="status", aria-busy="true"), tarjeta de error con X-Trace-Id
 *    y control de acceso RBAC (staff_soporte, staff_negocio, staff_admin permitidos; staff_operaciones bloqueado).
 */

import React, { useState, useEffect, useCallback } from "react";
import { useSearchParams, Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { peticionApi, ApiError } from "../api/clienteApi";
import { useAuth } from "../estado/auth";
import { formatDate, formatNumber, formatPercent, formatTokens } from "../i18n/formatters";
import { Boton } from "../componentes/Boton";
import { Badge } from "../componentes/Badge";
import { Select } from "../componentes/Select";
import { Input } from "../componentes/Input";
import { Modal } from "../componentes/Modal";
import { ContenedorEstado } from "../componentes/ContenedorEstado";
import { SolicitudConcesionModal } from "../componentes/SolicitudConcesionModal";
import { ControlExportarReporte } from "../componentes/ControlExportarReporte";
import {
  Tabla,
  TablaEncabezado,
  TablaCuerpo,
  TablaFila,
  TablaCeldaEncabezado,
  TablaCelda,
} from "../componentes/Tabla";

export interface ConsumoCicloCliente {
  loc: number;
  tokens: number;
  cuota_pct: number;
}

export interface ClienteItem {
  tenant_id: string;
  razon_social: string;
  dominio?: string;
  plan: string;
  estado: string;
  lineas_contratadas: number;
  lineas_activas?: number;
  alta_el: string;
  usuarios_activos?: number;
  tickets_abiertos?: number;
  ultima_actividad: string;
  consumo_ciclo: ConsumoCicloCliente;
  mrr_eur?: number;
  enmascarado: boolean;
}

export interface ClientesResponse {
  items: ClienteItem[];
  total: number;
  page: number;
  page_size: number;
  pages: number;
  frescura?: string;
  alguna_enmascarada?: boolean;
}

export const BizCustomers: React.FC = () => {
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

  const opcionesEstado = [
    { valor: "todos", etiqueta: t("common.statuses.all") },
    { valor: "activa", etiqueta: t("common.statuses.activa") },
    { valor: "periodo_gracia", etiqueta: t("common.statuses.periodo_gracia_moroso") },
    { valor: "suspendida", etiqueta: t("common.statuses.suspendida") },
    { valor: "finalizada", etiqueta: t("common.statuses.finalizada_baja") },
  ];

  const opcionesPageSize = [
    { valor: 10, etiqueta: t("common.pagination.perPageOption", { count: 10 }) },
    { valor: 25, etiqueta: t("common.pagination.perPageOption", { count: 25 }) },
    { valor: 50, etiqueta: t("common.pagination.perPageOption", { count: 50 }) },
    { valor: 100, etiqueta: t("common.pagination.perPageOption", { count: 100 }) },
  ];

  // Control de modales: explicativo y operativo de concesión
  const [modalInformativoAbierto, setModalInformativoAbierto] = useState<boolean>(false);
  const [modalConcesionAbierto, setModalConcesionAbierto] = useState<boolean>(false);
  const [mostrarTodasColumnas, setMostrarTodasColumnas] = useState<boolean>(false);
  const [tenantSeleccionado, setTenantSeleccionado] = useState<{
    tenant_id: string;
    razon_social: string;
  } | null>(null);

  // Parámetros leídos de la URL
  const page = Math.max(1, parseInt(searchParams.get("page") || "1", 10));
  const pageSize = Math.max(1, parseInt(searchParams.get("page_size") || "25", 10));
  const plan = searchParams.get("plan") || "todos";
  const estado = searchParams.get("estado") || "todos";
  const urlQ = searchParams.get("q") || "";
  const sort = searchParams.get("sort") || "";

  // Estado local para input de búsqueda con debounce
  const [busquedaInput, setBusquedaInput] = useState<string>(urlQ);

  // Sincronizar input cuando cambia la URL
  useEffect(() => {
    setBusquedaInput(urlQ);
  }, [urlQ]);

  // Actualizador auxiliar de parámetros en URL
  const actualizarParams = useCallback(
    (nuevos: Record<string, string | number | undefined | null>) => {
      setSearchParams((prev) => {
        const clon = new URLSearchParams(prev);
        for (const [clave, valor] of Object.entries(nuevos)) {
          if (valor === undefined || valor === null || valor === "" || valor === "todos") {
            clon.delete(clave);
          } else {
            clon.set(clave, String(valor));
          }
        }
        return clon;
      });
    },
    [setSearchParams]
  );

  // Debounce de 300ms para búsqueda por texto
  useEffect(() => {
    const timer = setTimeout(() => {
      if (busquedaInput !== urlQ) {
        actualizarParams({ q: busquedaInput.trim(), page: 1 });
      }
    }, 300);

    return () => clearTimeout(timer);
  }, [busquedaInput, urlQ, actualizarParams]);

  // Validación RBAC: personal de soporte, negocio o administración
  const rolNoAutorizado = Boolean(usuario) && usuario?.role === "staff_operaciones";

  // Consulta TanStack Query
  const { data, isLoading, isFetching, error, refetch } = useQuery<ClientesResponse, ApiError>({
    queryKey: ["business-customers", page, pageSize, plan, estado, urlQ, sort],
    queryFn: () =>
      peticionApi<ClientesResponse>("/admin/v1/business/customers", {
        params: {
          page,
          page_size: pageSize,
          plan: plan !== "todos" ? plan : undefined,
          estado: estado !== "todos" ? estado : undefined,
          q: urlQ || undefined,
          sort: sort || undefined,
        },
      }),
    enabled: !rolNoAutorizado,
    placeholderData: (previousData) => previousData,
    staleTime: 30000,
  });

  // Alternador de ordenación sobre la allowlist
  const alternarOrden = (campo: string) => {
    const ordenActual = sort === `${campo}-asc` ? `${campo}-desc` : `${campo}-asc`;
    actualizarParams({ sort: ordenActual, page: 1 });
  };

  const iconoOrden = (campo: string) => {
    if (sort === `${campo}-asc`) return " ↑";
    if (sort === `${campo}-desc`) return " ↓";
    return "";
  };

  // 1. Pantalla de denegación visual RBAC ante staff_operaciones
  if (rolNoAutorizado) {
    return (
      <main
        className="biz-customers-access-denied"
        data-testid="customers-error"
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
          {t("views.bizCustomers.rbacDenied", { role: usuario?.role })}
        </p>
      </main>
    );
  }

  // Cálculos de paginación
  const total = data?.total || 0;
  const items = data?.items || [];
  const pages = data?.pages || 1;
  const inicioRango = total === 0 ? 0 : (page - 1) * pageSize + 1;
  const finRango = Math.min(page * pageSize, total);

  // Variante semántica para badge de plan
  const planVariante = (p: string): "neutro" | "accent" | "good" => {
    switch (p.toLowerCase()) {
      case "enterprise":
        return "good";
      case "growth":
        return "accent";
      default:
        return "neutro";
    }
  };

  // Variante semántica para badge de estado
  const estadoVariante = (e: string): "good" | "warn" | "bad" | "neutro" => {
    const norm = e.toLowerCase();
    if (norm.startsWith("act")) return "good";
    if (norm.includes("gracia") || norm.includes("moroso")) return "warn";
    if (norm.startsWith("susp")) return "bad";
    return "neutro";
  };

  return (
    <ContenedorEstado
      cargando={isLoading && !data}
      error={error}
      vacio={!isLoading && !error && items.length === 0}
      tipoCarga="tabla"
      filasCarga={5}
      columnasCarga={6}
      dataTestIdCarga="customers-loading"
      dataTestIdError="customers-error"
      dataTestIdTrace="customers-trace-id"
      tituloError={
        (error as ApiError)?.status === 503 || (error as ApiError)?.codigo === "AGREGADO_NO_DISPONIBLE"
          ? t("common.errors.aggregatesRefreshing")
          : undefined
      }
      mensajeError={
        (error as ApiError)?.status === 503 || (error as ApiError)?.codigo === "AGREGADO_NO_DISPONIBLE"
          ? t("views.bizCustomers.error503Message")
          : undefined
      }
      textoBotonReintento={t("common.actions.retryQuery")}
      alReintentar={() => void refetch()}
    >
      {data && (
        <main
          className="biz-customers"
          aria-live="polite"
          style={{ display: "flex", flexDirection: "column", gap: "1.5rem" }}
        >
          {/* Cabecera de la Vista */}
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
              <h1 style={{ fontSize: "1.5rem", fontWeight: 700, color: "var(--text)", margin: 0 }}>
                {t("views.bizCustomers.title")}
              </h1>
              <p style={{ fontSize: "0.875rem", color: "var(--muted)", margin: "0.25rem 0 0 0" }}>
                {t("views.bizCustomers.subtitle")}
              </p>
            </div>

            <div className="kc-toolbar-actions">
              {data.alguna_enmascarada && (
                <Boton
                  variante="ghost"
                  tamano="sm"
                  onClick={() => setModalInformativoAbierto(true)}
                  aria-label={t("views.bizCustomers.privacyPolicyAria")}
                >
                  {t("views.bizCustomers.privacyPolicyButton")}
                </Boton>
              )}
              <ControlExportarReporte
                tipo="clientes"
                etiquetaBoton={t("views.bizCustomers.exportButton")}
                formatosPermitidos={["csv", "xlsx", "pdf"]}
                rolesPermitidos={["staff_negocio", "staff_admin"]}
              />
              <Boton
                variante="secondary"
                tamano="sm"
                onClick={() => void refetch()}
                disabled={isFetching}
                aria-label={t("views.bizCustomers.refreshAria")}
              >
                {isFetching ? t("common.actions.refreshing") : t("common.actions.refresh")}
              </Boton>
            </div>
          </header>

          {/* Alerta Contextual Informativa ante Datos Enmascarados */}
          {data.alguna_enmascarada && (
            <div
              data-testid="banner-enmascaramiento"
              style={{
                padding: "0.75rem 1rem",
                backgroundColor: "var(--warn-bg)",
                borderRadius: "var(--radius-md)",
                border: "1px solid var(--warn)",
                display: "flex",
                justifyContent: "space-between",
                alignItems: "center",
                flexWrap: "wrap",
                gap: "0.5rem",
              }}
            >
              <div style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
                <Badge variante="warn">{t("views.bizCustomers.maskingBanner.badge")}</Badge>
                <span style={{ fontSize: "0.8125rem", color: "var(--text)" }}>
                  {t("views.bizCustomers.maskingBanner.text")}
                </span>
              </div>
              <Boton
                variante="ghost"
                tamano="sm"
                onClick={() => {
                  const primerEnmascarado = items.find((c) => c.enmascarado);
                  setTenantSeleccionado(
                    primerEnmascarado
                      ? { tenant_id: primerEnmascarado.tenant_id, razon_social: primerEnmascarado.razon_social }
                      : null
                  );
                  setModalConcesionAbierto(true);
                }}
              >
                {t("common.actions.requestJustifiedAccess")}
              </Boton>
            </div>
          )}

      {/* Barra de Filtros, Búsqueda y Ordenación */}
      <section
        aria-label={t("views.bizCustomers.filters.regionLabel")}
        className="kc-filter-bar"
        style={{
          padding: "1rem",
          backgroundColor: "var(--card)",
          borderRadius: "var(--radius-md)",
          border: "1px solid var(--border)",
        }}
      >
        {/* Búsqueda por texto (q) */}
        <div className="kc-filter-item-wide">
          <Input
            id="filtro-busqueda-clientes"
            etiqueta={t("views.bizCustomers.filters.searchLabel")}
            placeholder={t("views.bizCustomers.filters.searchPlaceholder")}
            value={busquedaInput}
            onChange={(e) => setBusquedaInput(e.target.value)}
          />
        </div>

        {/* Filtro por Plan */}
        <div className="kc-filter-item">
          <Select
            id="filtro-plan-clientes"
            etiqueta={t("views.bizCustomers.filters.planLabel")}
            opciones={opcionesPlan}
            value={plan}
            onChange={(e) => actualizarParams({ plan: e.target.value, page: 1 })}
          />
        </div>

        {/* Filtro por Estado */}
        <div className="kc-filter-item">
          <Select
            id="filtro-estado-clientes"
            etiqueta={t("views.bizCustomers.filters.statusLabel")}
            opciones={opcionesEstado}
            value={estado}
            onChange={(e) => actualizarParams({ estado: e.target.value, page: 1 })}
          />
        </div>

        {/* Botón para restablecer filtros si hay alguno activo */}
        {(plan !== "todos" || estado !== "todos" || urlQ !== "" || sort !== "") && (
          <div className="kc-filter-actions">
            <Boton
              variante="ghost"
              tamano="sm"
              onClick={() => {
                setBusquedaInput("");
                setSearchParams({});
              }}
            >
              {t("common.actions.clearFilters")}
            </Boton>
          </div>
        )}
      </section>

      {/* Tabla Densa de Organizaciones */}
      <section aria-label={t("views.bizCustomers.table.regionLabel")}>
        <div className="kc-toolbar-actions" style={{ justifyContent: "flex-end", marginBottom: "0.5rem" }}>
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
        <Tabla
          densidad="alta"
          mostrarTodasColumnas={mostrarTodasColumnas}
          estadoVacio={
            items.length === 0 ? (
              <div data-testid="estado-vacio-clientes" style={{ padding: "2rem", textAlign: "center" }}>
                <p style={{ color: "var(--text)", fontWeight: 600, margin: "0 0 0.5rem 0" }}>
                  {t("views.bizCustomers.empty.title")}
                </p>
                <p style={{ color: "var(--muted)", fontSize: "0.875rem", margin: 0 }}>
                  {t("views.bizCustomers.empty.description")}
                </p>
              </div>
            ) : undefined
          }
        >
          <TablaEncabezado>
            <TablaFila>
              <TablaCeldaEncabezado
                fija
                onClick={() => alternarOrden("tenant_id")}
                style={{ cursor: "pointer", userSelect: "none" }}
                aria-sort={sort.startsWith("tenant_id") ? (sort.endsWith("asc") ? "ascending" : "descending") : "none"}
              >
                {t("views.bizCustomers.table.colTenant")}{iconoOrden("tenant_id")}
              </TablaCeldaEncabezado>

              <TablaCeldaEncabezado
                onClick={() => alternarOrden("nombre")}
                style={{ cursor: "pointer", userSelect: "none" }}
                aria-sort={sort.startsWith("nombre") ? (sort.endsWith("asc") ? "ascending" : "descending") : "none"}
              >
                {t("views.bizCustomers.table.colName")}{iconoOrden("nombre")}
              </TablaCeldaEncabezado>

              <TablaCeldaEncabezado
                onClick={() => alternarOrden("plan")}
                style={{ cursor: "pointer", userSelect: "none" }}
                aria-sort={sort.startsWith("plan") ? (sort.endsWith("asc") ? "ascending" : "descending") : "none"}
              >
                {t("views.bizCustomers.table.colPlan")}{iconoOrden("plan")}
              </TablaCeldaEncabezado>

              <TablaCeldaEncabezado
                onClick={() => alternarOrden("estado")}
                style={{ cursor: "pointer", userSelect: "none" }}
                aria-sort={sort.startsWith("estado") ? (sort.endsWith("asc") ? "ascending" : "descending") : "none"}
              >
                {t("views.bizCustomers.table.colStatus")}{iconoOrden("estado")}
              </TablaCeldaEncabezado>

              <TablaCeldaEncabezado numerico prioridad="baja">
                {t("views.bizCustomers.table.colLines")}
              </TablaCeldaEncabezado>

              <TablaCeldaEncabezado
                numerico
                prioridad="media"
                onClick={() => alternarOrden("consumo")}
                style={{ cursor: "pointer", userSelect: "none" }}
                aria-sort={sort.startsWith("consumo") ? (sort.endsWith("asc") ? "ascending" : "descending") : "none"}
              >
                {t("views.bizCustomers.table.colUsage")}{iconoOrden("consumo")}
              </TablaCeldaEncabezado>

              <TablaCeldaEncabezado
                prioridad="baja"
                onClick={() => alternarOrden("actualizado_en")}
                style={{ cursor: "pointer", userSelect: "none" }}
                aria-sort={sort.startsWith("actualizado_en") ? (sort.endsWith("asc") ? "ascending" : "descending") : "none"}
              >
                {t("views.bizCustomers.table.colLastActivity")}{iconoOrden("actualizado_en")}
              </TablaCeldaEncabezado>

              <TablaCeldaEncabezado prioridad="media">
                {t("views.bizCustomers.table.colPrivacy")}
              </TablaCeldaEncabezado>

              <TablaCeldaEncabezado style={{ textAlign: "right" }}>
                {t("views.bizCustomers.table.colActions")}
              </TablaCeldaEncabezado>
            </TablaFila>
          </TablaEncabezado>

          <TablaCuerpo>
            {items.map((c) => (
              <TablaFila key={c.tenant_id} data-testid={`fila-cliente-${c.tenant_id}`}>
                {/* 1. Tenant ID */}
                <TablaCelda fija>
                  <Link
                    to={`/business/customers/${c.tenant_id}`}
                    style={{
                      fontFamily: "var(--font-mono)",
                      color: "var(--accent)",
                      textDecoration: "none",
                      fontWeight: 600,
                    }}
                    aria-label={t("views.bizCustomers.table.viewDetailsAria", { tenantId: c.tenant_id })}
                  >
                    {c.tenant_id}
                  </Link>
                </TablaCelda>

                {/* 2. Razón Social */}
                <TablaCelda>
                  {c.enmascarado ? (
                    <span
                      data-testid={`razon-enmascarada-${c.tenant_id}`}
                      style={{ color: "var(--muted)", fontStyle: "italic" }}
                      title={t("views.bizCustomers.table.maskedTitle")}
                    >
                      {c.razon_social}
                    </span>
                  ) : (
                    <span
                      data-testid={`razon-clara-${c.tenant_id}`}
                      style={{ color: "var(--text)", fontWeight: 600 }}
                    >
                      {c.razon_social}
                    </span>
                  )}
                  {c.dominio && (
                    <span style={{ display: "block", fontSize: "0.75rem", color: "var(--muted)" }}>
                      {c.dominio}
                    </span>
                  )}
                </TablaCelda>

                {/* 3. Plan */}
                <TablaCelda>
                  <Badge variante={planVariante(c.plan)}>
                    {c.plan}
                  </Badge>
                </TablaCelda>

                {/* 4. Estado */}
                <TablaCelda>
                  <Badge variante={estadoVariante(c.estado)} punto>
                    {c.estado}
                  </Badge>
                </TablaCelda>

                {/* 5. Líneas Contratadas */}
                <TablaCelda numerico prioridad="baja">
                  <span style={{ fontWeight: 600, color: "var(--text)" }}>
                    {formatNumber(c.lineas_contratadas, undefined, lang)}
                  </span>
                  {c.lineas_activas !== undefined && (
                    <span style={{ fontSize: "0.75rem", color: "var(--muted)", marginLeft: "0.25rem" }}>
                      {t("views.bizCustomers.table.activeLines", { count: c.lineas_activas })}
                    </span>
                  )}
                </TablaCelda>

                {/* 6. Consumo Ciclo (LOC, tokens, % cuota) */}
                <TablaCelda numerico prioridad="media">
                  <div>
                    <span style={{ fontWeight: 600, color: "var(--text)" }}>
                      {t("views.bizCustomers.table.locLabel", {
                        count: formatNumber(c.consumo_ciclo.loc, undefined, lang),
                      })}
                    </span>
                  </div>
                  <div style={{ fontSize: "0.75rem", color: "var(--muted)" }}>
                    {t("views.bizCustomers.table.tokensQuota", {
                      tokens: formatTokens(c.consumo_ciclo.tokens, { compact: true, lang }),
                      pct: formatPercent(c.consumo_ciclo.cuota_pct, { decimals: 1, lang }),
                    })}
                  </div>
                </TablaCelda>

                {/* 7. Última Actividad */}
                <TablaCelda prioridad="baja">
                  <time dateTime={c.ultima_actividad} style={{ fontSize: "0.8125rem", color: "var(--muted)" }}>
                    {formatDate(c.ultima_actividad, { year: "numeric", month: "short", day: "numeric" }, lang)}
                  </time>
                </TablaCelda>

                {/* 8. Privacidad / Enmascarado */}
                <TablaCelda prioridad="media">
                  {c.enmascarado ? (
                    <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-start", gap: "4px" }}>
                      <Badge variante="warn" data-testid={`badge-enmascarado-${c.tenant_id}`} punto>
                        {t("common.states.masked")}
                      </Badge>
                      <Boton
                        variante="ghost"
                        tamano="sm"
                        onClick={() => {
                          setTenantSeleccionado({ tenant_id: c.tenant_id, razon_social: c.razon_social });
                          setModalConcesionAbierto(true);
                        }}
                        data-testid={`btn-solicitar-concesion-${c.tenant_id}`}
                        style={{ fontSize: "0.6875rem", padding: "2px 6px" }}
                      >
                        {t("common.actions.requestAccess")}
                      </Boton>
                    </div>
                  ) : (
                    <Badge variante="good" data-testid={`badge-claro-${c.tenant_id}`}>
                      {t("common.states.unmasked")}
                    </Badge>
                  )}
                </TablaCelda>

                {/* 9. Acciones */}
                <TablaCelda style={{ textAlign: "right" }}>
                  <Link
                    to={`/business/customers/${c.tenant_id}`}
                    className="btn btn-secondary btn-sm"
                    style={{ textDecoration: "none", fontSize: "0.75rem" }}
                  >
                    {t("common.actions.view360")}
                  </Link>
                </TablaCelda>
              </TablaFila>
            ))}
          </TablaCuerpo>
        </Tabla>
      </section>

      {/* Barra de Paginación Transversal */}
      <footer
        data-testid="customers-pagination"
        className="kc-pagination"
        style={{
          padding: "0.75rem 1rem",
          backgroundColor: "var(--card)",
          borderRadius: "var(--radius-md)",
          border: "1px solid var(--border)",
        }}
      >
        {/* Recuento de items */}
        <div style={{ fontSize: "0.8125rem", color: "var(--muted)" }}>
          {t("common.pagination.showingRange", { from: inicioRango, to: finRango, total })}
        </div>

        {/* Controles de página y tamaño */}
        <div className="kc-pagination-controls" style={{ gap: "0.75rem" }}>
          {/* Selector de tamaño de página */}
          <div className="kc-pagination-size">
            <Select
              id="filtro-tamano-pagina"
              aria-label={t("common.pagination.recordsPerPage")}
              opciones={opcionesPageSize}
              value={pageSize}
              onChange={(e) => actualizarParams({ page_size: parseInt(e.target.value, 10), page: 1 })}
            />
          </div>

          <span style={{ fontSize: "0.8125rem", color: "var(--muted)" }}>
            {t("common.pagination.pageOf", { page, pages: Math.max(1, pages) })}
          </span>

          {/* Botones de navegación de página */}
          <div style={{ display: "flex", gap: "0.25rem" }}>
            <Boton
              variante="ghost"
              tamano="sm"
              disabled={page <= 1}
              onClick={() => actualizarParams({ page: 1 })}
              aria-label={t("common.pagination.firstPage")}
            >
              «
            </Boton>
            <Boton
              variante="secondary"
              tamano="sm"
              disabled={page <= 1}
              onClick={() => actualizarParams({ page: page - 1 })}
              aria-label={t("common.pagination.previousPage")}
            >
              {t("common.pagination.previous")}
            </Boton>
            <Boton
              variante="secondary"
              tamano="sm"
              disabled={page >= pages}
              onClick={() => actualizarParams({ page: page + 1 })}
              aria-label={t("common.pagination.nextPage")}
            >
              {t("common.pagination.next")}
            </Boton>
            <Boton
              variante="ghost"
              tamano="sm"
              disabled={page >= pages}
              onClick={() => actualizarParams({ page: pages })}
              aria-label={t("common.pagination.lastPage")}
            >
              »
            </Boton>
          </div>
        </div>
      </footer>

      {/* Modal Informativo de Concesión y Revelación */}
      <Modal
        abierto={modalInformativoAbierto}
        alCerrar={() => setModalInformativoAbierto(false)}
        titulo={t("views.bizCustomers.privacyModal.title")}
      >
        <div style={{ display: "flex", flexDirection: "column", gap: "1rem" }}>
          <p style={{ color: "var(--text)", margin: 0, fontSize: "0.875rem" }}>
            {t("views.bizCustomers.privacyModal.intro")}
          </p>
          <div
            style={{
              padding: "0.75rem",
              backgroundColor: "var(--surface)",
              borderRadius: "var(--radius-sm)",
              border: "1px solid var(--border)",
              fontSize: "0.8125rem",
              color: "var(--muted)",
            }}
          >
            <p style={{ margin: "0 0 0.5rem 0", color: "var(--text)", fontWeight: 600 }}>
              {t("views.bizCustomers.privacyModal.conditionsTitle")}
            </p>
            <ul style={{ margin: 0, paddingLeft: "1.25rem" }}>
              <li>{t("views.bizCustomers.privacyModal.cond1")}</li>
              <li>{t("views.bizCustomers.privacyModal.cond2")}</li>
              <li>{t("views.bizCustomers.privacyModal.cond3")}</li>
            </ul>
          </div>
          <div style={{ display: "flex", justifyContent: "flex-end" }}>
            <Boton variante="primary" tamano="sm" onClick={() => setModalInformativoAbierto(false)}>
              {t("common.actions.understood")}
            </Boton>
          </div>
        </div>
      </Modal>

      {/* Modal Canónico de Solicitud de Concesión E6 */}
      <SolicitudConcesionModal
        abierto={modalConcesionAbierto}
        alCerrar={() => setModalConcesionAbierto(false)}
        tenantId={tenantSeleccionado?.tenant_id}
        razonSocial={tenantSeleccionado?.razon_social}
        onConcesionConcedida={() => void refetch()}
      />
    </main>
      )}
    </ContenedorEstado>
  );
};
