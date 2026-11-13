/**
 * msw_handlers.ts — Dobles de API con Mock Service Worker (MSW v2)
 *
 * Emula fielmente los endpoints comerciales y de negocio de /admin/v1 a partir
 * del contrato OpenAPI congelado (docs/openapi-admin-v1.yaml), permitiendo pruebas
 * frontend y desarrollo local desacoplados del backend FastAPI.
 */

import { http, HttpResponse } from "msw";

export interface MockConfig {
  concesionActiva: boolean;
  estadoAgregados: "ok" | "obsoleto" | "fallido";
  rolStaff: "staff_admin" | "staff_negocio" | "staff_soporte" | "staff_operaciones";
  frescuraCustom: string | null;
  telemetriaEstado: "normal" | "sin-trabajo" | "sin-telemetria" | "desactualizada";
}

const configDefecto: MockConfig = {
  concesionActiva: false,
  estadoAgregados: "ok",
  rolStaff: "staff_negocio",
  frescuraCustom: null,
  telemetriaEstado: "normal",
};

let estadoGlobal: MockConfig = { ...configDefecto };
const CLAVE_CONCESIONES_MOCK = "kc_mock_concesiones_tenants";
const concesionesPorTenant = new Set<string>();

function obtenerConcesionesPersistidas(): Set<string> {
  const conjunto = new Set(concesionesPorTenant);
  try {
    if (typeof window !== "undefined" && window.localStorage) {
      const raw = window.localStorage.getItem(CLAVE_CONCESIONES_MOCK);
      if (raw) {
        const arr = JSON.parse(raw);
        if (Array.isArray(arr)) {
          arr.forEach((id) => conjunto.add(String(id)));
        }
      }
    }
  } catch {
    // ignorar
  }
  return conjunto;
}

function persistirConcesionTenant(tenantId: string): void {
  concesionesPorTenant.add(tenantId);
  try {
    if (typeof window !== "undefined" && window.localStorage) {
      const actual = obtenerConcesionesPersistidas();
      actual.add(tenantId);
      window.localStorage.setItem(CLAVE_CONCESIONES_MOCK, JSON.stringify(Array.from(actual)));
    }
  } catch {
    // ignorar
  }
}

function limpiarTodasConcesiones(): void {
  concesionesPorTenant.clear();
  try {
    if (typeof window !== "undefined" && window.localStorage) {
      window.localStorage.removeItem(CLAVE_CONCESIONES_MOCK);
    }
  } catch {
    // ignorar
  }
}

/** Modifica dinámicamente si existe concesión activa de acceso simulada (global para tests). */
export function setMockConcesionActiva(activa: boolean): void {
  estadoGlobal.concesionActiva = activa;
}

/** Añade una concesión simulada para un tenant específico. */
export function setMockConcesionTenant(tenantId: string): void {
  persistirConcesionTenant(tenantId);
}

/** Limpia las concesiones por tenant simuladas. */
export function limpiarMockConcesionesTenants(): void {
  limpiarTodasConcesiones();
}

/** Modifica dinámicamente el estado de frescura de los agregados. */
export function setMockEstadoAgregados(estado: "ok" | "obsoleto" | "fallido"): void {
  estadoGlobal.estadoAgregados = estado;
}

/** Configura una fecha ISO personalizada para simular agregados obsoletos o recientes. */
export function setMockFrescura(fechaIso: string | null): void {
  estadoGlobal.frescuraCustom = fechaIso;
}

/** Modifica dinámicamente el estado de la telemetría del pipeline. */
export function setMockTelemetriaEstado(
  estado: "normal" | "sin-trabajo" | "sin-telemetria" | "desactualizada"
): void {
  estadoGlobal.telemetriaEstado = estado;
}

/** Modifica dinámicamente el rol del staff simulado. */
export function setMockRolStaff(
  rol: "staff_admin" | "staff_negocio" | "staff_soporte" | "staff_operaciones"
): void {
  estadoGlobal.rolStaff = rol;
}

/** Restablece la configuración de los mocks a sus valores por defecto. */
export function resetMockState(): void {
  estadoGlobal = { ...configDefecto };
  limpiarTodasConcesiones();
}

// ------------------------------------------------------------------ Clientes mock
interface ClienteMock {
  tenant_id: string;
  razon_social: string;
  dominio: string;
  plan: string;
  estado: string;
  lineas_contratadas: number;
  lineas_activas: number;
  alta_el: string;
  usuarios_activos: number;
  tickets_abiertos: number;
  ultima_actividad: string;
  mrr_eur: number;
  consumo_ciclo: {
    loc: number;
    tokens: number;
    cuota_pct: number;
  };
}

const CLIENTES_MOCK: ClienteMock[] = [
  {
    tenant_id: "org_acme",
    razon_social: "Acme Logística S.L.",
    dominio: "acme.com",
    plan: "growth",
    estado: "activa",
    lineas_contratadas: 10,
    lineas_activas: 8,
    alta_el: "2026-01-15T08:00:00Z",
    usuarios_activos: 25,
    tickets_abiertos: 2,
    ultima_actividad: "2026-10-30T10:00:00Z",
    mrr_eur: 1200.0,
    consumo_ciclo: { loc: 15000, tokens: 4500000, cuota_pct: 75.0 },
  },
  {
    tenant_id: "org_globex",
    razon_social: "Globex Industrial S.A.",
    dominio: "globex.com",
    plan: "enterprise",
    estado: "activa",
    lineas_contratadas: 30,
    lineas_activas: 28,
    alta_el: "2025-11-20T09:30:00Z",
    usuarios_activos: 110,
    tickets_abiertos: 5,
    ultima_actividad: "2026-10-30T12:15:00Z",
    mrr_eur: 4500.0,
    consumo_ciclo: { loc: 85000, tokens: 28000000, cuota_pct: 92.5 },
  },
  {
    tenant_id: "org_initech",
    razon_social: "Initech Software Corporation",
    dominio: "initech.com",
    plan: "starter",
    estado: "periodo_gracia",
    lineas_contratadas: 3,
    lineas_activas: 2,
    alta_el: "2026-03-10T14:00:00Z",
    usuarios_activos: 8,
    tickets_abiertos: 1,
    ultima_actividad: "2026-10-29T16:45:00Z",
    mrr_eur: 350.0,
    consumo_ciclo: { loc: 2500, tokens: 750000, cuota_pct: 35.0 },
  },
  {
    tenant_id: "org_wayne",
    razon_social: "Wayne Enterprises Inc.",
    dominio: "wayne.com",
    plan: "enterprise",
    estado: "activa",
    lineas_contratadas: 50,
    lineas_activas: 48,
    alta_el: "2025-08-01T11:00:00Z",
    usuarios_activos: 250,
    tickets_abiertos: 0,
    ultima_actividad: "2026-10-30T13:00:00Z",
    mrr_eur: 8900.0,
    consumo_ciclo: { loc: 140000, tokens: 49000000, cuota_pct: 68.0 },
  },
  {
    tenant_id: "org_umbrella",
    razon_social: "Umbrella BioTech SL",
    dominio: "umbrella.com",
    plan: "starter",
    estado: "suspendida",
    lineas_contratadas: 5,
    lineas_activas: 0,
    alta_el: "2026-02-14T10:00:00Z",
    usuarios_activos: 0,
    tickets_abiertos: 4,
    ultima_actividad: "2026-10-15T09:00:00Z",
    mrr_eur: 0.0,
    consumo_ciclo: { loc: 0, tokens: 0, cuota_pct: 0.0 },
  },
];

// Helper para determinar si aplica concesión activa
function tieneConcesion(request: Request, url: URL, tenantId?: string): boolean {
  if (
    request.headers.get("x-mock-grant") === "true" ||
    request.headers.get("x-mock-concesion") === "true" ||
    url.searchParams.get("mock_grant") === "true" ||
    estadoGlobal.concesionActiva
  ) {
    return true;
  }
  if (tenantId) {
    if (concesionesPorTenant.has(tenantId)) return true;
    const persistidas = obtenerConcesionesPersistidas();
    if (persistidas.has(tenantId)) return true;
  }
  return false;
}

// Helper para determinar el rol activo
function obtenerRol(request: Request): string {
  const headerRole = request.headers.get("x-mock-role");
  if (headerRole) return headerRole;
  const auth = request.headers.get("authorization");
  if (auth && auth.startsWith("Bearer mock_jwt_")) {
    const rolePart = auth.replace("Bearer mock_jwt_", "").trim();
    if (["staff_admin", "staff_negocio", "staff_soporte", "staff_operaciones"].includes(rolePart)) {
      return rolePart;
    }
  }
  return estadoGlobal.rolStaff;
}

// Helper para simular error 401
function verificarAutenticacion(request: Request): Response | null {
  const auth = request.headers.get("authorization");
  const force401 = request.headers.get("x-mock-status") === "401";
  if (force401 || (auth !== null && auth.includes("token_invalido"))) {
    return HttpResponse.json(
      {
        error: {
          codigo: "TOKEN_INVALIDO",
          code: "token_invalido",
          mensaje: "Token de acceso no válido o firma expirada.",
        },
      },
      { status: 401 }
    );
  }
  return null;
}

// Helper para simular error 503 por frescura de agregados
function verificarFrescuraAgregados(request: Request): Response | null {
  const force503 = request.headers.get("x-mock-status") === "503";
  if (force503 || estadoGlobal.estadoAgregados !== "ok") {
    const traceId = request.headers.get("x-trace-id") || "trc_503_frescura_001";
    return HttpResponse.json(
      {
        error: {
          codigo: "AGREGADO_NO_DISPONIBLE",
          code: "agregado_no_disponible",
          mensaje:
            "La capa de agregados analíticos está en refresco o no ha completado el ciclo.",
          detalle: { estado: estadoGlobal.estadoAgregados },
          trace_id: traceId,
        },
      },
      {
        status: 503,
        headers: {
          "x-trace-id": traceId,
        },
      }
    );
  }
  return null;
}

let sesionLoginPendiente: { email: string; rol: string } = {
  email: "admin@kallicode.com",
  rol: "staff_admin",
};

// ------------------------------------------------------------------ Handlers MSW
export const handlers = [
  // 0. Autenticación y 2FA/TOTP para modo interactivo en navegador
  http.post("*/admin/v1/auth/login", async ({ request }) => {
    let body: Record<string, unknown> = {};
    try {
      body = (await request.json()) as Record<string, unknown>;
    } catch {
      // Ignorar error de parsing si viene vacío
    }
    const email = String(body.email || "admin@kallicode.com");
    let rol: "staff_admin" | "staff_negocio" | "staff_soporte" | "staff_operaciones" = "staff_admin";
    if (email.includes("soporte")) {
      rol = "staff_soporte";
    } else if (email.includes("operaciones")) {
      rol = "staff_operaciones";
    } else if (email.includes("negocio")) {
      rol = "staff_negocio";
    }
    sesionLoginPendiente = { email, rol };
    return HttpResponse.json({
      mfa_token: `mfa_token_mock_${Date.now()}`,
      mfa_inscrito: true,
      expira_en: 300,
    });
  }),

  http.post("*/admin/v1/auth/mfa/verify", async () => {
    estadoGlobal.rolStaff = sesionLoginPendiente.rol as
      | "staff_admin"
      | "staff_negocio"
      | "staff_soporte"
      | "staff_operaciones";
    return HttpResponse.json({
      access_token: `mock_jwt_${sesionLoginPendiente.rol}`,
      refresh_token: "mock_refresh_token_jwt",
      staff: {
        id: "st_dev_01",
        nombre: `Personal (${sesionLoginPendiente.rol})`,
        rol: sesionLoginPendiente.rol,
      },
      expira_en: 3600,
    });
  }),

  http.post("*/admin/v1/auth/logout", () => {
    limpiarTodasConcesiones();
    return HttpResponse.json({ ok: true });
  }),

  http.post("*/admin/v1/auth/refresh", () => {
    return HttpResponse.json({
      access_token: `mock_jwt_${estadoGlobal.rolStaff}`,
      refresh_token: "mock_refresh_token_jwt",
      expira_en: 3600,
    });
  }),

  // 1. GET /admin/v1/business/summary
  http.get("*/admin/v1/business/summary", ({ request }) => {
    const errAuth = verificarAutenticacion(request);
    if (errAuth) return errAuth;

    const errFrescura = verificarFrescuraAgregados(request);
    if (errFrescura) return errFrescura;

    const rol = obtenerRol(request);
    if (rol === "staff_operaciones" || rol === "staff_soporte") {
      return HttpResponse.json(
        {
          error: {
            codigo: "ROL_STAFF_INSUFICIENTE",
            code: "rol_staff_insuficiente",
            mensaje: "Acceso exclusivo para roles de negocio o administración.",
          },
        },
        { status: 403 }
      );
    }

    return HttpResponse.json({
      mrr_eur: 45000.0,
      clientes_activos: 128,
      consumo_tokens_ciclo: {
        total: 125000000,
        flash: 80000000,
        pro: 35000000,
        fable: 10000000,
      },
      tendencia: {
        mrr_pct: 12.5,
        clientes_pct: 8.3,
        consumo_pct: 15.2,
      },
      frescura: "2026-10-30T14:00:00.000Z",
    });
  }),

  // 2. GET /admin/v1/business/overview
  http.get("*/admin/v1/business/overview", ({ request }) => {
    const errAuth = verificarAutenticacion(request);
    if (errAuth) return errAuth;

    const errFrescura = verificarFrescuraAgregados(request);
    if (errFrescura) return errFrescura;

    const rol = obtenerRol(request);
    if (rol === "staff_operaciones" || rol === "staff_soporte") {
      const traceId = request.headers.get("x-trace-id") || "trc_403_rol";
      return HttpResponse.json(
        {
          error: {
            codigo: "ROL_STAFF_INSUFICIENTE",
            code: "rol_staff_insuficiente",
            mensaje: `Acceso denegado para el rol ${rol}.`,
            trace_id: traceId,
          },
        },
        {
          status: 403,
          headers: { "x-trace-id": traceId },
        }
      );
    }

    const url = new URL(request.url);
    const periodo = url.searchParams.get("periodo") || "mes_actual";
    const compararCon = url.searchParams.get("comparar_con") || "periodo_anterior";

    // Permitir configurar frescura explícita vía estadoGlobal, header o query param
    const frescura =
      request.headers.get("x-mock-frescura") ||
      url.searchParams.get("frescura") ||
      estadoGlobal.frescuraCustom ||
      "2026-10-30T14:00:00.000Z";

    const traceId = request.headers.get("x-trace-id") || "trc_overview_ok_001";

    let mrr = 45000.0;
    let clientesActivos = 128;
    let tokens = 125000000;
    let tickets = 450;
    let variacionPct = 12.5;

    if (periodo === "mes_anterior") {
      mrr = 42000.0;
      clientesActivos = 120;
      tokens = 110000000;
      tickets = 410;
      variacionPct = 8.2;
    } else if (periodo === "trimestre") {
      mrr = 135000.0;
      clientesActivos = 135;
      tokens = 380000000;
      tickets = 1320;
      variacionPct = 18.0;
    } else if (periodo === "ano") {
      mrr = 520000.0;
      clientesActivos = 150;
      tokens = 1400000000;
      tickets = 5100;
      variacionPct = 25.4;
    }

    return HttpResponse.json(
      {
        periodo: {
          inicio: "2026-10-01",
          fin: "2026-10-31",
          tipo: periodo,
          comparar_con: compararCon,
        },
        frescura,
        variacion_pct: variacionPct,
        clientes: {
          activos: clientesActivos,
          nuevos: 14,
          altas: 14,
          perdidos: 2,
          por_plan: {
            starter: 40,
            growth: 65,
            enterprise: 23,
          },
        },
        ingresos: {
          importe: mrr,
          moneda: "EUR",
        },
        ingreso_recurrente: {
          importe: mrr,
          moneda: "EUR",
        },
        mrr_eur: mrr,
        consumo: {
          loc: 320000,
          tokens,
          coste_estimado: Math.round(tokens / 100000) * 1.0,
        },
        pipeline: {
          tickets_entregados: tickets,
          tiempo_e2e_p50_h: 2.4,
          escalado_humano_pct: 4.5,
        },
        tendencia: {
          mrr: variacionPct,
          consumo: 15.2,
          pipeline: 8.5,
        },
      },
      {
        headers: {
          "x-trace-id": traceId,
        },
      }
    );
  }),

  // 3. GET /admin/v1/business/customers
  http.get("*/admin/v1/business/customers", ({ request }) => {
    const errAuth = verificarAutenticacion(request);
    if (errAuth) return errAuth;

    const errFrescura = verificarFrescuraAgregados(request);
    if (errFrescura) return errFrescura;

    const rol = obtenerRol(request);
    if (rol === "staff_operaciones") {
      return HttpResponse.json(
        {
          error: {
            codigo: "ROL_STAFF_INSUFICIENTE",
            code: "rol_staff_insuficiente",
            mensaje: "staff_operaciones no tiene privilegios sobre el directorio de clientes.",
          },
        },
        { status: 403 }
      );
    }

    const url = new URL(request.url);
    const plan = url.searchParams.get("plan");
    const estado = url.searchParams.get("estado");
    const q = url.searchParams.get("q");
    const sort = url.searchParams.get("sort");
    const page = Math.max(1, parseInt(url.searchParams.get("page") || "1", 10));
    const pageSize = Math.min(
      100,
      Math.max(1, parseInt(url.searchParams.get("page_size") || "25", 10))
    );

    // Búsqueda por nombre requiere concesión activa si no es por org_...
    const conConcesionGlobal = tieneConcesion(request, url);
    const busquedaPorNombre = Boolean(q && !q.startsWith("org_"));
    if (busquedaPorNombre && !conConcesionGlobal && obtenerConcesionesPersistidas().size === 0) {
      return HttpResponse.json(
        {
          error: {
            codigo: "ACCESO_NO_JUSTIFICADO",
            code: "acceso_no_justificado",
            mensaje: "La búsqueda de clientes por nombre exige una concesión activa.",
          },
        },
        { status: 403 }
      );
    }

    let filtrados = [...CLIENTES_MOCK];
    if (plan) {
      filtrados = filtrados.filter((c) => c.plan.toLowerCase() === plan.toLowerCase());
    }
    if (estado) {
      filtrados = filtrados.filter((c) => c.estado.toLowerCase().startsWith(estado.toLowerCase()));
    }
    if (q) {
      const qLower = q.toLowerCase();
      filtrados = filtrados.filter(
        (c) =>
          c.tenant_id.toLowerCase().includes(qLower) ||
          c.razon_social.toLowerCase().includes(qLower)
      );
    }

    // Ordenación
    if (sort) {
      const [campo, direccion] = sort.split("-");
      const mult = direccion === "desc" ? -1 : 1;
      filtrados.sort((a, b) => {
        if (campo === "mrr_eur") return (a.mrr_eur - b.mrr_eur) * mult;
        if (campo === "tenant_id") return a.tenant_id.localeCompare(b.tenant_id) * mult;
        if (campo === "nombre" || campo === "razon_social") return a.razon_social.localeCompare(b.razon_social) * mult;
        if (campo === "plan") return a.plan.localeCompare(b.plan) * mult;
        if (campo === "estado") return a.estado.localeCompare(b.estado) * mult;
        if (campo === "consumo") return (a.consumo_ciclo.loc - b.consumo_ciclo.loc) * mult;
        if (campo === "alta" || campo === "creado_en") return a.alta_el.localeCompare(b.alta_el) * mult;
        if (campo === "actualizado_en") return a.ultima_actividad.localeCompare(b.ultima_actividad) * mult;
        return 0;
      });
    }

    const total = filtrados.length;
    const offset = (page - 1) * pageSize;
    const paginados = filtrados.slice(offset, offset + pageSize);

    // Mapeo de enmascaramiento según concesión por tenant
    const items = paginados.map((c) => {
      const masked = !tieneConcesion(request, url, c.tenant_id);
      return {
        tenant_id: c.tenant_id,
        razon_social: masked ? "A•••• S.L." : c.razon_social,
        dominio: masked ? "a••••.com" : c.dominio,
        plan: c.plan,
        estado: c.estado,
        lineas_contratadas: c.lineas_contratadas,
        lineas_activas: c.lineas_activas,
        alta_el: c.alta_el,
        usuarios_activos: c.usuarios_activos,
        tickets_abiertos: c.tickets_abiertos,
        ultima_actividad: c.ultima_actividad,
        consumo_ciclo: c.consumo_ciclo,
        mrr_eur: c.mrr_eur,
        enmascarado: masked,
      };
    });

    const pages = pageSize > 0 ? Math.ceil(total / pageSize) : 0;
    const traceId = request.headers.get("x-trace-id") || "trc_customers_list_001";

    return HttpResponse.json(
      {
        items,
        total,
        page,
        page_size: pageSize,
        pages,
        frescura: "2026-10-30T14:00:00.000Z",
        alguna_enmascarada: items.some((i) => i.enmascarado),
      },
      {
        headers: {
          "x-trace-id": traceId,
        },
      }
    );
  }),

  // 4. GET /admin/v1/business/customers/:tenant_id
  http.get("*/admin/v1/business/customers/:tenant_id", ({ params, request }) => {
    const errAuth = verificarAutenticacion(request);
    if (errAuth) return errAuth;

    const errFrescura = verificarFrescuraAgregados(request);
    if (errFrescura) return errFrescura;

    const rol = obtenerRol(request);
    if (rol === "staff_operaciones") {
      return HttpResponse.json(
        {
          error: {
            codigo: "ROL_STAFF_INSUFICIENTE",
            code: "rol_staff_insuficiente",
            mensaje: "staff_operaciones no puede consultar la ficha 360 del cliente.",
          },
        },
        { status: 403 }
      );
    }

    const { tenant_id } = params;
    if (tenant_id === "org_desconocida" || tenant_id === "org_inexistente") {
      return HttpResponse.json(
        {
          error: {
            codigo: "NO_ENCONTRADO",
            code: "no_encontrado",
            mensaje: `Organización ${tenant_id} no encontrada.`,
          },
        },
        { status: 404 }
      );
    }

    const cliente = CLIENTES_MOCK.find((c) => c.tenant_id === tenant_id) || CLIENTES_MOCK[0];
    const url = new URL(request.url);
    const conConcesion = tieneConcesion(request, url, cliente.tenant_id);

    const razonSocial = conConcesion ? cliente.razon_social : "A•••• S.L.";
    const dominio = conConcesion ? cliente.dominio : "a••••.com";
    const enmascarados = conConcesion ? [] : ["identificacion", "usuarios", "integraciones"];
    const traceId = request.headers.get("x-trace-id") || "trc_cust_detail_001";

    return HttpResponse.json(
      {
        tenant_id: cliente.tenant_id,
        razon_social: razonSocial,
        dominio,
        frescura: "2026-10-30T14:00:00.000Z",
        enmascarado: enmascarados,
        identificacion: {
          tenant_id: cliente.tenant_id,
          razon_social: razonSocial,
          dominio,
          despliegue: "cloud",
          idioma: "es",
          alta_el: cliente.alta_el,
        },
        suscripcion: {
          plan_codigo: cliente.plan,
          plan_nombre: `Plan ${cliente.plan.toUpperCase()}`,
          estado: cliente.estado,
          inicia_el: "2026-01-15",
          renueva_el: "2027-01-15",
          finaliza_el: null,
          importe_mes: cliente.mrr_eur,
          moneda: "EUR",
          solicitudes_pendientes: ["Cambio a plan Enterprise en revisión"],
        },
        lineas: {
          contratadas: cliente.lineas_contratadas,
          activas: cliente.lineas_activas,
          utilizacion_media_pct: 80.0,
          loc_mes: 20000,
        },
        actividad: {
          cobertura_pct: 88.5,
          nodos: 1420,
          aristas: 3850,
          rendimiento_e2e_horas: 3.4,
          usuarios_activos: cliente.usuarios_activos,
          usuarios_total: cliente.usuarios_activos + 5,
          integraciones: 4,
          docs_onboarding: 8,
          tickets_abiertos: cliente.tickets_abiertos,
          ultima_actividad: cliente.ultima_actividad,
        },
        grafo_actividad: {
          cobertura_pct: 88.5,
          nodos: 1420,
          aristas: 3850,
          rendimiento_e2e_horas: 3.4,
        },
        consumo: {
          loc_consumidas: cliente.consumo_ciclo.loc,
          cuota_pct: cliente.consumo_ciclo.cuota_pct,
          tokens_in: 3000000,
          tokens_out: 1500000,
          tokens_total: 4500000,
          coste: 45.5,
          historico: [
            { ciclo: "2026-05", loc: 12000, tokens: 3800000, cuota_pct: 60.0 },
            { ciclo: "2026-06", loc: 13500, tokens: 4100000, cuota_pct: 67.5 },
            { ciclo: "2026-07", loc: 14000, tokens: 4200000, cuota_pct: 70.0 },
            { ciclo: "2026-08", loc: 14200, tokens: 4300000, cuota_pct: 71.0 },
            { ciclo: "2026-09", loc: 14800, tokens: 4400000, cuota_pct: 74.0 },
            {
              ciclo: "2026-10",
              loc: cliente.consumo_ciclo.loc,
              tokens: cliente.consumo_ciclo.tokens,
              cuota_pct: cliente.consumo_ciclo.cuota_pct,
            },
          ],
        },
        usuarios: [
          {
            id: "usr_01",
            nombre: conConcesion ? "Juan Pérez" : "J•••• P••••",
            email: conConcesion ? "admin@acme.com" : "u••••@acme.com",
            rol: "owner",
            idioma: "es",
            estado: "activo",
          },
          {
            id: "usr_02",
            nombre: conConcesion ? "Ana Gómez" : "A•••• G••••",
            email: conConcesion ? "ana.gomez@acme.com" : "a••••@acme.com",
            rol: "developer",
            idioma: "en",
            estado: "activo",
          },
        ],
        integraciones: [
          {
            id: "int_01",
            tipo: "github",
            nombre: conConcesion ? "acme-corp/core-api" : "repo-••••",
            estado: "conectado",
          },
          {
            id: "int_02",
            tipo: "jira",
            nombre: conConcesion ? "acme.atlassian.net" : "jira-••••",
            estado: "conectado",
          },
          {
            id: "int_03",
            tipo: "ci_cd",
            nombre: conConcesion ? "GitHub Actions CI" : "ci-••••",
            estado: "activo",
          },
          {
            id: "int_04",
            tipo: "database",
            nombre: conConcesion ? "pg-prod.acme.internal" : "db-••••",
            estado: "conectado",
          },
        ],
      },
      {
        headers: {
          "x-trace-id": traceId,
        },
      }
    );
  }),

  // 5. GET /admin/v1/business/subscriptions
  http.get("*/admin/v1/business/subscriptions", ({ request }) => {
    const errAuth = verificarAutenticacion(request);
    if (errAuth) return errAuth;

    const errFrescura = verificarFrescuraAgregados(request);
    if (errFrescura) return errFrescura;

    const rol = obtenerRol(request);
    if (rol === "staff_operaciones" || rol === "staff_soporte") {
      return HttpResponse.json(
        {
          error: {
            codigo: "ROL_STAFF_INSUFICIENTE",
            code: "rol_staff_insuficiente",
            mensaje: "Acceso exclusivo para roles de negocio o administración.",
          },
        },
        { status: 403 }
      );
    }

    const url = new URL(request.url);

    const planParam = url.searchParams.get("plan");
    const estadoParam = url.searchParams.get("estado");
    const renuevaParam = url.searchParams.get("renueva_en_dias");
    const qParam = url.searchParams.get("q")?.toLowerCase();
    const orderByParam = url.searchParams.get("order_by");
    const page = Math.max(1, parseInt(url.searchParams.get("page") || "1", 10));
    const pageSize = Math.max(1, parseInt(url.searchParams.get("page_size") || "25", 10));

    // Base mock con diferentes rangos de renovación
    const suscripcionesBase = [
      {
        ...CLIENTES_MOCK[0],
        dias_para_renovacion: 16,
        renueva_el: "2026-11-26",
        inicia_el: "2026-01-15",
      },
      {
        ...CLIENTES_MOCK[1],
        dias_para_renovacion: 28,
        renueva_el: "2026-12-08",
        inicia_el: "2025-11-20",
      },
      {
        ...CLIENTES_MOCK[2],
        dias_para_renovacion: 55,
        renueva_el: "2027-01-04",
        inicia_el: "2026-03-10",
      },
      {
        ...CLIENTES_MOCK[3],
        dias_para_renovacion: 85,
        renueva_el: "2027-02-03",
        inicia_el: "2025-08-01",
      },
      {
        ...CLIENTES_MOCK[4],
        dias_para_renovacion: 8,
        renueva_el: "2026-11-18",
        inicia_el: "2026-02-14",
      },
    ];

    let filtrados = suscripcionesBase.map((c) => {
      const tieneGrant = tieneConcesion(request, url, c.tenant_id);
      return {
        tenant_id: c.tenant_id,
        razon_social: tieneGrant ? c.razon_social : "A•••• S.L.",
        plan: c.plan,
        estado: c.estado,
        suscripcion_estado: c.estado,
        inicia_el: c.inicia_el,
        renueva_el: c.renueva_el,
        finaliza_el: null,
        dias_para_renovacion: c.dias_para_renovacion,
        importe_mes: c.mrr_eur,
        moneda: "EUR",
        cuota_uso_pct: c.consumo_ciclo.cuota_pct,
        enmascarado: !tieneGrant,
      };
    });

    if (planParam && planParam !== "todos") {
      filtrados = filtrados.filter((s) => s.plan === planParam);
    }
    if (estadoParam && estadoParam !== "todos") {
      filtrados = filtrados.filter((s) => s.estado === estadoParam);
    }
    if (renuevaParam && renuevaParam !== "todos") {
      const diasMax = parseInt(renuevaParam, 10);
      if (!isNaN(diasMax)) {
        filtrados = filtrados.filter((s) => s.dias_para_renovacion <= diasMax && s.dias_para_renovacion >= 0);
      }
    }
    if (qParam) {
      filtrados = filtrados.filter(
        (s) =>
          s.tenant_id.toLowerCase().includes(qParam) ||
          s.razon_social.toLowerCase().includes(qParam)
      );
    }

    if (orderByParam) {
      const descendente = orderByParam.endsWith("-desc");
      const campo = orderByParam.replace(/-(asc|desc)$/, "");
      filtrados.sort((a, b) => {
        let valA: string | number = "";
        let valB: string | number = "";
        if (campo === "renovacion" || campo === "renueva_el") {
          valA = a.dias_para_renovacion;
          valB = b.dias_para_renovacion;
        } else if (campo === "importe" || campo === "importe_mes") {
          valA = a.importe_mes;
          valB = b.importe_mes;
        } else if (campo === "nombre" || campo === "razon_social") {
          valA = a.razon_social;
          valB = b.razon_social;
        } else if (campo === "tenant_id") {
          valA = a.tenant_id;
          valB = b.tenant_id;
        }
        if (valA < valB) return descendente ? 1 : -1;
        if (valA > valB) return descendente ? -1 : 1;
        return 0;
      });
    }

    const total = filtrados.length;
    const offset = (page - 1) * pageSize;
    const paginados = filtrados.slice(offset, offset + pageSize);

    return HttpResponse.json({
      items: paginados,
      total,
      page,
      page_size: pageSize,
      pages: Math.ceil(total / pageSize) || 1,
      frescura: "2026-10-30T14:00:00.000Z",
      alguna_enmascarada: filtrados.some((s) => s.enmascarado),
    });
  }),

  // 5b. GET /admin/v1/business/upgrade-requests
  http.get("*/admin/v1/business/upgrade-requests", ({ request }) => {
    const errAuth = verificarAutenticacion(request);
    if (errAuth) return errAuth;

    const errFrescura = verificarFrescuraAgregados(request);
    if (errFrescura) return errFrescura;

    const rol = obtenerRol(request);
    if (rol === "staff_operaciones" || rol === "staff_soporte") {
      return HttpResponse.json(
        {
          error: {
            codigo: "ROL_STAFF_INSUFICIENTE",
            code: "rol_staff_insuficiente",
            mensaje: "Acceso exclusivo para roles de negocio o administración.",
          },
        },
        { status: 403 }
      );
    }

    const url = new URL(request.url);

    const estadoParam = url.searchParams.get("estado") ?? "pendiente";
    const planDeseadoParam = url.searchParams.get("plan_deseado");
    const page = Math.max(1, parseInt(url.searchParams.get("page") || "1", 10));
    const pageSize = Math.max(1, parseInt(url.searchParams.get("page_size") || "25", 10));

    const upgradeRequestsMock = [
      {
        solicitud_id: "req_001",
        tenant_id: "org_initech",
        razon_social_real: "Initech Software Corporation",
        plan_actual: "starter",
        plan_deseado: "growth",
        urgente: true,
        estado: "pendiente",
        comentario: "Consumo al 94% de cuota. Requerimos ampliar concurrencia urgente.",
        solicitado_el: "2026-11-08T09:30:00Z",
        cuota_uso_pct: 94.0,
        antiguedad_h: 56,
      },
      {
        solicitud_id: "req_002",
        tenant_id: "org_acme",
        razon_social_real: "Acme Logística S.L.",
        plan_actual: "growth",
        plan_deseado: "enterprise",
        urgente: false,
        estado: "pendiente",
        comentario: "Planificación comercial anual para migrar a despliegue enterprise.",
        solicitado_el: "2026-11-09T14:15:00Z",
        cuota_uso_pct: 85.0,
        antiguedad_h: 27,
      },
      {
        solicitud_id: "req_003",
        tenant_id: "org_globex",
        razon_social_real: "Globex Industrial S.A.",
        plan_actual: "starter",
        plan_deseado: "enterprise",
        urgente: true,
        estado: "atendida",
        comentario: "Upgrade aprobado por dirección comercial.",
        solicitado_el: "2026-11-01T10:00:00Z",
        cuota_uso_pct: 92.5,
        antiguedad_h: 220,
      },
      {
        solicitud_id: "req_004",
        tenant_id: "org_umbrella",
        razon_social_real: "Umbrella BioTech SL",
        plan_actual: "starter",
        plan_deseado: "growth",
        urgente: false,
        estado: "rechazada",
        comentario: "Denegada por incidencias financieras no resueltas.",
        solicitado_el: "2026-10-25T11:00:00Z",
        cuota_uso_pct: 12.0,
        antiguedad_h: 380,
      },
    ].map((r) => {
      const tieneGrant = tieneConcesion(request, url, r.tenant_id);
      return {
        ...r,
        razon_social: tieneGrant ? r.razon_social_real : "A•••• S.L.",
        enmascarado: !tieneGrant,
      };
    });

    let filtrados = [...upgradeRequestsMock];

    if (estadoParam && estadoParam !== "todos") {
      filtrados = filtrados.filter((r) => r.estado === estadoParam);
    }
    if (planDeseadoParam && planDeseadoParam !== "todos") {
      filtrados = filtrados.filter((r) => r.plan_deseado === planDeseadoParam);
    }

    // Por defecto orden por antigüedad: más antiguas primero (solicitado_el ASC)
    filtrados.sort((a, b) => new Date(a.solicitado_el).getTime() - new Date(b.solicitado_el).getTime());

    const total = filtrados.length;
    const offset = (page - 1) * pageSize;
    const paginados = filtrados.slice(offset, offset + pageSize);

    return HttpResponse.json({
      items: paginados,
      total,
      page,
      page_size: pageSize,
      pages: Math.ceil(total / pageSize) || 1,
      frescura: "2026-10-30T14:00:00.000Z",
      alguna_enmascarada: filtrados.some((s) => s.enmascarado),
    });
  }),

  // 6. GET /admin/v1/business/usage/tokens
  http.get("*/admin/v1/business/usage/tokens", ({ request }) => {
    const errAuth = verificarAutenticacion(request);
    if (errAuth) return errAuth;

    const rol = obtenerRol(request);
    if (rol !== "staff_negocio" && rol !== "staff_admin") {
      return HttpResponse.json(
        {
          error: {
            codigo: "ROL_STAFF_INSUFICIENTE",
            mensaje: "Acceso denegado: se requiere rol de negocio o administración.",
          },
        },
        { status: 403 }
      );
    }

    const errFrescura = verificarFrescuraAgregados(request);
    if (errFrescura) return errFrescura;

    const url = new URL(request.url);
    const agruparPor = url.searchParams.get("agrupar_por") || "cliente";
    const periodo = url.searchParams.get("periodo") || "mes_actual";
    const planFiltro = url.searchParams.get("plan") || url.searchParams.get("tier");
    const tenantFiltro = url.searchParams.get("tenant_id") || url.searchParams.get("q");
    const forzarDescuadre =
      request.headers.get("x-mock-descuadre") === "true" ||
      url.searchParams.get("mock_descuadre") === "true";

    if (agruparPor === "tier") {
      const itemsTier = [
        {
          clave: "flash",
          tier: "flash",
          tokens_in: 14500000,
          tokens_input: 14500000,
          tokens_out: 7000000,
          tokens_output: 7000000,
          tokens_total: 21500000,
          por_tier: { flash: 21500000 },
          coste: 43.0,
          coste_estimado_eur: 43.0,
          cuadra_con_facturacion: true,
          enmascarado: false,
        },
        {
          clave: "pro",
          tier: "pro",
          tokens_in: 6000000,
          tokens_input: 6000000,
          tokens_out: 3500000,
          tokens_output: 3500000,
          tokens_total: 9500000,
          por_tier: { pro: 9500000 },
          coste: 190.0,
          coste_estimado_eur: 190.0,
          cuadra_con_facturacion: true,
          enmascarado: false,
        },
        {
          clave: "fable",
          tier: "fable",
          tokens_in: 500000,
          tokens_input: 500000,
          tokens_out: 1000000,
          tokens_output: 1000000,
          tokens_total: 1500000,
          por_tier: { fable: 1500000 },
          coste: 92.5,
          coste_estimado_eur: 92.5,
          cuadra_con_facturacion: true,
          enmascarado: false,
        },
      ];

      return HttpResponse.json({
        items: itemsTier,
        total: itemsTier.length,
        page: 1,
        page_size: 25,
        pages: 1,
        periodo,
        ciclo: "2026-11",
        frescura: new Date().toISOString(),
        totales: {
          tokens: 32500000,
          coste: 325.5,
          moneda: "EUR",
        },
        resumen: {
          total_tokens: 32500000,
          tokens_total: 32500000,
          coste_consolidado: 325.5,
          coste_total_eur: 325.5,
          porcentaje_medio_cuota: 83.75,
          cuota_consumo_media_pct: 83.75,
          moneda: "EUR",
        },
        cuadra_con_facturacion: true,
        descuadres: null,
      });
    }

    if (agruparPor === "dia") {
      const itemsDia = [
        {
          clave: "2026-11-10",
          dia: "2026-11-10",
          tokens_in: 1200000,
          tokens_input: 1200000,
          tokens_out: 600000,
          tokens_output: 600000,
          tokens_total: 1800000,
          por_tier: { flash: 1200000, pro: 500000, fable: 100000 },
          coste: 18.5,
          coste_estimado_eur: 18.5,
          cuadra_con_facturacion: true,
          enmascarado: false,
        },
        {
          clave: "2026-11-09",
          dia: "2026-11-09",
          tokens_in: 1000000,
          tokens_input: 1000000,
          tokens_out: 500000,
          tokens_output: 500000,
          tokens_total: 1500000,
          por_tier: { flash: 1000000, pro: 400000, fable: 100000 },
          coste: 15.0,
          coste_estimado_eur: 15.0,
          cuadra_con_facturacion: true,
          enmascarado: false,
        },
      ];

      return HttpResponse.json({
        items: itemsDia,
        total: itemsDia.length,
        page: 1,
        page_size: 25,
        pages: 1,
        periodo,
        ciclo: "2026-11",
        frescura: new Date().toISOString(),
        totales: {
          tokens: 3300000,
          coste: 33.5,
          moneda: "EUR",
        },
        resumen: {
          total_tokens: 3300000,
          tokens_total: 3300000,
          coste_consolidado: 33.5,
          coste_total_eur: 33.5,
          porcentaje_medio_cuota: 65.0,
          cuota_consumo_media_pct: 65.0,
          moneda: "EUR",
        },
        cuadra_con_facturacion: true,
        descuadres: null,
      });
    }

    // Modo por cliente (por defecto)
    let baseItems = [
      {
        clave: "org_acme",
        tenant_id: "org_acme",
        razon_social_real: "Acme Logística S.L.",
        plan: "growth",
        tokens_in: 3000000,
        tokens_input: 3000000,
        tokens_out: 1500000,
        tokens_output: 1500000,
        tokens_total: 4500000,
        por_tier: {
          flash: 2500000,
          pro: 1500000,
          fable: 500000,
        },
        coste: 45.5,
        coste_estimado_eur: 45.5,
        loc_consumidas: 15000,
        loc_procesadas: 15000,
        cuota_pct: 75.0,
        porcentaje_consumido: 75.0,
        cuadra_con_facturacion: !forzarDescuadre,
      },
      {
        clave: "org_globex",
        tenant_id: "org_globex",
        razon_social_real: "Globex Industrial S.A.",
        plan: "enterprise",
        tokens_in: 18000000,
        tokens_input: 18000000,
        tokens_out: 10000000,
        tokens_output: 10000000,
        tokens_total: 28000000,
        por_tier: {
          flash: 12000000,
          pro: 12000000,
          fable: 4000000,
        },
        coste: 280.0,
        coste_estimado_eur: 280.0,
        loc_consumidas: 85000,
        loc_procesadas: 85000,
        cuota_pct: 92.5,
        porcentaje_consumido: 92.5,
        cuadra_con_facturacion: true,
      },
    ].map((i) => {
      const tieneGrant = tieneConcesion(request, url, i.tenant_id);
      return {
        ...i,
        razon_social: tieneGrant
          ? i.razon_social_real
          : i.tenant_id === "org_globex"
          ? "G•••• S.A."
          : "A•••• S.L.",
        enmascarado: !tieneGrant,
      };
    });

    if (planFiltro && planFiltro !== "todos") {
      baseItems = baseItems.filter((i) => i.plan.toLowerCase() === planFiltro.toLowerCase());
    }

    if (tenantFiltro) {
      const q = tenantFiltro.toLowerCase().trim();
      baseItems = baseItems.filter(
        (i) => i.tenant_id.toLowerCase().includes(q) || i.razon_social.toLowerCase().includes(q)
      );
    }

    const totalTokens = baseItems.reduce((acc, i) => acc + i.tokens_total, 0);
    const costeConsolidado = baseItems.reduce((acc, i) => acc + i.coste_estimado_eur, 0);
    const mediaCuota =
      baseItems.length > 0
        ? baseItems.reduce((acc, i) => acc + (i.cuota_pct || 0), 0) / baseItems.length
        : 0;

    const descuadres = baseItems.filter((i) => !i.cuadra_con_facturacion).map((i) => i.tenant_id);

    return HttpResponse.json({
      items: baseItems,
      total: baseItems.length,
      page: 1,
      page_size: 25,
      pages: 1,
      ciclo: "2026-11",
      periodo,
      frescura: new Date().toISOString(),
      totales: {
        tokens: totalTokens,
        coste: costeConsolidado,
        moneda: "EUR",
      },
      resumen: {
        total_tokens: totalTokens,
        tokens_total: totalTokens,
        coste_consolidado: Number(costeConsolidado.toFixed(2)),
        coste_total_eur: Number(costeConsolidado.toFixed(2)),
        porcentaje_medio_cuota: Number(mediaCuota.toFixed(2)),
        cuota_consumo_media_pct: Number(mediaCuota.toFixed(2)),
        moneda: "EUR",
      },
      cuadra_con_facturacion: descuadres.length === 0,
      descuadres: descuadres.length > 0 ? descuadres : null,
      alguna_enmascarada: baseItems.some((i) => i.enmascarado),
    });
  }),

  // 7. POST /admin/v1/access-grants
  http.post("*/admin/v1/access-grants", async ({ request }) => {
    const errAuth = verificarAutenticacion(request);
    if (errAuth) return errAuth;

    const rol = obtenerRol(request);
    if (rol === "staff_operaciones") {
      return HttpResponse.json(
        {
          error: {
            codigo: "ROL_STAFF_INSUFICIENTE",
            code: "rol_staff_insuficiente",
            mensaje: "staff_operaciones no puede solicitar concesiones de acceso.",
          },
        },
        { status: 403 }
      );
    }

    let body: Record<string, unknown> = {};
    try {
      body = (await request.json()) as Record<string, unknown>;
    } catch {
      return HttpResponse.json(
        {
          error: {
            codigo: "CUERPO_INVALIDO",
            code: "cuerpo_invalido",
            mensaje: "El cuerpo de la petición debe ser JSON válido.",
          },
        },
        { status: 422 }
      );
    }

    const tenantId = (body.tenant_id as string) || "";
    const alcance = (body.alcance as string) || "datos_negocio";
    const motivo = (body.motivo as string) || "";
    const duracionMin = Number(body.duracion_min) || 240;
    const referencia = (body.referencia as string) || "";

    const motivoLimpio = motivo.trim();
    const patronTicket = /(KC|SUP)-\d{3,}/i;
    const refEfectiva = referencia || (patronTicket.test(motivoLimpio) ? motivoLimpio : "");

    if (motivoLimpio.length < 20 || !patronTicket.test(refEfectiva || motivoLimpio)) {
      return HttpResponse.json(
        {
          error: {
            codigo: "MOTIVO_INSUFICIENTE",
            code: "motivo_insuficiente",
            mensaje:
              "El motivo debe contener al menos 20 caracteres y una referencia válida a ticket KC-#### o SUP-####.",
          },
        },
        { status: 422 }
      );
    }

    if (tenantId) {
      persistirConcesionTenant(tenantId);
    }

    const concedidoEn = new Date().toISOString();
    const caducaEn = new Date(Date.now() + duracionMin * 60 * 1000).toISOString();

    return HttpResponse.json(
      {
        grant_id: "gr_mock_" + Math.random().toString(36).substring(2, 9),
        tenant_id: tenantId,
        alcance,
        motivo: motivoLimpio,
        duracion_min: duracionMin,
        referencia: refEfectiva,
        concedido_en: concedidoEn,
        caduca_en: caducaEn,
        visible_para_cliente_en: concedidoEn,
      },
      {
        status: 201,
        headers: {
          "x-trace-id": request.headers.get("x-trace-id") || "trc_grant_001",
        },
      }
    );
  }),

  // ------------------------------------------------------------------ Ops & Telemetría §17.13 – §17.16 / §18.24 – §18.26
  http.get("*/admin/v1/ops/agents", ({ request }) => {
    return responderAgentes(request);
  }),
  http.get("*/internal/v1/telemetry/agents", ({ request }) => {
    return responderAgentes(request);
  }),

  http.get("*/admin/v1/ops/queues", ({ request }) => {
    return responderColas(request);
  }),
  http.get("*/internal/v1/telemetry/queues", ({ request }) => {
    return responderColas(request);
  }),

  http.get("*/admin/v1/ops/models", ({ request }) => {
    return responderModelos(request);
  }),
  http.get("*/internal/v1/telemetry/providers", ({ request }) => {
    return responderModelos(request);
  }),

  http.post("*/internal/v1/telemetry/heartbeat", async ({ request }) => {
    const traceId = request.headers.get("x-trace-id") || "trc_hb_001";
    const escenario = request.headers.get("x-mock-scenario") || "";

    if (escenario === "rate-limit") {
      return HttpResponse.json(
        {
          error: {
            codigo: "RATE_LIMIT_EXCEDIDO",
            mensaje: "Máximo 12 latidos por minuto por agente.",
          },
        },
        { status: 429, headers: { "x-trace-id": traceId } }
      );
    }

    let body: Record<string, unknown> = {};
    try {
      body = (await request.json()) as Record<string, unknown>;
    } catch {
      return HttpResponse.json(
        { error: { codigo: "CUERPO_INVALIDO", mensaje: "JSON inválido." } },
        { status: 422, headers: { "x-trace-id": traceId } }
      );
    }

    if (!body.agente_id || !body.linea || !body.etapa || body.ventana_s === undefined) {
      return HttpResponse.json(
        {
          error: {
            codigo: "VALIDACION_ENTRADA",
            mensaje: "Faltan campos obligatorios en el latido.",
          },
        },
        { status: 422, headers: { "x-trace-id": traceId } }
      );
    }

    return HttpResponse.json(
      {
        recibido: true,
        agente_id: body.agente_id,
        registrado_en: new Date().toISOString(),
      },
      { status: 202, headers: { "x-trace-id": traceId } }
    );
  }),
];

function responderAgentes(request: Request): Response {
  const traceId = request.headers.get("x-trace-id") || "trc_ops_ag_001";
  const url = new URL(request.url);
  const ventana = url.searchParams.get("ventana") || "1h";
  const escenario =
    request.headers.get("x-mock-scenario") || estadoGlobal.telemetriaEstado;

  if (escenario === "desactualizada") {
    return HttpResponse.json(
      {
        error: {
          codigo: "TELEMETRIA_NO_DISPONIBLE",
          mensaje: "La telemetría del pipeline no está disponible (> 15 min).",
        },
      },
      { status: 503, headers: { "x-trace-id": traceId } }
    );
  }

  if (escenario === "sin-telemetria") {
    return HttpResponse.json(
      {
        ventana,
        telemetria: {
          disponible: false,
          antiguedad_s: null,
          desde: null,
        },
        agentes_total: 0,
        agentes_ocupados: 0,
        agentes_caidos: 0,
        etapas: null,
        lineas: { activas: 0, mantenimiento: 0, libres: 0 },
        alertas: [],
      },
      { status: 200, headers: { "x-trace-id": traceId } }
    );
  }

  if (escenario === "sin-trabajo") {
    return HttpResponse.json(
      {
        ventana,
        telemetria: {
          disponible: true,
          antiguedad_s: 5,
          desde: new Date().toISOString(),
        },
        agentes_total: 25,
        agentes_ocupados: 0,
        agentes_caidos: 0,
        lineas: { activas: 12, mantenimiento: 0, libres: 5 },
        etapas: [
          { etapa: "triage", agentes_total: 4, agentes_ocupados: 0, agentes_caidos: 0 },
          { etapa: "design", agentes_total: 6, agentes_ocupados: 0, agentes_caidos: 0 },
          { etapa: "build", agentes_total: 10, agentes_ocupados: 0, agentes_caidos: 0 },
          { etapa: "qa", agentes_total: 5, agentes_ocupados: 0, agentes_caidos: 0 },
        ],
        alertas: [],
      },
      { status: 200, headers: { "x-trace-id": traceId } }
    );
  }

  return HttpResponse.json(
    {
      ventana,
      telemetria: {
        disponible: true,
        antiguedad_s: 4,
        desde: new Date().toISOString(),
      },
      agentes_total: 25,
      agentes_ocupados: 18,
      agentes_caidos: 1,
      jobs_completados: 142,
      duracion_p95_s: 38.5,
      lineas_activas: 12,
      lineas: { activas: 12, mantenimiento: 1, libres: 5 },
      etapas: [
        {
          etapa: "triage",
          agentes_total: 4,
          agentes_ocupados: 2,
          agentes_caidos: 0,
          en_cola: 5,
          latencia_p95_ms: 1200,
          errores: 0,
        },
        {
          etapa: "design",
          agentes_total: 6,
          agentes_ocupados: 5,
          agentes_caidos: 0,
          en_cola: 12,
          latencia_p95_ms: 4800,
          errores: 0,
        },
        {
          etapa: "build",
          agentes_total: 10,
          agentes_ocupados: 8,
          agentes_caidos: 1,
          en_cola: 18,
          latencia_p95_ms: 14200,
          errores: 1,
        },
        {
          etapa: "qa",
          agentes_total: 5,
          agentes_ocupados: 3,
          agentes_caidos: 0,
          en_cola: 2,
          latencia_p95_ms: 6100,
          errores: 0,
        },
      ],
      alertas: [{ tipo: "agentes_caidos", etapa: "build", valor: 1 }],
    },
    { status: 200, headers: { "x-trace-id": traceId } }
  );
}

function responderColas(request: Request): Response {
  const traceId = request.headers.get("x-trace-id") || "trc_ops_q_001";

  return HttpResponse.json(
    {
      telemetria_desde: new Date().toISOString(),
      resumen: {
        criticas: 1,
        atencion: 1,
        pendientes_total: 104,
        fallidos_total: 2,
      },
      colas: [
        {
          nombre: "cola_ingesta",
          profundidad: 24,
          antiguedad_max_s: 15,
          no_confirmados: 4,
          dlq: 0,
          umbral_atencion_s: 60,
          estado: "normal",
        },
        {
          nombre: "cola_generacion",
          profundidad: 78,
          antiguedad_max_s: 75,
          no_confirmados: 12,
          dlq: 0,
          umbral_atencion_s: 60,
          estado: "atencion",
        },
        {
          nombre: "kc:dlq",
          profundidad: 2,
          antiguedad_max_s: 320,
          no_confirmados: 0,
          dlq: 2,
          umbral_atencion_s: 0,
          estado: "critico",
        },
      ],
    },
    { status: 200, headers: { "x-trace-id": traceId } }
  );
}

function responderModelos(request: Request): Response {
  const traceId = request.headers.get("x-trace-id") || "trc_ops_mod_001";
  const url = new URL(request.url);
  const ventana = url.searchParams.get("ventana") || "24h";

  return HttpResponse.json(
    {
      ventana,
      telemetria_desde: new Date().toISOString(),
      proveedores: [
        {
          proveedor: "Google",
          modelo: "gemini-2.5-flash",
          tier: "flash",
          disponibilidad_pct: 99.98,
          latencia_p50_ms: 180,
          latencia_p95_ms: 420,
          tasa_error_pct: 0.05,
        },
        {
          proveedor: "Google",
          modelo: "gemini-2.5-pro",
          tier: "pro",
          disponibilidad_pct: 99.85,
          latencia_p50_ms: 650,
          latencia_p95_ms: 1250,
          tasa_error_pct: 0.12,
        },
        {
          proveedor: "Anthropic",
          modelo: "claude-3-7-sonnet",
          tier: "fable",
          disponibilidad_pct: 99.92,
          latencia_p50_ms: 920,
          latencia_p95_ms: 1840,
          tasa_error_pct: 0.08,
        },
      ],
      modelos: [
        {
          proveedor: "Google",
          modelo: "gemini-2.5-flash",
          tier: "flash",
          disponibilidad_pct: 99.98,
          latencia_p50_ms: 180,
          latencia_p95_ms: 420,
          tasa_error_pct: 0.05,
        },
        {
          proveedor: "Google",
          modelo: "gemini-2.5-pro",
          tier: "pro",
          disponibilidad_pct: 99.85,
          latencia_p50_ms: 650,
          latencia_p95_ms: 1250,
          tasa_error_pct: 0.12,
        },
        {
          proveedor: "Anthropic",
          modelo: "claude-3-7-sonnet",
          tier: "fable",
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
        flash: 80000000,
        pro: 35000000,
        fable: 10000000,
      },
      coste_por_tier: {
        flash: 120.5,
        pro: 310.2,
        fable: 450.0,
      },
      degradados: null,
      comparacion: null,
    },
    { status: 200, headers: { "x-trace-id": traceId } }
  );
}
