/**
 * BizOverview.test.tsx — Pruebas de componente para el Panel General de Negocio
 *
 * Valida:
 * 1. Renderizado de los 4 bloques principales de KPIs y distribución de planes vía MSW v2.
 * 2. Indicador de frescura normal (ACTIVO) vs alerta de antigüedad (> 6h) "WARN admin.business.frescura_alta".
 * 3. Actualización interactiva de filtros de rango temporal (periodo) y comparación.
 * 4. Estado de carga estructurado (skeleton loading) con accesibilidad (role="status", aria-busy="true").
 * 5. Manejo de error HTTP 503 con visualización de X-Trace-Id y reintento.
 * 6. Manejo de error HTTP 403 por respuesta del backend o por guarda RBAC de rol staff no autorizado.
 * 7. Semántica accesible (aria-live="polite", etiquetas asociadas).
 */

import { describe, it, expect } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { http, HttpResponse } from "msw";
import { server } from "../../pruebas/server";
import { setMockFrescura } from "../../pruebas/msw_handlers";
import { AuthProvider, UsuarioStaff } from "../../estado/auth";
import { BizOverview } from "../BizOverview";

function renderBizOverview(opciones?: { usuario?: UsuarioStaff }) {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
      },
    },
  });

  const usuarioNegocio: UsuarioStaff = opciones?.usuario ?? {
    staff_id: "st_negocio_001",
    email: "negocio@kallicode.com",
    nombre: "Staff Negocio",
    role: "staff_negocio",
    mfa_validado: true,
  };

  return render(
    <AuthProvider
      sesionInicial={{
        usuario: usuarioNegocio,
        token: "jwt_token_valido_negocio",
      }}
    >
      <QueryClientProvider client={queryClient}>
        <BizOverview />
      </QueryClientProvider>
    </AuthProvider>
  );
}

describe("BizOverview — Panel General de Negocio", () => {
  it("1. renderiza correctamente los 4 bloques principales de KPIs provistos por MSW", async () => {
    // Fijar frescura reciente (< 6 horas)
    setMockFrescura(new Date(Date.now() - 30 * 60 * 1000).toISOString());

    renderBizOverview();

    // 1. Estado inicial de carga (Skeleton Loading con accesibilidad)
    const loader = screen.getByTestId("overview-loading");
    expect(loader).toBeDefined();
    expect(loader.getAttribute("role")).toBe("status");
    expect(loader.getAttribute("aria-busy")).toBe("true");

    // Esperar a que TanStack Query procese la respuesta de MSW
    await waitFor(() => {
      expect(screen.getByText("Panel General de Negocio")).toBeDefined();
    });

    // 2. Bloque 1: Ingreso Recurrente Mensual (MRR con variación y moneda)
    const kpiMrr = screen.getByTestId("kpi-mrr");
    expect(kpiMrr.textContent).toContain("45.000");
    expect(kpiMrr.textContent).toContain("EUR");
    expect(kpiMrr.textContent).toContain("+12.5%");

    // 3. Bloque 2: Clientes Activos (total, altas, cancelaciones)
    const kpiClientes = screen.getByTestId("kpi-clientes-activos");
    expect(kpiClientes.textContent).toContain("128");
    expect(kpiClientes.textContent).toContain("+14 altas");
    expect(kpiClientes.textContent).toContain("-2 cancelaciones");

    // 4. Bloque 3: Consumo Agregado de Plataforma (Tokens, LOC y coste estimado)
    const kpiTokens = screen.getByTestId("kpi-tokens");
    expect(kpiTokens.textContent).toContain("125.000.000");
    expect(kpiTokens.textContent).toContain("320.000 LOC");
    expect(kpiTokens.textContent).toContain("Coste:");

    // 5. Bloque 4: Rendimiento del Pipeline (Tickets, p50 y tasa de escalado)
    const kpiPipeline = screen.getByTestId("kpi-pipeline");
    expect(kpiPipeline.textContent).toContain("450");
    expect(kpiPipeline.textContent).toContain("p50: 2.4h");
    expect(kpiPipeline.textContent).toContain("4.5%");

    // 6. Distribución por planes
    expect(screen.getByTestId("plan-starter")).toBeDefined();
    expect(screen.getByTestId("plan-growth")).toBeDefined();
    expect(screen.getByTestId("plan-enterprise")).toBeDefined();

    // 7. Accesibilidad del contenedor principal
    const contenedorPrincipal = screen.getByRole("main");
    expect(contenedorPrincipal.getAttribute("aria-live")).toBe("polite");
  });

  it("2. muestra insignia ACTIVO cuando la frescura es reciente (< 6 horas)", async () => {
    // 2 horas de antigüedad
    const fechaReciente = new Date(Date.now() - 2 * 60 * 60 * 1000).toISOString();
    setMockFrescura(fechaReciente);

    renderBizOverview();

    await waitFor(() => {
      expect(screen.getByTestId("badge-frescura-ok")).toBeDefined();
    });

    expect(screen.getByText("ACTIVO")).toBeDefined();
    expect(screen.queryByTestId("badge-frescura-warn")).toBeNull();
  });

  it("3. muestra advertencia 'WARN admin.business.frescura_alta' cuando la antigüedad supera las 6 horas", async () => {
    // 8 horas de antigüedad
    const fechaAntigua = new Date(Date.now() - 8 * 60 * 60 * 1000).toISOString();
    setMockFrescura(fechaAntigua);

    renderBizOverview();

    await waitFor(() => {
      expect(screen.getByTestId("badge-frescura-warn")).toBeDefined();
    });

    expect(screen.getByText("WARN admin.business.frescura_alta")).toBeDefined();
    expect(screen.queryByTestId("badge-frescura-ok")).toBeNull();
  });

  it("4. permite cambiar el periodo y la comparación actualizando las métricas sin recargar la página", async () => {
    setMockFrescura(new Date().toISOString());
    renderBizOverview();

    await waitFor(() => {
      expect(screen.getByTestId("kpi-mrr")).toBeDefined();
    });

    expect(screen.getByTestId("kpi-mrr").textContent).toContain("45.000");

    // Cambiar selector de periodo a "trimestre"
    const selectorPeriodo = screen.getByLabelText("Periodo");
    fireEvent.change(selectorPeriodo, { target: { value: "trimestre" } });

    // Esperar a que la consulta TanStack Query se actualice con los datos del trimestre
    await waitFor(() => {
      expect(screen.getByTestId("kpi-mrr").textContent).toContain("135.000");
    });

    expect(screen.getByTestId("kpi-pipeline").textContent).toContain("1320");

    // Cambiar selector de comparación
    const selectorComparacion = screen.getByLabelText("Comparar con");
    fireEvent.change(selectorComparacion, { target: { value: "mismo_periodo_ano_anterior" } });

    // Botón de refresco manual
    await waitFor(() => {
      const botonRefrescar = screen.getByLabelText("Refrescar métricas de negocio");
      expect(botonRefrescar).toBeDefined();
      fireEvent.click(botonRefrescar);
    });
  });

  it("5. muestra tarjeta de error accionable con X-Trace-Id ante HTTP 503 AGREGADO_NO_DISPONIBLE", async () => {
    server.use(
      http.get("*/admin/v1/business/overview", () => {
        return HttpResponse.json(
          {
            error: {
              codigo: "AGREGADO_NO_DISPONIBLE",
              code: "agregado_no_disponible",
              mensaje: "Los agregados de negocio están recalculándose en PostgreSQL.",
              trace_id: "trc_503_test_run",
            },
          },
          {
            status: 503,
            headers: {
              "x-trace-id": "trc_503_test_run",
            },
          }
        );
      })
    );

    renderBizOverview();

    await waitFor(() => {
      expect(screen.getByTestId("overview-error")).toBeDefined();
    });

    expect(screen.getByText("AGREGADOS EN REFRESCO")).toBeDefined();
    expect(
      screen.getByText(/Los agregados de negocio están recalculándose/)
    ).toBeDefined();

    // Verificación de visualización del X-Trace-Id
    const traceIdBox = screen.getByTestId("overview-trace-id");
    expect(traceIdBox.textContent).toContain("trc_503_test_run");

    // Botón de reintento
    const botonReintento = screen.getByText("Reintentar consulta");
    expect(botonReintento).toBeDefined();
    fireEvent.click(botonReintento);
  });

  it("6. muestra tarjeta de acceso denegado ante error HTTP 403 ROL_STAFF_INSUFICIENTE de la API", async () => {
    server.use(
      http.get("*/admin/v1/business/overview", () => {
        return HttpResponse.json(
          {
            error: {
              codigo: "ROL_STAFF_INSUFICIENTE",
              code: "rol_staff_insuficiente",
              mensaje: "Acceso denegado para el personal de operaciones.",
              trace_id: "trc_403_test_forbidden",
            },
          },
          {
            status: 403,
            headers: {
              "x-trace-id": "trc_403_test_forbidden",
            },
          }
        );
      })
    );

    renderBizOverview();

    await waitFor(() => {
      expect(screen.getByTestId("overview-error")).toBeDefined();
    });

    expect(screen.getByText("ACCESO DENEGADO")).toBeDefined();
    expect(
      screen.getByText("Acceso denegado para el personal de operaciones.")
    ).toBeDefined();
  });

  it("7. bloquea visualmente el acceso si el rol del staff en sesión no es negocio ni admin", () => {
    const usuarioOperaciones: UsuarioStaff = {
      staff_id: "st_ops_999",
      email: "ops@kallicode.com",
      nombre: "Operador de Infraestructura",
      role: "staff_operaciones",
      mfa_validado: true,
    };

    renderBizOverview({ usuario: usuarioOperaciones });

    expect(screen.getByTestId("overview-error")).toBeDefined();
    expect(screen.getByText("ACCESO DENEGADO")).toBeDefined();
    expect(screen.getByText("403 ROL_STAFF_INSUFICIENTE")).toBeDefined();
    expect(screen.getByText(/Acceso denegado para el rol staff_operaciones/)).toBeDefined();
  });
});
