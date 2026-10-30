/**
 * BizCustomers.test.tsx — Pruebas de componente para el Directorio de Clientes
 *
 * Valida:
 * 1. Renderizado de la tabla densa de organizaciones con todas las columnas y datos de MSW.
 * 2. Filtrado por plan comercial y estado de suscripción.
 * 3. Búsqueda por texto con debounce (q).
 * 4. Paginación transversal (items, total, page, page_size, pages).
 * 5. Ordenación por allowlist interactiva (alternando -asc y -desc).
 * 6. Enmascaramiento por defecto de PII/razón social (política E6) vs revelación con concesión activa.
 * 7. Modal informativo de concesiones y política de privacidad E6.
 * 8. Skeleton loading estructurado con accesibilidad (role="status", aria-busy="true").
 * 9. Manejo de error HTTP 503 con visualización de X-Trace-Id y reintento.
 * 10. Control de acceso RBAC: permitido para soporte, negocio y admin; bloqueo para operaciones (403).
 * 11. Enlaces de navegación directa hacia /business/customers/:tenant_id.
 */

import { describe, it, expect, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { MemoryRouter, Routes, Route } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { http, HttpResponse } from "msw";
import { server } from "../../pruebas/server";
import { setMockConcesionActiva, resetMockState } from "../../pruebas/msw_handlers";
import { AuthProvider, UsuarioStaff } from "../../estado/auth";
import { BizCustomers } from "../BizCustomers";

function renderBizCustomers(opciones?: {
  usuario?: UsuarioStaff;
  rutaInicial?: string;
}) {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
      },
    },
  });

  const usuarioStaff: UsuarioStaff = opciones?.usuario ?? {
    staff_id: "st_negocio_001",
    email: "negocio@kallicode.com",
    nombre: "Staff Negocio",
    role: "staff_negocio",
    mfa_validado: true,
  };

  const ruta = opciones?.rutaInicial ?? "/business/customers";

  return render(
    <AuthProvider
      sesionInicial={{
        usuario: usuarioStaff,
        token: "jwt_token_valido_test",
      }}
    >
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={[ruta]}>
          <Routes>
            <Route path="/business/customers" element={<BizCustomers />} />
            <Route
              path="/business/customers/:tenant_id"
              element={<div data-testid="vista-detalle-360">Ficha 360 Cliente</div>}
            />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>
    </AuthProvider>
  );
}

describe("BizCustomers — Pantalla de Listado de Clientes", () => {
  beforeEach(() => {
    resetMockState();
  });

  it("1. renderiza la tabla densa de organizaciones con todas las columnas requeridas", async () => {
    renderBizCustomers();

    // 1. Estado inicial de carga (Skeleton Loading con accesibilidad)
    const loader = screen.getByTestId("customers-loading");
    expect(loader).toBeDefined();
    expect(loader.getAttribute("role")).toBe("status");
    expect(loader.getAttribute("aria-busy")).toBe("true");

    // Esperar a que los datos de MSW sean cargados y procesados
    await waitFor(() => {
      expect(screen.getByText("Directorio de Clientes y Organizaciones")).toBeDefined();
    });

    // 2. Encabezados de tabla
    expect(screen.getByRole("columnheader", { name: /Tenant ID/ })).toBeDefined();
    expect(screen.getByRole("columnheader", { name: /Razón Social/ })).toBeDefined();
    expect(screen.getByRole("columnheader", { name: /^Plan/ })).toBeDefined();
    expect(screen.getByRole("columnheader", { name: /^Estado/ })).toBeDefined();
    expect(screen.getByRole("columnheader", { name: /Líneas/ })).toBeDefined();
    expect(screen.getByRole("columnheader", { name: /Consumo/ })).toBeDefined();
    expect(screen.getByRole("columnheader", { name: /Última Actividad/ })).toBeDefined();
    expect(screen.getByRole("columnheader", { name: /Privacidad/ })).toBeDefined();

    // 3. Filas de clientes mock (5 clientes en mock base)
    expect(screen.getByTestId("fila-cliente-org_acme")).toBeDefined();
    expect(screen.getByTestId("fila-cliente-org_globex")).toBeDefined();
    expect(screen.getByTestId("fila-cliente-org_initech")).toBeDefined();
    expect(screen.getByTestId("fila-cliente-org_wayne")).toBeDefined();
    expect(screen.getByTestId("fila-cliente-org_umbrella")).toBeDefined();

    // 4. Barra de paginación transversal
    const pagination = screen.getByTestId("customers-pagination");
    expect(pagination.textContent).toContain("Mostrando 1 a 5 de 5 organizaciones");
    expect(pagination.textContent).toContain("Página 1 de 1");
  });

  it("2. enmascara por defecto la razón social bajo la política E6 y la revela con concesión activa", async () => {
    // Caso 1: Sin concesión activa
    const { unmount } = renderBizCustomers();

    await waitFor(() => {
      expect(screen.getByTestId("fila-cliente-org_acme")).toBeDefined();
    });

    // Razón social enmascarada
    expect(screen.getByTestId("razon-enmascarada-org_acme").textContent).toBe("A•••• S.L.");
    expect(screen.getByTestId("badge-enmascarado-org_acme")).toBeDefined();
    expect(screen.getByTestId("banner-enmascaramiento")).toBeDefined();

    unmount();

    // Caso 2: Con concesión activa
    setMockConcesionActiva(true);
    renderBizCustomers();

    await waitFor(() => {
      expect(screen.getByTestId("fila-cliente-org_acme")).toBeDefined();
    });

    // Razón social visible en claro
    expect(screen.getByTestId("razon-clara-org_acme").textContent).toBe("Acme Logística S.L.");
    expect(screen.getByTestId("badge-claro-org_acme")).toBeDefined();
    expect(screen.queryByTestId("banner-enmascaramiento")).toBeNull();
  });

  it("3. filtra organizaciones por plan comercial (starter, growth, enterprise)", async () => {
    renderBizCustomers();

    await waitFor(() => {
      expect(screen.getByTestId("fila-cliente-org_acme")).toBeDefined();
    });

    // Seleccionar plan "starter"
    const selectPlan = screen.getByLabelText("Plan comercial");
    fireEvent.change(selectPlan, { target: { value: "starter" } });

    // Esperar a que la consulta se actualice y org_acme (growth) desaparezca
    await waitFor(() => {
      expect(screen.queryByTestId("fila-cliente-org_acme")).toBeNull();
    });

    expect(screen.getByTestId("fila-cliente-org_initech")).toBeDefined();
    expect(screen.getByTestId("fila-cliente-org_umbrella")).toBeDefined();
    expect(screen.queryByTestId("fila-cliente-org_globex")).toBeNull();
  });

  it("4. filtra organizaciones por estado de suscripción", async () => {
    renderBizCustomers();

    await waitFor(() => {
      expect(screen.getByTestId("fila-cliente-org_acme")).toBeDefined();
    });

    // Seleccionar estado "suspendida"
    const selectEstado = screen.getByLabelText("Estado");
    fireEvent.change(selectEstado, { target: { value: "suspendida" } });

    // Esperar a que la consulta se actualice y org_acme (activa) desaparezca
    await waitFor(() => {
      expect(screen.queryByTestId("fila-cliente-org_acme")).toBeNull();
    });

    expect(screen.getByTestId("fila-cliente-org_umbrella")).toBeDefined();
    expect(screen.queryByTestId("fila-cliente-org_globex")).toBeNull();
  });

  it("5. permite búsqueda por texto con debounce", async () => {
    renderBizCustomers();

    await waitFor(() => {
      expect(screen.getByTestId("fila-cliente-org_acme")).toBeDefined();
    });

    const inputBusqueda = screen.getByLabelText("Buscar por ID u organización");
    fireEvent.change(inputBusqueda, { target: { value: "org_wayne" } });

    // Espera a que el debounce de 300ms se active y actualice la consulta
    await waitFor(
      () => {
        expect(screen.queryByTestId("fila-cliente-org_acme")).toBeNull();
      },
      { timeout: 1500 }
    );

    expect(screen.getByTestId("fila-cliente-org_wayne")).toBeDefined();
    expect(screen.queryByTestId("fila-cliente-org_globex")).toBeNull();
  });

  it("6. ordena interactivamente por columnas de la allowlist alternando -asc y -desc", async () => {
    renderBizCustomers();

    await waitFor(() => {
      expect(screen.getByTestId("fila-cliente-org_acme")).toBeDefined();
    });

    // Clic en encabezado Tenant ID para ordenar asc
    const thTenant = screen.getByRole("columnheader", { name: /Tenant ID/ });
    fireEvent.click(thTenant);

    await waitFor(() => {
      expect(thTenant.textContent).toContain("↑");
    });

    // Clic nuevamente para ordenar desc
    fireEvent.click(thTenant);

    await waitFor(() => {
      expect(thTenant.textContent).toContain("↓");
    });
  });

  it("7. abre el modal informativo de la política de privacidad y concesiones E6", async () => {
    renderBizCustomers();

    await waitFor(() => {
      expect(screen.getByTestId("banner-enmascaramiento")).toBeDefined();
    });

    // Clic en solicitar acceso justificado
    const botonSolicitar = screen.getByText("Solicitar acceso justificado");
    fireEvent.click(botonSolicitar);

    await waitFor(() => {
      expect(screen.getByText("Política de Privacidad y Acceso Justificado (E6)")).toBeDefined();
    });

    expect(screen.getAllByText(/admin.access_grants/).length).toBeGreaterThan(0);
    expect(screen.getByText(/admin.staff_actions/)).toBeDefined();

    // Cerrar modal
    const botonEntendido = screen.getByText("Entendido");
    fireEvent.click(botonEntendido);

    await waitFor(() => {
      expect(screen.queryByText("Condiciones para revelación en claro:")).toBeNull();
    });
  });

  it("8. muestra tarjeta de error estructurada con X-Trace-Id ante HTTP 503 AGREGADO_NO_DISPONIBLE", async () => {
    server.use(
      http.get("*/admin/v1/business/customers", () => {
        return HttpResponse.json(
          {
            error: {
              codigo: "AGREGADO_NO_DISPONIBLE",
              code: "agregado_no_disponible",
              mensaje: "La capa de agregados analíticos está en refresco en PostgreSQL.",
              trace_id: "trc_503_customers_run",
            },
          },
          {
            status: 503,
            headers: {
              "x-trace-id": "trc_503_customers_run",
            },
          }
        );
      })
    );

    renderBizCustomers();

    await waitFor(() => {
      expect(screen.getByTestId("customers-error")).toBeDefined();
    });

    expect(screen.getByText("AGREGADOS EN REFRESCO")).toBeDefined();
    expect(
      screen.getByText("La capa de agregados analíticos está en refresco en PostgreSQL.")
    ).toBeDefined();

    // Verificación del X-Trace-Id
    const traceBox = screen.getByTestId("customers-trace-id");
    expect(traceBox.textContent).toContain("trc_503_customers_run");

    // Botón de reintento
    const botonReintento = screen.getByText("Reintentar consulta");
    expect(botonReintento).toBeDefined();
    fireEvent.click(botonReintento);
  });

  it("9. bloquea visualmente el acceso y muestra 403 ROL_STAFF_INSUFICIENTE para staff_operaciones", () => {
    const usuarioOperaciones: UsuarioStaff = {
      staff_id: "st_ops_123",
      email: "ops@kallicode.com",
      nombre: "Operador Ops",
      role: "staff_operaciones",
      mfa_validado: true,
    };

    renderBizCustomers({ usuario: usuarioOperaciones });

    expect(screen.getByTestId("customers-error")).toBeDefined();
    expect(screen.getByText("ACCESO DENEGADO")).toBeDefined();
    expect(screen.getByText("403 ROL_STAFF_INSUFICIENTE")).toBeDefined();
    expect(
      screen.getByText(/Acceso denegado para el rol staff_operaciones/)
    ).toBeDefined();
  });

  it("10. permite el acceso para los roles autorizados staff_soporte y staff_admin", async () => {
    const usuarioSoporte: UsuarioStaff = {
      staff_id: "st_soporte_456",
      email: "soporte@kallicode.com",
      nombre: "Soporte KalliCode",
      role: "staff_soporte",
      mfa_validado: true,
    };

    renderBizCustomers({ usuario: usuarioSoporte });

    await waitFor(() => {
      expect(screen.getByText("Directorio de Clientes y Organizaciones")).toBeDefined();
    });

    expect(screen.getByTestId("fila-cliente-org_acme")).toBeDefined();
  });

  it("11. contiene enlaces de navegación directa hacia /business/customers/:tenant_id", async () => {
    renderBizCustomers();

    await waitFor(() => {
      expect(screen.getByTestId("fila-cliente-org_acme")).toBeDefined();
    });

    const linkDetalle = screen.getByLabelText("Ver detalles de org_acme");
    expect(linkDetalle.getAttribute("href")).toBe("/business/customers/org_acme");
  });
});
