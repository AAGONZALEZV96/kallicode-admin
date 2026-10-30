/**
 * BizOverview.test.tsx — Pruebas de componente para el Panel General de Negocio
 *
 * Valida el consumo del doble de API MSW v2, el renderizado de KPIs ejecutivos
 * y los estados de error accionables sin requerir el backend FastAPI.
 */

import React from "react";
import { describe, it, expect } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { http, HttpResponse } from "msw";
import { server } from "../../pruebas/server";
import { BizOverview } from "../BizOverview";

function renderConQueryClient(componente: React.ReactElement) {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
      },
    },
  });

  return render(
    <QueryClientProvider client={queryClient}>
      {componente}
    </QueryClientProvider>
  );
}

describe("BizOverview con dobles de API MSW", () => {
  it("renderiza correctamente los KPIs comerciales provistos por el mock de MSW", async () => {
    renderConQueryClient(<BizOverview />);

    // Verifica estado inicial de carga
    expect(screen.getByTestId("overview-loading")).toBeDefined();

    // Espera a que los datos de MSW sean procesados y renderizados
    await waitFor(() => {
      expect(screen.getByText("Panel General de Negocio")).toBeDefined();
    });

    // 1. KPI MRR
    const kpiMrr = screen.getByTestId("kpi-mrr");
    expect(kpiMrr.textContent).toContain("45.000");

    // 2. KPI Clientes Activos
    const kpiClientes = screen.getByTestId("kpi-clientes-activos");
    expect(kpiClientes.textContent).toContain("128");

    // 3. KPI Tokens
    const kpiTokens = screen.getByTestId("kpi-tokens");
    expect(kpiTokens.textContent).toContain("125.000.000");

    // 4. KPI Pipeline
    const kpiPipeline = screen.getByTestId("kpi-pipeline");
    expect(kpiPipeline.textContent).toContain("450");

    // 5. Distribución por planes
    expect(screen.getByText("starter")).toBeDefined();
    expect(screen.getByText("growth")).toBeDefined();
    expect(screen.getByText("enterprise")).toBeDefined();
  });

  it("muestra estado de error estructurado ante HTTP 503 AGREGADO_NO_DISPONIBLE", async () => {
    // Sobrescribir handler de overview para simular agregados obsoletos o en refresco
    server.use(
      http.get("*/admin/v1/business/overview", () => {
        return HttpResponse.json(
          {
            error: {
              codigo: "AGREGADO_NO_DISPONIBLE",
              code: "agregado_no_disponible",
              mensaje: "Los agregados de negocio están recalculándose en PostgreSQL.",
            },
          },
          { status: 503 }
        );
      })
    );

    renderConQueryClient(<BizOverview />);

    await waitFor(() => {
      expect(screen.getByTestId("overview-error")).toBeDefined();
    });

    expect(screen.getByText("AGREGADOS EN REFRESCO")).toBeDefined();
    expect(
      screen.getByText(/Los agregados de negocio están recalculándose/)
    ).toBeDefined();
    expect(screen.getByText("Reintentar consulta")).toBeDefined();
  });

  it("muestra mensaje de denegación ante HTTP 403 ROL_STAFF_INSUFICIENTE", async () => {
    // Sobrescribir handler de overview para simular rol insuficiente
    server.use(
      http.get("*/admin/v1/business/overview", () => {
        return HttpResponse.json(
          {
            error: {
              codigo: "ROL_STAFF_INSUFICIENTE",
              code: "rol_staff_insuficiente",
              mensaje: "Acceso denegado para el rol staff_operaciones.",
            },
          },
          { status: 403 }
        );
      })
    );

    renderConQueryClient(<BizOverview />);

    await waitFor(() => {
      expect(screen.getByTestId("overview-error")).toBeDefined();
    });

    expect(screen.getByText("ACCESO DENEGADO")).toBeDefined();
    expect(
      screen.getByText("Acceso denegado para el rol staff_operaciones.")
    ).toBeDefined();
  });
});
