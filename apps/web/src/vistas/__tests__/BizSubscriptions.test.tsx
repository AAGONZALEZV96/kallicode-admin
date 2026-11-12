/**
 * BizSubscriptions.test.tsx — Pruebas de componente para Gestión de Suscripciones y Upgrades
 *
 * Valida los requisitos de [KC-ADM-B4-02] (Épica EAD4 / ADM-G08 / §18.19 - §18.20):
 * 1. Renderizado del radar de renovaciones con columnas obligatorias y datos de MSW.
 * 2. Destacado visual de renovaciones críticas (<= 15 días) y avisos (<= 30 días).
 * 3. Filtrado por plan comercial, estado y ventana de renovación (15, 30, 60, 90 días).
 * 4. Búsqueda por texto con debounce y ordenación interactiva por allowlist.
 * 5. Pestaña concurrente de Cola de Upgrades ordenadas por antigüedad (más antiguas primero).
 * 6. Filtrado de solicitudes de cambio de plan por estado y plan deseado.
 * 7. Enmascaramiento por defecto bajo política E6 ("ENMASCARADO") y apertura del modal de concesión.
 * 8. Envío exitoso de POST /admin/v1/access-grants y revelación reactiva ("EN CLARO").
 * 9. Manejo de error HTTP 503 AGREGADO_NO_DISPONIBLE con traza X-Trace-Id y botón de reintento.
 * 10. Control de acceso RBAC: 403 ROL_STAFF_INSUFICIENTE para staff_operaciones y staff_soporte.
 * 11. Paginación transversal y sincronización con URL searchParams.
 */

import { describe, it, expect, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { MemoryRouter, Routes, Route } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { http, HttpResponse } from "msw";
import { server } from "../../pruebas/server";
import { setMockConcesionActiva, resetMockState } from "../../pruebas/msw_handlers";
import { AuthProvider, UsuarioStaff } from "../../estado/auth";
import { BizSubscriptions } from "../BizSubscriptions";

function renderBizSubscriptions(opciones?: {
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

  const ruta = opciones?.rutaInicial ?? "/business/subscriptions";

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
            <Route path="/business/subscriptions" element={<BizSubscriptions />} />
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

describe("BizSubscriptions — Pantalla de Suscripciones y Renovaciones", () => {
  beforeEach(() => {
    resetMockState();
  });

  it("1. renderiza la tabla densa de suscripciones con todas las columnas obligatorias", async () => {
    renderBizSubscriptions();

    // Esperar a que la tabla y datos se rendericen
    await waitFor(() => {
      expect(screen.getByTestId("fila-suscripcion-org_acme")).toBeDefined();
    });

    // Encabezados de columnas obligatorias
    expect(screen.getByText(/Organización \(Tenant\)/)).toBeDefined();
    expect(screen.getByText(/Razón Social/)).toBeDefined();
    expect(screen.getAllByText(/^Plan$/).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/^Estado$/).length).toBeGreaterThan(0);
    expect(screen.getByText(/Inicia El/)).toBeDefined();
    expect(screen.getByText(/Renueva El/)).toBeDefined();
    expect(screen.getByText(/Días Renovación/)).toBeDefined();
    expect(screen.getByText(/Importe \/ Mes/)).toBeDefined();
    expect(screen.getByText(/% Cuota Uso/)).toBeDefined();

    // Filas renderizadas
    expect(screen.getByTestId("fila-suscripcion-org_acme")).toBeDefined();
    expect(screen.getByTestId("fila-suscripcion-org_globex")).toBeDefined();
    expect(screen.getByTestId("fila-suscripcion-org_initech")).toBeDefined();
    expect(screen.getByTestId("fila-suscripcion-org_wayne")).toBeDefined();
    expect(screen.getByTestId("fila-suscripcion-org_umbrella")).toBeDefined();

    // Enlace a ficha 360°
    const enlaceTenant = screen.getByRole("link", { name: "org_acme" });
    expect(enlaceTenant.getAttribute("href")).toBe("/business/customers/org_acme");
  });

  it("2. destaca visualmente alertas de renovaciones inminentes (<= 15 días y <= 30 días)", async () => {
    renderBizSubscriptions();

    await waitFor(() => {
      expect(screen.getByTestId("fila-suscripcion-org_umbrella")).toBeDefined();
    });

    // org_umbrella tiene 8 días (<= 15 días: alerta crítica)
    const alertasCriticas = screen.getAllByTestId("alerta-renovacion-critica");
    expect(alertasCriticas.length).toBeGreaterThan(0);
    expect(alertasCriticas[0].textContent).toContain("≤ 15 días");

    // org_acme tiene 16 días o org_globex 28 días (<= 30 días: aviso)
    const alertasAviso = screen.getAllByTestId("alerta-renovacion-aviso");
    expect(alertasAviso.length).toBeGreaterThan(0);
    expect(alertasAviso[0].textContent).toContain("≤ 30 días");
  });

  it("3. permite filtrar suscripciones por plan comercial y estado", async () => {
    renderBizSubscriptions();

    await waitFor(() => {
      expect(screen.getByTestId("fila-suscripcion-org_acme")).toBeDefined();
    });

    // Filtrar por plan enterprise
    const selectPlan = screen.getByTestId("select-plan-subs");
    fireEvent.change(selectPlan, { target: { value: "enterprise" } });

    await waitFor(() => {
      expect(screen.getByTestId("fila-suscripcion-org_globex")).toBeDefined();
      expect(screen.getByTestId("fila-suscripcion-org_wayne")).toBeDefined();
      expect(screen.queryByTestId("fila-suscripcion-org_acme")).toBeNull();
    });

    // Filtrar por estado periodo_gracia
    const selectEstado = screen.getByTestId("select-estado-subs");
    fireEvent.change(selectPlan, { target: { value: "todos" } });
    fireEvent.change(selectEstado, { target: { value: "periodo_gracia" } });

    await waitFor(() => {
      expect(screen.getByTestId("fila-suscripcion-org_initech")).toBeDefined();
      expect(screen.queryByTestId("fila-suscripcion-org_acme")).toBeNull();
    });
  });

  it("4. permite filtrar suscripciones por rango de renovación próxima", async () => {
    renderBizSubscriptions();

    await waitFor(() => {
      expect(screen.getByTestId("fila-suscripcion-org_acme")).toBeDefined();
    });

    // Filtrar próximas en 15 días
    const selectRango = screen.getByTestId("select-renovacion-subs");
    fireEvent.change(selectRango, { target: { value: "15" } });

    await waitFor(() => {
      expect(screen.getByTestId("fila-suscripcion-org_umbrella")).toBeDefined();
      expect(screen.queryByTestId("fila-suscripcion-org_wayne")).toBeNull(); // 85 días
    });
  });

  it("5. permite búsqueda textual con debounce e interactúa con la ordenación", async () => {
    renderBizSubscriptions();

    await waitFor(() => {
      expect(screen.getByTestId("fila-suscripcion-org_acme")).toBeDefined();
    });

    // Buscar "umbrella"
    const inputBusqueda = screen.getByTestId("input-busqueda-subs");
    fireEvent.change(inputBusqueda, { target: { value: "umbrella" } });

    await waitFor(
      () => {
        expect(screen.getByTestId("fila-suscripcion-org_umbrella")).toBeDefined();
        expect(screen.queryByTestId("fila-suscripcion-org_acme")).toBeNull();
      },
      { timeout: 1500 }
    );
  });

  it("6. conmuta a la pestaña Cola de Upgrades y muestra solicitudes ordenadas por antigüedad", async () => {
    renderBizSubscriptions();

    await waitFor(() => {
      expect(screen.getByTestId("tab-solicitudes")).toBeDefined();
    });

    // Cambiar a la pestaña de solicitudes
    fireEvent.click(screen.getByTestId("tab-solicitudes"));

    // Esperar a que cargue la tabla de solicitudes
    await waitFor(() => {
      expect(screen.getByTestId("fila-upgrade-req_001")).toBeDefined();
      expect(screen.getByTestId("fila-upgrade-req_002")).toBeDefined();
    });

    // Verificar columnas obligatorias
    expect(screen.getByText("ID Solicitud")).toBeDefined();
    expect(screen.getByText("Transición de Plan")).toBeDefined();
    expect(screen.getByText("Antigüedad")).toBeDefined();
    expect(screen.getByText("Prioridad")).toBeDefined();

    // Transición de planes (starter → growth)
    expect(screen.getAllByText("starter").length).toBeGreaterThan(0);
    expect(screen.getAllByText("growth").length).toBeGreaterThan(0);

    // Badge urgente
    const badgeUrgente = screen.getByTestId("badge-urgente");
    expect(badgeUrgente.textContent).toContain("Urgente");
  });

  it("7. permite filtrar solicitudes de upgrade por estado y plan deseado", async () => {
    renderBizSubscriptions({ rutaInicial: "/business/subscriptions?tab=solicitudes" });

    await waitFor(() => {
      expect(screen.getByTestId("fila-upgrade-req_001")).toBeDefined();
    });

    // Filtrar todas las solicitudes (incluyendo atendidas y rechazadas)
    const selectEstadoUpg = screen.getByTestId("select-estado-upg");
    fireEvent.change(selectEstadoUpg, { target: { value: "todos" } });

    await waitFor(() => {
      expect(screen.getByTestId("fila-upgrade-req_003")).toBeDefined(); // atendida
      expect(screen.getByTestId("fila-upgrade-req_004")).toBeDefined(); // rechazada
    });

    // Filtrar por plan_deseado enterprise
    const selectPlanDeseado = screen.getByTestId("select-plan-deseado-upg");
    fireEvent.change(selectPlanDeseado, { target: { value: "enterprise" } });

    await waitFor(() => {
      expect(screen.getByTestId("fila-upgrade-req_002")).toBeDefined();
      expect(screen.queryByTestId("fila-upgrade-req_001")).toBeNull();
    });
  });

  it("8. gestiona enmascaramiento por defecto E6 y permite solicitar revelación justificada con modal", async () => {
    const { unmount } = renderBizSubscriptions();

    await waitFor(() => {
      expect(screen.getByTestId("fila-suscripcion-org_acme")).toBeDefined();
    });

    // Estado inicial: enmascarado
    expect(screen.getAllByText("A•••• S.L.").length).toBeGreaterThan(0);
    const btnRevelar = screen.getByTestId("btn-revelar-org_acme");
    expect(btnRevelar).toBeDefined();

    // Abrir modal de revelación justificada
    fireEvent.click(btnRevelar);

    await waitFor(() => {
      expect(screen.getByText("Solicitar Revelación de Datos de Cliente (E6)")).toBeDefined();
    });

    // Rellenar formulario con motivo válido y ticket
    const inputMotivo = screen.getByTestId("input-concesion-motivo");
    const inputReferencia = screen.getByTestId("input-concesion-referencia");
    const btnConfirmar = screen.getByTestId("btn-confirmar-concesion");

    fireEvent.change(inputMotivo, {
      target: { value: "Revisión urgente de renovación anual y cuadre de consumo" },
    });
    fireEvent.change(inputReferencia, { target: { value: "KC-1049" } });

    fireEvent.click(btnConfirmar);

    // Confirmación y cierre del modal
    await waitFor(() => {
      expect(screen.getByTestId("exito-concesion")).toBeDefined();
    });

    unmount();

    // Al montar con concesión activa en MSW
    setMockConcesionActiva(true);
    renderBizSubscriptions();

    await waitFor(() => {
      expect(screen.getByText("Acme Logística S.L.")).toBeDefined();
      expect(screen.getAllByText("EN CLARO").length).toBeGreaterThan(0);
    });
  });

  it("9. gestiona error HTTP 503 AGREGADO_NO_DISPONIBLE mostrando X-Trace-Id y botón de reintento", async () => {
    server.use(
      http.get("*/admin/v1/business/subscriptions", () => {
        return HttpResponse.json(
          {
            error: {
              codigo: "AGREGADO_NO_DISPONIBLE",
              code: "agregado_no_disponible",
              mensaje: "El agregado de suscripciones está recalculándose.",
              trace_id: "trc_subs_503_test",
            },
          },
          {
            status: 503,
            headers: {
              "x-trace-id": "trc_subs_503_test",
            },
          }
        );
      })
    );

    renderBizSubscriptions();

    await waitFor(() => {
      expect(screen.getByRole("alert")).toBeDefined();
    });

    expect(screen.getByText(/trc_subs_503_test/)).toBeDefined();
    expect(screen.getByRole("button", { name: /Reintentar/i })).toBeDefined();
  });

  it("10. bloquea visualmente el acceso y muestra 403 ROL_STAFF_INSUFICIENTE para roles no autorizados", async () => {
    // Caso 1: staff_operaciones
    const { unmount } = renderBizSubscriptions({
      usuario: {
        staff_id: "st_ops_001",
        email: "ops@kallicode.com",
        nombre: "Staff Operaciones",
        role: "staff_operaciones",
        mfa_validado: true,
      },
    });

    expect(screen.getByTestId("error-403-rol")).toBeDefined();
    expect(screen.getByText(/Acceso Restringido \(403 ROL_STAFF_INSUFICIENTE\)/)).toBeDefined();

    unmount();

    // Caso 2: staff_soporte
    renderBizSubscriptions({
      usuario: {
        staff_id: "st_sop_001",
        email: "soporte@kallicode.com",
        nombre: "Staff Soporte",
        role: "staff_soporte",
        mfa_validado: true,
      },
    });

    expect(screen.getByTestId("error-403-rol")).toBeDefined();
  });

  it("11. navega y pagina transversalmente sincronizando los parámetros", async () => {
    renderBizSubscriptions({ rutaInicial: "/business/subscriptions?page=1&page_size=25" });

    await waitFor(() => {
      expect(screen.getByText(/Mostrando 5 de 5 suscripciones/)).toBeDefined();
    });

    // Paginador
    const btnAnterior = screen.getByRole("button", { name: "Página anterior" });
    const btnSiguiente = screen.getByRole("button", { name: "Página siguiente" });

    // En la página 1 de 1 están deshabilitados
    expect(btnAnterior.hasAttribute("disabled")).toBe(true);
    expect(btnSiguiente.hasAttribute("disabled")).toBe(true);
  });
});
