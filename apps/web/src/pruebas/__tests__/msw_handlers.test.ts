/**
 * msw_handlers.test.ts — Pruebas directas de los dobles de API de negocio MSW v2
 *
 * Valida contratos OpenAPI, paginación, filtros, enmascaramiento condicional
 * y simulación de errores HTTP (401, 403, 404, 503).
 */

import { describe, it, expect } from "vitest";
import { peticionApi } from "../../api/clienteApi";
import {
  setMockConcesionActiva,
  setMockEstadoAgregados,
  setMockRolStaff,
  setMockTelemetriaEstado,
  resetMockState,
} from "../msw_handlers";

describe("MSW Handlers — Endpoints de Negocio (/admin/v1/business/*)", () => {
  // 1. /summary
  it("GET /admin/v1/business/summary devuelve KPIs consolidados compatibles con OpenAPI", async () => {
    const res = await peticionApi<Record<string, unknown>>(
      "/admin/v1/business/summary"
    );

    expect(res.mrr_eur).toBe(45000.0);
    expect(res.clientes_activos).toBe(128);
    expect(res.frescura).toBeDefined();

    const tokens = res.consumo_tokens_ciclo as Record<string, number>;
    expect(tokens.total).toBe(125000000);
    expect(tokens.flash).toBe(80000000);
    expect(tokens.pro).toBe(35000000);
    expect(tokens.fable).toBe(10000000);
  });

  // 2. /overview
  it("GET /admin/v1/business/overview devuelve los bloques requeridos del panel", async () => {
    const res = await peticionApi<Record<string, unknown>>(
      "/admin/v1/business/overview"
    );

    expect(res.mrr_eur).toBe(45000.0);
    expect(res.clientes).toBeDefined();
    expect(res.ingresos).toBeDefined();
    expect(res.consumo).toBeDefined();
    expect(res.pipeline).toBeDefined();
    expect(res.tendencia).toBeDefined();
    expect(res.frescura).toBeDefined();
  });

  // 3. /customers con enmascaramiento por defecto
  it("GET /admin/v1/business/customers enmascara por defecto sin concesión activa", async () => {
    setMockConcesionActiva(false);

    const res = await peticionApi<{
      items: Array<{ razon_social: string; dominio: string; enmascarado: boolean }>;
      total: number;
      page: number;
      page_size: number;
      pages: number;
      alguna_enmascarada: boolean;
    }>("/admin/v1/business/customers");

    expect(res.items.length).toBeGreaterThan(0);
    expect(res.total).toBe(5);
    expect(res.page).toBe(1);
    expect(res.page_size).toBe(25);
    expect(res.pages).toBe(1);
    expect(res.alguna_enmascarada).toBe(true);

    const primero = res.items[0];
    expect(primero.enmascarado).toBe(true);
    expect(primero.razon_social).toBe("A•••• S.L.");
    expect(primero.dominio).toBe("a••••.com");
  });

  // 4. /customers con concesión activa
  it("GET /admin/v1/business/customers entrega datos visibles cuando existe concesión activa", async () => {
    setMockConcesionActiva(true);

    const res = await peticionApi<{
      items: Array<{ razon_social: string; dominio: string; enmascarado: boolean }>;
      alguna_enmascarada: boolean;
    }>("/admin/v1/business/customers");

    expect(res.alguna_enmascarada).toBe(false);
    const primero = res.items[0];
    expect(primero.enmascarado).toBe(false);
    expect(primero.razon_social).toBe("Acme Logística S.L.");
    expect(primero.dominio).toBe("acme.com");
  });

  // 5. /customers con filtros y paginación
  it("GET /admin/v1/business/customers filtra correctamente por plan y estado", async () => {
    setMockConcesionActiva(true);

    const resStarter = await peticionApi<{
      items: Array<{ plan: string }>;
      total: number;
    }>("/admin/v1/business/customers", {
      params: { plan: "starter" },
    });

    expect(resStarter.total).toBe(2);
    for (const item of resStarter.items) {
      expect(item.plan).toBe("starter");
    }

    const resActiva = await peticionApi<{
      items: Array<{ estado: string }>;
      total: number;
    }>("/admin/v1/business/customers", {
      params: { estado: "activa" },
    });

    expect(resActiva.total).toBe(3);
    for (const item of resActiva.items) {
      expect(item.estado).toBe("activa");
    }
  });

  // 6. /customers/{tenant_id} (Ficha 360)
  it("GET /admin/v1/business/customers/:tenant_id devuelve la ficha 360", async () => {
    setMockConcesionActiva(true);

    const res = await peticionApi<Record<string, unknown>>(
      "/admin/v1/business/customers/org_acme"
    );

    expect(res.tenant_id).toBe("org_acme");
    expect(res.razon_social).toBe("Acme Logística S.L.");
    expect(res.identificacion).toBeDefined();
    expect(res.suscripcion).toBeDefined();
    expect(res.lineas).toBeDefined();
    expect(res.actividad).toBeDefined();
    expect(res.consumo).toBeDefined();
    expect(res.usuarios).toBeDefined();
  });

  // 7. Error HTTP 404 ante organización inexistente
  it("GET /admin/v1/business/customers/:tenant_id devuelve 404 ante org_desconocida", async () => {
    await expect(
      peticionApi("/admin/v1/business/customers/org_desconocida")
    ).rejects.toMatchObject({
      status: 404,
      codigo: "NO_ENCONTRADO",
    });
  });

  // 8. Error HTTP 403 ante staff_operaciones
  it("GET /admin/v1/business/customers devuelve 403 ROL_STAFF_INSUFICIENTE a staff_operaciones", async () => {
    setMockRolStaff("staff_operaciones");

    await expect(peticionApi("/admin/v1/business/customers")).rejects.toMatchObject({
      status: 403,
      codigo: "ROL_STAFF_INSUFICIENTE",
    });
  });

  // 9. Error HTTP 503 ante agregados no disponibles o en refresco
  it("GET /admin/v1/business/overview devuelve 503 AGREGADO_NO_DISPONIBLE cuando el worker no ha completado el refresco", async () => {
    setMockEstadoAgregados("fallido");

    await expect(peticionApi("/admin/v1/business/overview")).rejects.toMatchObject({
      status: 503,
      codigo: "AGREGADO_NO_DISPONIBLE",
    });
  });

  // 10. GET /subscriptions
  it("GET /admin/v1/business/subscriptions devuelve listado de renovaciones y planes", async () => {
    const res = await peticionApi<{
      items: Array<{ tenant_id: string; dias_para_renovacion: number; importe_mes: number }>;
      total: number;
      pages: number;
    }>("/admin/v1/business/subscriptions");

    expect(res.total).toBe(5);
    expect(res.pages).toBe(1);
    expect(res.items[0].dias_para_renovacion).toBe(16);
    expect(res.items[0].importe_mes).toBe(1200.0);
  });

  // 11. GET /usage/tokens
  it("GET /admin/v1/business/usage/tokens desglosa consumo por tier de modelo", async () => {
    const res = await peticionApi<{
      items: Array<{
        tenant_id: string;
        por_tier: { flash: number; pro: number; fable: number };
        cuadra_con_facturacion: boolean;
      }>;
    }>("/admin/v1/business/usage/tokens");

    expect(res.items.length).toBe(2);
    expect(res.items[0].por_tier.flash).toBeGreaterThan(0);
    expect(res.items[0].por_tier.pro).toBeGreaterThan(0);
    expect(res.items[0].por_tier.fable).toBeGreaterThan(0);
    expect(res.items[0].cuadra_con_facturacion).toBe(true);
  });
});

describe("MSW Handlers — Endpoints de Operaciones y Telemetría (§17.13 – §17.16)", () => {
  it("GET /admin/v1/ops/agents devuelve estado nominal de agentes y líneas", async () => {
    resetMockState();
    const res = await peticionApi<{
      telemetria: { disponible: boolean; antiguedad_s: number };
      agentes_total: number;
      agentes_ocupados: number;
      etapas: Array<{ etapa: string }>;
    }>("/admin/v1/ops/agents");

    expect(res.telemetria.disponible).toBe(true);
    expect(res.agentes_total).toBe(25);
    expect(res.agentes_ocupados).toBe(18);
    expect(res.etapas.length).toBeGreaterThan(0);
  });

  it("GET /admin/v1/ops/agents distingue 'sin-trabajo' (agentes > 0, ocupados = 0)", async () => {
    setMockTelemetriaEstado("sin-trabajo");
    const res = await peticionApi<{
      telemetria: { disponible: boolean };
      agentes_total: number;
      agentes_ocupados: number;
    }>("/admin/v1/ops/agents");

    expect(res.telemetria.disponible).toBe(true);
    expect(res.agentes_total).toBe(25);
    expect(res.agentes_ocupados).toBe(0);
  });

  it("GET /admin/v1/ops/agents distingue 'sin-telemetria' (disponible = false, etapas = null)", async () => {
    setMockTelemetriaEstado("sin-telemetria");
    const res = await peticionApi<{
      telemetria: { disponible: boolean; desde: string | null };
      agentes_total: number;
      etapas: unknown;
    }>("/admin/v1/ops/agents");

    expect(res.telemetria.disponible).toBe(false);
    expect(res.telemetria.desde).toBeNull();
    expect(res.agentes_total).toBe(0);
    expect(res.etapas).toBeNull();
  });

  it("GET /admin/v1/ops/agents rechaza con 503 TELEMETRIA_NO_DISPONIBLE si la señal supera 15 min", async () => {
    setMockTelemetriaEstado("desactualizada");
    await expect(peticionApi("/admin/v1/ops/agents")).rejects.toMatchObject({
      status: 503,
      codigo: "TELEMETRIA_NO_DISPONIBLE",
    });
  });

  it("GET /admin/v1/ops/queues supervisa colas e incluye la cola crítica kc:dlq", async () => {
    resetMockState();
    const res = await peticionApi<{
      colas: Array<{ nombre: string; dlq: number; estado: string }>;
      resumen: { criticas: number };
    }>("/admin/v1/ops/queues");

    expect(res.colas.length).toBeGreaterThanOrEqual(3);
    const dlq = res.colas.find((c) => c.nombre === "kc:dlq");
    expect(dlq).toBeDefined();
    expect(dlq?.dlq).toBe(2);
    expect(dlq?.estado).toBe("critico");
    expect(res.resumen.criticas).toBe(1);
  });

  it("GET /admin/v1/ops/models reporta el tier fable de forma estrictamente separada de pro", async () => {
    resetMockState();
    const res = await peticionApi<{
      modelos: Array<{ modelo: string; tier: string }>;
      escalados: { flash_a_pro: number; pro_a_fable: number; a_humano: number };
      tokens_por_tier: { flash: number; pro: number; fable: number };
    }>("/admin/v1/ops/models");

    const tiers = res.modelos.map((m) => m.tier);
    expect(tiers).toContain("flash");
    expect(tiers).toContain("pro");
    expect(tiers).toContain("fable");

    expect(res.tokens_por_tier.fable).toBe(10000000);
    expect(res.tokens_por_tier.pro).toBe(35000000);
    expect(res.escalados.flash_a_pro).toBe(142);
    expect(res.escalados.pro_a_fable).toBe(18);
    expect(res.escalados.a_humano).toBe(3);
  });

  it("POST /internal/v1/telemetry/heartbeat acepta latidos válidos y rechaza inválidos o rate-limited", async () => {
    // 1. Aceptado 202
    const resOk = await peticionApi<{ recibido: boolean; agente_id: string }>(
      "/internal/v1/telemetry/heartbeat",
      {
        method: "POST",
        body: JSON.stringify({
          agente_id: "ag_test_01",
          linea: "linea_01",
          etapa: "build",
          job_id: "job_01",
          ventana_s: 5,
          timestamp: new Date().toISOString(),
        }),
      }
    );
    expect(resOk.recibido).toBe(true);
    expect(resOk.agente_id).toBe("ag_test_01");

    // 2. Inválido 422
    await expect(
      peticionApi("/internal/v1/telemetry/heartbeat", {
        method: "POST",
        body: JSON.stringify({ agente_id: "incompleto" }),
      })
    ).rejects.toMatchObject({
      status: 422,
      codigo: "VALIDACION_ENTRADA",
    });

    // 3. Rate-limited 429
    await expect(
      peticionApi("/internal/v1/telemetry/heartbeat", {
        method: "POST",
        headers: { "x-mock-scenario": "rate-limit" },
        body: JSON.stringify({
          agente_id: "ag_flood",
          linea: "linea_01",
          etapa: "triage",
          ventana_s: 1,
        }),
      })
    ).rejects.toMatchObject({
      status: 429,
      codigo: "RATE_LIMIT_EXCEDIDO",
    });
  });
});
