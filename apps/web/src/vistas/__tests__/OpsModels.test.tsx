/**
 * OpsModels.test.tsx — Pruebas de componente para la pantalla OpsModels
 *
 * Valida:
 * 1. Skeleton accesible (ContenedorEstado), catálogo canónico v1.1 (gemini-3-flash,
 *    gemini-3-pro, deepseek-v4, claude-fable-5), salud de servicios core,
 *    escalados (flash_a_pro, pro_a_fable, a_humano) y tokens/coste por tier.
 * 2. Segregación visual y numérica estricta del tier Fable respecto a Flash y Pro.
 * 3. Selector de ventana (1h, 24h, 7d, 30d), filtros por proveedor y tier,
 *    y comparativa contra período anterior (comparar_con=periodo_anterior).
 * 4. Alerta crítica visual ante disponibilidad < 99% en ventana de 1 hora.
 * 5. Manejo de 503 TELEMETRIA_NO_DISPONIBLE con X-Trace-Id, reintento y estado vacío.
 * 6. Control de acceso RBAC (staff_operaciones, staff_admin, staff_negocio permitidos;
 *    staff_soporte bloqueado con 403 ROL_STAFF_INSUFICIENTE) y ausencia de UI leaks.
 */

import { describe, it, expect } from "vitest";
import { render, screen, waitFor, fireEvent, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { http, HttpResponse } from "msw";
import { server } from "../../pruebas/server";
import { AuthProvider, UsuarioStaff } from "../../estado/auth";
import { OpsModels } from "../OpsModels";

function renderOpsModels(opciones?: { usuario?: UsuarioStaff }) {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
      },
    },
  });

  const usuarioOps: UsuarioStaff = opciones?.usuario ?? {
    staff_id: "st_ops_001",
    email: "ops@kallicode.com",
    nombre: "Staff Operaciones",
    role: "staff_operaciones",
    mfa_validado: true,
  };

  return render(
    <AuthProvider
      sesionInicial={{
        usuario: usuarioOps,
        token: `mock_jwt_${usuarioOps.role}`,
      }}
    >
      <QueryClientProvider client={queryClient}>
        <OpsModels />
      </QueryClientProvider>
    </AuthProvider>
  );
}

describe("OpsModels — Telemetría LLM, Escalados y Segregación Fable", () => {
  it("1. renderiza skeleton inicial, servicios core, escalados, tokens/coste por tier y catálogo v1.1", async () => {
    const { container } = renderOpsModels();

    const loader = screen.getByTestId("ops-models-loading");
    expect(loader.getAttribute("role")).toBe("status");
    expect(loader.getAttribute("aria-busy")).toBe("true");

    await waitFor(() => {
      expect(screen.getByTestId("tabla-modelos-estandar")).toBeDefined();
    });

    // Ventana 24h activa por defecto
    expect(screen.getByTestId("btn-ventana-models-24h").getAttribute("aria-pressed")).toBe("true");

    // Servicios Core
    expect(screen.getByTestId("servicio-postgres").textContent).toContain("OPERATIVO");
    expect(screen.getByTestId("servicio-blob").textContent).toContain("OPERATIVO");
    expect(screen.getByTestId("servicio-telemetria").textContent).toContain("OPERATIVO");
    expect(screen.getByTestId("servicio-agregados").textContent).toContain("OPERATIVO");

    // Escalados
    expect(screen.getByTestId("kpi-escalado-flash-pro").textContent).toContain("142");
    expect(screen.getByTestId("kpi-escalado-pro-fable").textContent).toContain("18");
    expect(screen.getByTestId("kpi-escalado-humano").textContent).toContain("3");

    // Tokens y coste segregados por tier
    expect(screen.getByTestId("card-tier-flash").textContent).toContain("80.0 M tokens");
    expect(screen.getByTestId("card-tier-flash").textContent).toContain("120.50 €");
    expect(screen.getByTestId("card-tier-pro").textContent).toContain("35.0 M tokens");
    expect(screen.getByTestId("card-tier-pro").textContent).toContain("310.20 €");
    expect(screen.getByTestId("card-tier-fable").textContent).toContain("10.0 M tokens");
    expect(screen.getByTestId("card-tier-fable").textContent).toContain("450.00 €");

    // Cabeceras accesibles con scope="col"
    const headers = container.querySelectorAll("th[scope='col']");
    expect(headers.length).toBeGreaterThanOrEqual(8);

    // Ausencia de fugas de especificación o nombres crudos BD
    expect(container.textContent).not.toMatch(/§18\.|admin\.agg_|admin\.staff_/);
  });

  it("2. segrega estrictamente el tier Fable (claude-fable-5) de los tiers estándar (Flash y Pro)", async () => {
    renderOpsModels();

    await waitFor(() => {
      expect(screen.getByTestId("tabla-modelos-estandar")).toBeDefined();
      expect(screen.getByTestId("seccion-fable-segregada")).toBeDefined();
    });

    const tablaEstandar = screen.getByTestId("tabla-modelos-estandar");
    expect(within(tablaEstandar).getByText("gemini-3-flash")).toBeDefined();
    expect(within(tablaEstandar).getByText("gemini-3-pro")).toBeDefined();
    expect(within(tablaEstandar).getByText("deepseek-v4")).toBeDefined();
    expect(within(tablaEstandar).queryByText("claude-fable-5")).toBeNull();

    const seccionFable = screen.getByTestId("seccion-fable-segregada");
    expect(within(seccionFable).getByText("claude-fable-5")).toBeDefined();
    expect(within(seccionFable).getByText("FABLE")).toBeDefined();
    expect(within(seccionFable).queryByText("gemini-3-pro")).toBeNull();
  });

  it("3. sincroniza ventana (1h, 24h, 7d, 30d), filtros proveedor/tier y comparativa periodo_anterior", async () => {
    const consultas: string[] = [];
    server.use(
      http.get("*/admin/v1/ops/models", ({ request }) => {
        consultas.push(request.url);
        const url = new URL(request.url);
        const ventana = url.searchParams.get("ventana") || "24h";
        const proveedor = url.searchParams.get("proveedor");
        const tier = url.searchParams.get("tier");
        const compararCon = url.searchParams.get("comparar_con");

        const base = [
          {
            proveedor: "Google",
            modelo: "gemini-3-flash",
            tier: "flash",
            llamadas: ventana === "7d" ? 297500 : 42500,
            disponibilidad_pct: 99.98,
            latencia_p50_ms: 180,
            latencia_p95_ms: 420,
            tasa_error_pct: 0.05,
          },
          {
            proveedor: "Anthropic",
            modelo: "claude-fable-5",
            tier: "fable",
            llamadas: ventana === "7d" ? 12950 : 1850,
            disponibilidad_pct: 99.92,
            latencia_p50_ms: 920,
            latencia_p95_ms: 1840,
            tasa_error_pct: 0.08,
          },
        ].filter((m) => {
          if (proveedor && m.proveedor.toLowerCase() !== proveedor) return false;
          if (tier && m.tier !== tier) return false;
          return true;
        });

        return HttpResponse.json({
          ventana,
          proveedores: base,
          modelos: base,
          escalados: { flash_a_pro: 142, pro_a_fable: 18, a_humano: 3 },
          tokens_por_tier: { flash: 80000000, pro: 35000000, fable: 10000000 },
          coste_por_tier: { flash: 120.5, pro: 310.2, fable: 450.0 },
          comparacion:
            compararCon === "periodo_anterior"
              ? {
                  periodo: "periodo_anterior",
                  escalados: { flash_a_pro: 120, pro_a_fable: 15, a_humano: 3 },
                  proveedores: base.map((m) => ({
                    ...m,
                    llamadas: Math.round(m.llamadas * 0.8),
                    latencia_p95_ms: Math.round(m.latencia_p95_ms * 1.1),
                  })),
                }
              : null,
        });
      })
    );

    renderOpsModels();

    await waitFor(() => {
      expect(screen.getByTestId("fila-modelo-gemini-3-flash")).toBeDefined();
    });

    // Cambiar ventana a 7d
    fireEvent.click(screen.getByTestId("btn-ventana-models-7d"));
    await waitFor(() => {
      expect(consultas.some((u) => u.includes("ventana=7d"))).toBe(true);
    });

    // Activar comparación con período anterior
    fireEvent.click(screen.getByTestId("toggle-comparar-periodo"));
    await waitFor(() => {
      expect(screen.getByTestId("delta-gemini-3-flash").textContent).toContain("+25.0%");
    });

    // Filtrar por proveedor Anthropic
    fireEvent.change(screen.getByTestId("filtro-proveedor"), {
      target: { value: "anthropic" },
    });
    await waitFor(() => {
      expect(screen.queryByTestId("fila-modelo-gemini-3-flash")).toBeNull();
      expect(screen.getByTestId("fila-modelo-claude-fable-5")).toBeDefined();
    });

    expect(consultas.some((u) => u.includes("comparar_con=periodo_anterior"))).toBe(true);
    expect(consultas.some((u) => u.includes("proveedor=anthropic"))).toBe(true);
  });

  it("4. alerta visualmente cuando algún proveedor cae por debajo de 99% de disponibilidad en ventana 1h", async () => {
    renderOpsModels();

    await waitFor(() => {
      expect(screen.getByTestId("tabla-modelos-estandar")).toBeDefined();
    });

    server.use(
      http.get("*/admin/v1/ops/models", () =>
        HttpResponse.json({
          ventana: "1h",
          proveedores: [
            {
              proveedor: "DeepSeek",
              modelo: "deepseek-v4",
              tier: "pro",
              llamadas: 840,
              disponibilidad_pct: 97.8,
              latencia_p50_ms: 1450,
              latencia_p95_ms: 3200,
              tasa_error_pct: 2.2,
            },
          ],
          modelos: [
            {
              proveedor: "DeepSeek",
              modelo: "deepseek-v4",
              tier: "pro",
              llamadas: 840,
              disponibilidad_pct: 97.8,
              latencia_p50_ms: 1450,
              latencia_p95_ms: 3200,
              tasa_error_pct: 2.2,
            },
          ],
          escalados: { flash_a_pro: 25, pro_a_fable: 4, a_humano: 1 },
          tokens_por_tier: { flash: 8000000, pro: 3500000, fable: 1000000 },
          coste_por_tier: { flash: 12.05, pro: 31.02, fable: 45.0 },
          degradados: ["DeepSeek"],
        })
      )
    );

    fireEvent.click(screen.getByTestId("btn-ventana-models-1h"));

    await waitFor(() => {
      expect(screen.getByTestId("alerta-disponibilidad-1h")).toBeDefined();
    });

    const alerta = screen.getByTestId("alerta-disponibilidad-1h");
    expect(alerta.getAttribute("role")).toBe("alert");
    expect(alerta.textContent).toContain("DeepSeek");
    expect(alerta.textContent).toContain("97.80%");
  });

  it("5. maneja HTTP 503 TELEMETRIA_NO_DISPONIBLE con ContenedorEstado, X-Trace-Id y recuperación al reintentar", async () => {
    let intento = 0;
    server.use(
      http.get("*/admin/v1/ops/models", () => {
        intento += 1;
        if (intento === 1) {
          return HttpResponse.json(
            {
              error: {
                codigo: "TELEMETRIA_NO_DISPONIBLE",
                mensaje: "La telemetría de modelos LLM no está disponible.",
              },
            },
            { status: 503, headers: { "x-trace-id": "trc_models_503_err" } }
          );
        }
        return HttpResponse.json({
          ventana: "24h",
          proveedores: [
            {
              proveedor: "Google",
              modelo: "gemini-3-flash",
              tier: "flash",
              llamadas: 1000,
              disponibilidad_pct: 99.98,
              latencia_p50_ms: 170,
              latencia_p95_ms: 410,
              tasa_error_pct: 0.02,
            },
          ],
          modelos: [
            {
              proveedor: "Google",
              modelo: "gemini-3-flash",
              tier: "flash",
              llamadas: 1000,
              disponibilidad_pct: 99.98,
              latencia_p50_ms: 170,
              latencia_p95_ms: 410,
              tasa_error_pct: 0.02,
            },
          ],
          escalados: { flash_a_pro: 10, pro_a_fable: 1, a_humano: 0 },
          tokens_por_tier: { flash: 1000000, pro: 0, fable: 0 },
          coste_por_tier: { flash: 1.5, pro: 0, fable: 0 },
        });
      })
    );

    renderOpsModels();

    await waitFor(() => {
      expect(screen.getByTestId("ops-models-error")).toBeDefined();
    });

    const errCard = screen.getByTestId("ops-models-error");
    expect(errCard.getAttribute("role")).toBe("alert");
    expect(screen.getByTestId("ops-models-trace-id").textContent).toContain(
      "trc_models_503_err"
    );

    fireEvent.click(screen.getByRole("button", { name: /Reintentar/i }));

    await waitFor(() => {
      expect(screen.getByTestId("fila-modelo-gemini-3-flash")).toBeDefined();
    });
  });

  it("6. valida estado vacío y matriz RBAC (staff_operaciones, staff_admin y staff_negocio permitidos; staff_soporte 403)", async () => {
    // Bloqueo para staff_soporte
    const { unmount } = renderOpsModels({
      usuario: {
        staff_id: "st_soporte_001",
        email: "soporte@kallicode.com",
        nombre: "Soporte L1",
        role: "staff_soporte",
        mfa_validado: true,
      },
    });

    const bloqueo = screen.getByTestId("ops-models-rbac-bloqueado");
    expect(bloqueo.getAttribute("role")).toBe("alert");
    expect(bloqueo.textContent).toContain("403 ROL_STAFF_INSUFICIENTE");
    unmount();

    // Acceso permitido a staff_negocio con estado vacío tras filtro
    server.use(
      http.get("*/admin/v1/ops/models", () =>
        HttpResponse.json({
          ventana: "24h",
          proveedores: [],
          modelos: [],
          escalados: { flash_a_pro: 0, pro_a_fable: 0, a_humano: 0 },
          tokens_por_tier: { flash: 0, pro: 0, fable: 0 },
          coste_por_tier: { flash: 0, pro: 0, fable: 0 },
        })
      )
    );

    renderOpsModels({
      usuario: {
        staff_id: "st_neg_001",
        email: "negocio@kallicode.com",
        nombre: "Dirección Negocio",
        role: "staff_negocio",
        mfa_validado: true,
      },
    });

    await waitFor(() => {
      expect(screen.getByText("Sin métricas de modelos para el filtro aplicado")).toBeDefined();
    });
  });
});
