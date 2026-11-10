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
import { peticionApi, ApiError } from "../api/clienteApi";
import { useAuth } from "../estado/auth";
import { Boton } from "../componentes/Boton";
import { Badge } from "../componentes/Badge";
import { Select } from "../componentes/Select";
import { Input } from "../componentes/Input";
import { Modal } from "../componentes/Modal";
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

const OPCIONES_PLAN = [
  { valor: "todos", etiqueta: "Todos los planes" },
  { valor: "starter", etiqueta: "Starter" },
  { valor: "growth", etiqueta: "Growth" },
  { valor: "enterprise", etiqueta: "Enterprise" },
];

const OPCIONES_ESTADO = [
  { valor: "todos", etiqueta: "Todos los estados" },
  { valor: "activa", etiqueta: "Activa" },
  { valor: "periodo_gracia", etiqueta: "Periodo de gracia / Moroso" },
  { valor: "suspendida", etiqueta: "Suspendida" },
  { valor: "finalizada", etiqueta: "Finalizada / Baja" },
];

const OPCIONES_PAGE_SIZE = [
  { valor: 10, etiqueta: "10 por pág." },
  { valor: 25, etiqueta: "25 por pág." },
  { valor: 50, etiqueta: "50 por pág." },
  { valor: 100, etiqueta: "100 por pág." },
];

export const BizCustomers: React.FC = () => {
  const { usuario } = useAuth();
  const [searchParams, setSearchParams] = useSearchParams();

  // Control modal de explicación de enmascaramiento / política E6
  const [modalConcesionAbierto, setModalConcesionAbierto] = useState<boolean>(false);

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
          <Badge variante="error">ACCESO DENEGADO</Badge>
          <strong style={{ fontSize: "1.1rem" }}>403 ROL_STAFF_INSUFICIENTE</strong>
        </div>
        <p style={{ color: "var(--muted)", margin: "0.5rem 0" }}>
          Acceso denegado para el rol {usuario?.role}. El directorio de clientes y organizaciones es exclusivo para personal de soporte, negocio y administración.
        </p>
      </main>
    );
  }

  // 2. Estado de Carga Inicial: Skeleton Loading con estructura de tabla
  if (isLoading && !data) {
    return (
      <main
        className="biz-customers-loading"
        data-testid="customers-loading"
        role="status"
        aria-busy="true"
        style={{ display: "flex", flexDirection: "column", gap: "1.5rem" }}
      >
        <span className="sr-only">Cargando directorio de organizaciones cliente...</span>

        {/* Cabecera Esqueleto */}
        <header style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: "1rem" }}>
          <div>
            <div style={{ width: "240px", height: "28px", backgroundColor: "var(--surface2)", borderRadius: "var(--radius-sm)", marginBottom: "0.5rem" }} />
            <div style={{ width: "380px", height: "16px", backgroundColor: "var(--surface)", borderRadius: "var(--radius-sm)" }} />
          </div>
        </header>

        {/* Barra de Filtros Esqueleto */}
        <div style={{ display: "flex", gap: "1rem", padding: "1rem", backgroundColor: "var(--card)", borderRadius: "var(--radius-md)", border: "1px solid var(--border)", flexWrap: "wrap" }}>
          <div style={{ width: "220px", height: "36px", backgroundColor: "var(--surface2)", borderRadius: "var(--radius-sm)" }} />
          <div style={{ width: "180px", height: "36px", backgroundColor: "var(--surface2)", borderRadius: "var(--radius-sm)" }} />
          <div style={{ width: "180px", height: "36px", backgroundColor: "var(--surface2)", borderRadius: "var(--radius-sm)" }} />
        </div>

        {/* Tabla Esqueleto */}
        <div style={{ backgroundColor: "var(--card)", borderRadius: "var(--radius-md)", border: "1px solid var(--border)", padding: "1rem" }}>
          {[1, 2, 3, 4, 5].map((i) => (
            <div
              key={i}
              style={{
                height: "44px",
                display: "flex",
                alignItems: "center",
                gap: "1rem",
                borderBottom: i < 5 ? "1px solid var(--border)" : "none",
              }}
            >
              <div style={{ width: "120px", height: "16px", backgroundColor: "var(--surface2)", borderRadius: "var(--radius-sm)" }} />
              <div style={{ width: "200px", height: "16px", backgroundColor: "var(--surface)", borderRadius: "var(--radius-sm)" }} />
              <div style={{ width: "90px", height: "16px", backgroundColor: "var(--surface2)", borderRadius: "var(--radius-sm)" }} />
              <div style={{ width: "100px", height: "16px", backgroundColor: "var(--surface)", borderRadius: "var(--radius-sm)" }} />
              <div style={{ flex: 1, height: "16px", backgroundColor: "var(--surface2)", borderRadius: "var(--radius-sm)" }} />
            </div>
          ))}
        </div>
      </main>
    );
  }

  // 3. Manejo de Errores Accionable (HTTP 503, HTTP 403, Errores de Red)
  if (error || !data) {
    const apiErr = error instanceof ApiError ? error : null;
    const es503 = apiErr?.status === 503 || apiErr?.codigo === "AGREGADO_NO_DISPONIBLE";
    const es403 = apiErr?.status === 403 || apiErr?.codigo === "ROL_STAFF_INSUFICIENTE";
    const traceId =
      apiErr?.traceId ||
      (apiErr?.detalle as Record<string, unknown>)?.trace_id as string ||
      "trc_customers_error_001";

    return (
      <main
        className="biz-customers-error"
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
          <Badge variante="error">
            {es503 ? "AGREGADOS EN REFRESCO" : es403 ? "ACCESO DENEGADO" : "ERROR"}
          </Badge>
          <strong style={{ fontSize: "1.1rem" }}>
            {es503
              ? "Agregados analíticos en proceso de cálculo"
              : es403
              ? "Permisos insuficientes"
              : "No se pudieron cargar las organizaciones cliente"}
          </strong>
        </div>

        <p style={{ color: "var(--muted)", margin: "0.5rem 0", fontSize: "0.875rem" }}>
          {apiErr?.message || "Ocurrió un error inesperado al consultar el directorio de clientes."}
        </p>

        {/* Visualización explícita del X-Trace-Id */}
        <div
          data-testid="customers-trace-id"
          style={{
            margin: "0.75rem 0",
            fontSize: "0.75rem",
            color: "var(--muted)",
            display: "flex",
            alignItems: "center",
            gap: "0.5rem",
          }}
        >
          <span>X-Trace-Id:</span>
          <code
            style={{
              padding: "0.15rem 0.4rem",
              backgroundColor: "var(--surface)",
              borderRadius: "var(--radius-sm)",
              border: "1px solid var(--border)",
              color: "var(--text)",
            }}
          >
            {traceId}
          </code>
        </div>

        <Boton variante="secondary" tamano="sm" onClick={() => void refetch()}>
          Reintentar consulta
        </Boton>
      </main>
    );
  }

  // Cálculos de paginación
  const total = data.total;
  const items = data.items;
  const pages = data.pages;
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
            Directorio de Clientes y Organizaciones
          </h1>
          <p style={{ fontSize: "0.875rem", color: "var(--muted)", margin: "0.25rem 0 0 0" }}>
            Supervisión cross-tenant de suscripciones, consumo y actividad operativa.
          </p>
        </div>

        <div style={{ display: "flex", alignItems: "center", gap: "0.75rem" }}>
          {data.alguna_enmascarada && (
            <Boton
              variante="ghost"
              tamano="sm"
              onClick={() => setModalConcesionAbierto(true)}
              aria-label="Ver información sobre política de enmascaramiento"
            >
              🔒 Política de Enmascaramiento E6
            </Boton>
          )}
          <Boton
            variante="secondary"
            tamano="sm"
            onClick={() => void refetch()}
            disabled={isFetching}
            aria-label="Refrescar listado de clientes"
          >
            {isFetching ? "Actualizando..." : "Refrescar"}
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
            <Badge variante="warn">ENMASCARADO ACTIVO</Badge>
            <span style={{ fontSize: "0.8125rem", color: "var(--text)" }}>
              Los datos sensibles de clientes están protegidos por defecto bajo la política E6. Para ver en claro se requiere una concesión activa en <code>admin.access_grants</code>.
            </span>
          </div>
          <Boton
            variante="ghost"
            tamano="sm"
            onClick={() => setModalConcesionAbierto(true)}
          >
            Solicitar acceso justificado
          </Boton>
        </div>
      )}

      {/* Barra de Filtros, Búsqueda y Ordenación */}
      <section
        aria-label="Controles de búsqueda y filtros de organizaciones"
        style={{
          display: "flex",
          flexWrap: "wrap",
          alignItems: "flex-end",
          gap: "1rem",
          padding: "1rem",
          backgroundColor: "var(--card)",
          borderRadius: "var(--radius-md)",
          border: "1px solid var(--border)",
        }}
      >
        {/* Búsqueda por texto (q) */}
        <div style={{ flex: "1 1 240px", minWidth: "200px" }}>
          <Input
            id="filtro-busqueda-clientes"
            etiqueta="Buscar por ID u organización"
            placeholder="org_acme, Acme..."
            value={busquedaInput}
            onChange={(e) => setBusquedaInput(e.target.value)}
          />
        </div>

        {/* Filtro por Plan */}
        <div style={{ minWidth: "160px" }}>
          <Select
            id="filtro-plan-clientes"
            etiqueta="Plan comercial"
            opciones={OPCIONES_PLAN}
            value={plan}
            onChange={(e) => actualizarParams({ plan: e.target.value, page: 1 })}
          />
        </div>

        {/* Filtro por Estado */}
        <div style={{ minWidth: "180px" }}>
          <Select
            id="filtro-estado-clientes"
            etiqueta="Estado"
            opciones={OPCIONES_ESTADO}
            value={estado}
            onChange={(e) => actualizarParams({ estado: e.target.value, page: 1 })}
          />
        </div>

        {/* Botón para restablecer filtros si hay alguno activo */}
        {(plan !== "todos" || estado !== "todos" || urlQ !== "" || sort !== "") && (
          <div style={{ alignSelf: "flex-end" }}>
            <Boton
              variante="ghost"
              tamano="sm"
              onClick={() => {
                setBusquedaInput("");
                setSearchParams({});
              }}
            >
              Limpiar filtros
            </Boton>
          </div>
        )}
      </section>

      {/* Tabla Densa de Organizaciones */}
      <section aria-label="Listado de organizaciones cliente">
        <Tabla
          densidad="alta"
          estadoVacio={
            items.length === 0 ? (
              <div data-testid="estado-vacio-clientes" style={{ padding: "2rem", textAlign: "center" }}>
                <p style={{ color: "var(--text)", fontWeight: 600, margin: "0 0 0.5rem 0" }}>
                  No se encontraron organizaciones
                </p>
                <p style={{ color: "var(--muted)", fontSize: "0.875rem", margin: 0 }}>
                  Prueba a ajustar los criterios de búsqueda o filtros seleccionados.
                </p>
              </div>
            ) : undefined
          }
        >
          <TablaEncabezado>
            <TablaFila>
              <TablaCeldaEncabezado
                onClick={() => alternarOrden("tenant_id")}
                style={{ cursor: "pointer", userSelect: "none" }}
                aria-sort={sort.startsWith("tenant_id") ? (sort.endsWith("asc") ? "ascending" : "descending") : "none"}
              >
                Tenant ID{iconoOrden("tenant_id")}
              </TablaCeldaEncabezado>

              <TablaCeldaEncabezado
                onClick={() => alternarOrden("nombre")}
                style={{ cursor: "pointer", userSelect: "none" }}
                aria-sort={sort.startsWith("nombre") ? (sort.endsWith("asc") ? "ascending" : "descending") : "none"}
              >
                Razón Social{iconoOrden("nombre")}
              </TablaCeldaEncabezado>

              <TablaCeldaEncabezado
                onClick={() => alternarOrden("plan")}
                style={{ cursor: "pointer", userSelect: "none" }}
                aria-sort={sort.startsWith("plan") ? (sort.endsWith("asc") ? "ascending" : "descending") : "none"}
              >
                Plan{iconoOrden("plan")}
              </TablaCeldaEncabezado>

              <TablaCeldaEncabezado
                onClick={() => alternarOrden("estado")}
                style={{ cursor: "pointer", userSelect: "none" }}
                aria-sort={sort.startsWith("estado") ? (sort.endsWith("asc") ? "ascending" : "descending") : "none"}
              >
                Estado{iconoOrden("estado")}
              </TablaCeldaEncabezado>

              <TablaCeldaEncabezado numerico>
                Líneas
              </TablaCeldaEncabezado>

              <TablaCeldaEncabezado
                numerico
                onClick={() => alternarOrden("consumo")}
                style={{ cursor: "pointer", userSelect: "none" }}
                aria-sort={sort.startsWith("consumo") ? (sort.endsWith("asc") ? "ascending" : "descending") : "none"}
              >
                Consumo (Ciclo){iconoOrden("consumo")}
              </TablaCeldaEncabezado>

              <TablaCeldaEncabezado
                onClick={() => alternarOrden("actualizado_en")}
                style={{ cursor: "pointer", userSelect: "none" }}
                aria-sort={sort.startsWith("actualizado_en") ? (sort.endsWith("asc") ? "ascending" : "descending") : "none"}
              >
                Última Actividad{iconoOrden("actualizado_en")}
              </TablaCeldaEncabezado>

              <TablaCeldaEncabezado>
                Privacidad
              </TablaCeldaEncabezado>

              <TablaCeldaEncabezado style={{ textAlign: "right" }}>
                Acciones
              </TablaCeldaEncabezado>
            </TablaFila>
          </TablaEncabezado>

          <TablaCuerpo>
            {items.map((c) => (
              <TablaFila key={c.tenant_id} data-testid={`fila-cliente-${c.tenant_id}`}>
                {/* 1. Tenant ID */}
                <TablaCelda>
                  <Link
                    to={`/business/customers/${c.tenant_id}`}
                    style={{
                      fontFamily: "var(--font-mono)",
                      color: "var(--accent)",
                      textDecoration: "none",
                      fontWeight: 600,
                    }}
                    aria-label={`Ver detalles de ${c.tenant_id}`}
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
                      title="Dato enmascarado por política de privacidad E6"
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
                <TablaCelda numerico>
                  <span style={{ fontWeight: 600, color: "var(--text)" }}>
                    {c.lineas_contratadas}
                  </span>
                  {c.lineas_activas !== undefined && (
                    <span style={{ fontSize: "0.75rem", color: "var(--muted)", marginLeft: "0.25rem" }}>
                      ({c.lineas_activas} act.)
                    </span>
                  )}
                </TablaCelda>

                {/* 6. Consumo Ciclo (LOC, tokens, % cuota) */}
                <TablaCelda numerico>
                  <div>
                    <span style={{ fontWeight: 600, color: "var(--text)" }}>
                      {c.consumo_ciclo.loc.toLocaleString("es-ES")} LOC
                    </span>
                  </div>
                  <div style={{ fontSize: "0.75rem", color: "var(--muted)" }}>
                    {(c.consumo_ciclo.tokens / 1000000).toFixed(1)}M tok ({c.consumo_ciclo.cuota_pct}%)
                  </div>
                </TablaCelda>

                {/* 7. Última Actividad */}
                <TablaCelda>
                  <time dateTime={c.ultima_actividad} style={{ fontSize: "0.8125rem", color: "var(--muted)" }}>
                    {new Date(c.ultima_actividad).toLocaleDateString("es-ES", {
                      year: "numeric",
                      month: "short",
                      day: "numeric",
                    })}
                  </time>
                </TablaCelda>

                {/* 8. Privacidad / Enmascarado */}
                <TablaCelda>
                  {c.enmascarado ? (
                    <Badge variante="warn" data-testid={`badge-enmascarado-${c.tenant_id}`} punto>
                      ENMASCARADO
                    </Badge>
                  ) : (
                    <Badge variante="good" data-testid={`badge-claro-${c.tenant_id}`}>
                      EN CLARO
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
                    Ver 360°
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
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          flexWrap: "wrap",
          gap: "1rem",
          padding: "0.75rem 1rem",
          backgroundColor: "var(--card)",
          borderRadius: "var(--radius-md)",
          border: "1px solid var(--border)",
        }}
      >
        {/* Recuento de items */}
        <div style={{ fontSize: "0.8125rem", color: "var(--muted)" }}>
          Mostrando <strong style={{ color: "var(--text)" }}>{inicioRango}</strong> a{" "}
          <strong style={{ color: "var(--text)" }}>{finRango}</strong> de{" "}
          <strong style={{ color: "var(--text)" }}>{total}</strong> organizaciones
        </div>

        {/* Controles de página y tamaño */}
        <div style={{ display: "flex", alignItems: "center", gap: "1rem", flexWrap: "wrap" }}>
          {/* Selector de tamaño de página */}
          <div style={{ minWidth: "120px" }}>
            <Select
              id="filtro-tamano-pagina"
              aria-label="Registros por página"
              opciones={OPCIONES_PAGE_SIZE}
              value={pageSize}
              onChange={(e) => actualizarParams({ page_size: parseInt(e.target.value, 10), page: 1 })}
            />
          </div>

          <span style={{ fontSize: "0.8125rem", color: "var(--muted)" }}>
            Página <strong style={{ color: "var(--text)" }}>{page}</strong> de{" "}
            <strong style={{ color: "var(--text)" }}>{Math.max(1, pages)}</strong>
          </span>

          {/* Botones de navegación de página */}
          <div style={{ display: "flex", gap: "0.25rem" }}>
            <Boton
              variante="ghost"
              tamano="sm"
              disabled={page <= 1}
              onClick={() => actualizarParams({ page: 1 })}
              aria-label="Primera página"
            >
              «
            </Boton>
            <Boton
              variante="secondary"
              tamano="sm"
              disabled={page <= 1}
              onClick={() => actualizarParams({ page: page - 1 })}
              aria-label="Página anterior"
            >
              Anterior
            </Boton>
            <Boton
              variante="secondary"
              tamano="sm"
              disabled={page >= pages}
              onClick={() => actualizarParams({ page: page + 1 })}
              aria-label="Página siguiente"
            >
              Siguiente
            </Boton>
            <Boton
              variante="ghost"
              tamano="sm"
              disabled={page >= pages}
              onClick={() => actualizarParams({ page: pages })}
              aria-label="Última página"
            >
              »
            </Boton>
          </div>
        </div>
      </footer>

      {/* Modal Informativo de Concesión y Revelación E6 */}
      <Modal
        abierto={modalConcesionAbierto}
        alCerrar={() => setModalConcesionAbierto(false)}
        titulo="Política de Privacidad y Acceso Justificado (E6)"
      >
        <div style={{ display: "flex", flexDirection: "column", gap: "1rem" }}>
          <p style={{ color: "var(--text)", margin: 0, fontSize: "0.875rem" }}>
            Bajo las directivas de seguridad del Equipo E6 de KalliCode, la razón social, correos y datos sensibles de clientes se muestran <strong>enmascarados por defecto</strong> para todo el personal.
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
              Condiciones para revelación en claro:
            </p>
            <ul style={{ margin: 0, paddingLeft: "1.25rem" }}>
              <li>Debe existir una concesión activa en <code>admin.access_grants</code> autorizada con justificación operativa.</li>
              <li>Toda consulta sobre datos revelados se registra en la auditoría inmutable <code>admin.staff_actions</code>.</li>
              <li>Las concesiones son temporales y expiran automáticamente tras su ventana de validez.</li>
            </ul>
          </div>
          <div style={{ display: "flex", justifyContent: "flex-end" }}>
            <Boton variante="primary" tamano="sm" onClick={() => setModalConcesionAbierto(false)}>
              Entendido
            </Boton>
          </div>
        </div>
      </Modal>
    </main>
  );
};
