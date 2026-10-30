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
}

const configDefecto: MockConfig = {
  concesionActiva: false,
  estadoAgregados: "ok",
  rolStaff: "staff_negocio",
  frescuraCustom: null,
};

let estadoGlobal: MockConfig = { ...configDefecto };

/** Modifica dinámicamente si existe concesión activa de acceso simulada. */
export function setMockConcesionActiva(activa: boolean): void {
  estadoGlobal.concesionActiva = activa;
}

/** Modifica dinámicamente el estado de frescura de los agregados. */
export function setMockEstadoAgregados(estado: "ok" | "obsoleto" | "fallido"): void {
  estadoGlobal.estadoAgregados = estado;
}

/** Configura una fecha ISO personalizada para simular agregados obsoletos o recientes. */
export function setMockFrescura(fechaIso: string | null): void {
  estadoGlobal.frescuraCustom = fechaIso;
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
function tieneConcesion(request: Request, url: URL): boolean {
  return (
    request.headers.get("x-mock-grant") === "true" ||
    request.headers.get("x-mock-concesion") === "true" ||
    url.searchParams.get("mock_grant") === "true" ||
    estadoGlobal.concesionActiva
  );
}

// Helper para determinar el rol activo
function obtenerRol(request: Request): string {
  return request.headers.get("x-mock-role") || estadoGlobal.rolStaff;
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

// ------------------------------------------------------------------ Handlers MSW
export const handlers = [
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
    const conConcesion = tieneConcesion(request, url);
    const busquedaPorNombre = Boolean(q && !q.startsWith("org_"));
    if (busquedaPorNombre && !conConcesion) {
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

    // Mapeo de enmascaramiento según concesión
    const items = paginados.map((c) => {
      const masked = !conConcesion;
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
        alguna_enmascarada: !conConcesion,
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
    const conConcesion = tieneConcesion(request, url);

    const razonSocial = conConcesion ? cliente.razon_social : "A•••• S.L.";
    const dominio = conConcesion ? cliente.dominio : "a••••.com";
    const enmascarados = conConcesion ? [] : ["razon_social", "dominio"];

    return HttpResponse.json({
      tenant_id: cliente.tenant_id,
      razon_social: razonSocial,
      dominio,
      frescura: "2026-10-30T14:00:00.000Z",
      enmascarado: enmascarados,
      identificacion: {
        tenant_id: cliente.tenant_id,
        razon_social: razonSocial,
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
      },
      lineas: {
        contratadas: cliente.lineas_contratadas,
        activas: cliente.lineas_activas,
        loc_mes: 20000,
      },
      actividad: {
        usuarios_activos: cliente.usuarios_activos,
        usuarios_total: cliente.usuarios_activos + 5,
        integraciones: 3,
        docs_onboarding: 8,
        tickets_abiertos: cliente.tickets_abiertos,
        ultima_actividad: cliente.ultima_actividad,
      },
      consumo: {
        loc_consumidas: cliente.consumo_ciclo.loc,
        cuota_pct: cliente.consumo_ciclo.cuota_pct,
        tokens_in: 3000000,
        tokens_out: 1500000,
        coste: 45.5,
      },
      usuarios: [
        { id: "usr_01", email: conConcesion ? "admin@acme.com" : "a••••@acme.com", rol: "owner", estado: "activo" },
      ],
      integraciones: [{ id: "int_01", tipo: "github", estado: "conectado" }],
    });
  }),

  // 5. GET /admin/v1/business/subscriptions
  http.get("*/admin/v1/business/subscriptions", ({ request }) => {
    const errAuth = verificarAutenticacion(request);
    if (errAuth) return errAuth;

    const errFrescura = verificarFrescuraAgregados(request);
    if (errFrescura) return errFrescura;

    const url = new URL(request.url);
    const conConcesion = tieneConcesion(request, url);

    const items = CLIENTES_MOCK.map((c) => ({
      tenant_id: c.tenant_id,
      razon_social: conConcesion ? c.razon_social : "A•••• S.L.",
      plan: c.plan,
      estado: c.estado,
      suscripcion_estado: c.estado,
      inicia_el: "2026-01-15",
      renueva_el: "2026-11-15",
      finaliza_el: null,
      dias_para_renovacion: 16,
      importe_mes: c.mrr_eur,
      moneda: "EUR",
      cuota_uso_pct: c.consumo_ciclo.cuota_pct,
      enmascarado: !conConcesion,
    }));

    return HttpResponse.json({
      items,
      total: items.length,
      page: 1,
      page_size: 25,
      pages: 1,
      alguna_enmascarada: !conConcesion,
    });
  }),

  // 6. GET /admin/v1/business/usage/tokens
  http.get("*/admin/v1/business/usage/tokens", ({ request }) => {
    const errAuth = verificarAutenticacion(request);
    if (errAuth) return errAuth;

    const errFrescura = verificarFrescuraAgregados(request);
    if (errFrescura) return errFrescura;

    const items = [
      {
        clave: "org_acme",
        tenant_id: "org_acme",
        tokens_in: 3000000,
        tokens_out: 1500000,
        por_tier: {
          flash: 2500000,
          pro: 1500000,
          fable: 500000,
        },
        coste: 45.5,
        loc_consumidas: 15000,
        cuota_pct: 75.0,
        cuadra_con_facturacion: true,
      },
      {
        clave: "org_globex",
        tenant_id: "org_globex",
        tokens_in: 18000000,
        tokens_out: 10000000,
        por_tier: {
          flash: 12000000,
          pro: 12000000,
          fable: 4000000,
        },
        coste: 280.0,
        loc_consumidas: 85000,
        cuota_pct: 92.5,
        cuadra_con_facturacion: true,
      },
    ];

    return HttpResponse.json({
      items,
      total: items.length,
      page: 1,
      page_size: 25,
      pages: 1,
    });
  }),
];
