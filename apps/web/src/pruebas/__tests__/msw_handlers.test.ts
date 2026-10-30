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
