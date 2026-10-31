/**
 * CustomerDetail.test.tsx — Pruebas de Componente para la Ficha Detallada 360° de Cliente
 *
 * Valida de forma exhaustiva:
 * 1. Estado inicial de carga Skeleton (role="status", aria-busy="true", data-testid="customer-detail-loading").
 * 2. Renderizado de las 6 secciones ejecutivas 360° con enmascaramiento por defecto bajo política E6 (RGPD).
 * 3. Banner de política de privacidad E6 con lista de bloques protegidos y botón "Solicitar Revelación de Datos".
 * 4. Validación de formulario en modal de solicitud de concesión (mínimo 20 caracteres y patrón KC-#### / SUP-####).
 * 5. Envío exitoso de POST /admin/v1/access-grants, invalidación automática de caché y desenmascarado reactivo.
 * 6. Gestión de error 404 (organización no encontrada) con opción de reintento y enlace al listado.
 * 7. Gestión de error 503 (agregados analíticos en refresco) con visualización de X-Trace-Id y botón de reintento.
 * 8. Control de acceso RBAC bloqueando la vista para rol staff_operaciones (403 ROL_STAFF_INSUFICIENTE).
 * 9. Acceso autorizado para personal staff_soporte y staff_admin.
 * 10. Cierre accesible del modal de concesión con botón Cancelar y tecla Escape.
 */

import { describe, it, expect, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { MemoryRouter, Routes, Route } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { http, HttpResponse } from "msw";
import { server } from "../../pruebas/server";
import { resetMockState } from "../../pruebas/msw_handlers";
import { AuthProvider, UsuarioStaff } from "../../estado/auth";
import { CustomerDetail } from "../CustomerDetail";

function renderCustomerDetail(opciones?: {
  usuario?: UsuarioStaff;
  tenantId?: string;
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

  const tenantId = opciones?.tenantId ?? "org_acme";
  const rutaInicial = `/business/customers/${tenantId}`;

  return render(
    <AuthProvider
      sesionInicial={{
        usuario: usuarioStaff,
        token: "jwt_token_valido_test",
      }}
    >
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={[rutaInicial]}>
          <Routes>
            <Route path="/business/customers/:tenant_id" element={<CustomerDetail />} />
            <Route
              path="/business/customers"
              element={<div data-testid="vista-directorio-clientes">Directorio Clientes</div>}
            />
            <Route
              path="/ops/agents"
              element={<div data-testid="vista-ops-agents">Operaciones Agentes</div>}
            />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>
    </AuthProvider>
  );
}

describe("CustomerDetail — Ficha 360° de Cliente y Concesión de Revelación", () => {
  beforeEach(() => {
    resetMockState();
  });

  it("1. renderiza el estado de carga skeleton accesible con role=status y aria-busy=true", () => {
    renderCustomerDetail();

    const loader = screen.getByTestId("customer-detail-loading");
    expect(loader).toBeDefined();
    expect(loader.getAttribute("role")).toBe("status");
    expect(loader.getAttribute("aria-busy")).toBe("true");
  });

  it("2. renderiza las 6 secciones ejecutivas 360° con datos enmascarados por defecto bajo política E6", async () => {
    renderCustomerDetail();

    // Esperar a que se resuelva la consulta
    await waitFor(() => {
      expect(screen.getByTestId("card-identificacion-suscripcion")).toBeDefined();
    });

    // 1. Identificación & Suscripción (Enmascarado por defecto)
    const cardId = screen.getByTestId("card-identificacion-suscripcion");
    expect(cardId.textContent).toContain("org_acme");
    expect(cardId.textContent).toContain("A•••• S.L.");
    expect(cardId.textContent).toContain("a••••.com");
    expect(cardId.textContent).toContain("Growth");
    expect(cardId.textContent).toContain("Activa");

    // 2. Líneas de Producción
    const cardLineas = screen.getByTestId("card-lineas-produccion");
    expect(cardLineas.textContent).toContain("Líneas Contratadas");
    expect(cardLineas.textContent).toContain("Líneas Activas");
    expect(cardLineas.textContent).toContain("Utilización Media del Ciclo");

    // 3. Consumo del Ciclo e Histórico
    const cardConsumo = screen.getByTestId("card-consumo-historico");
    expect(cardConsumo.textContent).toContain("LOC Consumidas");
    expect(cardConsumo.textContent).toContain("Tokens Consumidos");
    expect(cardConsumo.textContent).toContain("Histórico de los Últimos 6 Ciclos Comerciales");
    expect(cardConsumo.textContent).toContain("2026-10");

    // 4. Usuarios de la Organización (Emails Enmascarados)
    const cardUsuarios = screen.getByTestId("card-usuarios-organizacion");
    expect(cardUsuarios.textContent).toContain("[Emails Enmascarados]");
    expect(cardUsuarios.textContent).toContain("u••••@acme.com");

    // 5. Integraciones Conectadas (Rutas Enmascaradas)
    const cardInteg = screen.getByTestId("card-integraciones");
    expect(cardInteg.textContent).toContain("[Rutas Enmascaradas]");
    expect(cardInteg.textContent).toContain("repo-••••");

    // 6. Actividad de Pipeline & Grafo CodeMapping
    const cardGrafo = screen.getByTestId("card-actividad-grafo");
    expect(cardGrafo.textContent).toContain("Cobertura de Grafo");
    expect(cardGrafo.textContent).toContain("Nodos Indexados");
    expect(cardGrafo.textContent).toContain("Aristas de Dependencia");
    expect(cardGrafo.textContent).toContain("Rendimiento End-to-End");
  });

  it("3. muestra el banner de protección de PII E6 y botón de solicitud de revelación cuando hay campos enmascarados", async () => {
    renderCustomerDetail();

    await waitFor(() => {
      expect(screen.getByTestId("banner-enmascaramiento-e6")).toBeDefined();
    });

    const banner = screen.getByTestId("banner-enmascaramiento-e6");
    expect(banner.textContent).toContain("Protección de PII y Política de Enmascaramiento por Defecto (E6)");
    expect(screen.getByTestId("btn-solicitar-revelacion")).toBeDefined();
    expect(screen.getByTestId("btn-revelar-banner")).toBeDefined();
  });

  it("4. abre el modal accesible de concesión y valida que el motivo tenga al menos 20 caracteres y referencia a ticket", async () => {
    renderCustomerDetail();

    await waitFor(() => {
      expect(screen.getByTestId("btn-solicitar-revelacion")).toBeDefined();
    });

    // Abrir modal
    fireEvent.click(screen.getByTestId("btn-solicitar-revelacion"));
    expect(screen.getByText("Solicitud de Concesión de Acceso a Datos de Cliente")).toBeDefined();

    // 1. Intento de envío vacío o con motivo corto (< 20 caracteres)
    const textarea = screen.getByTestId("input-concesion-motivo");
    const submitBtn = screen.getByTestId("btn-confirmar-concesion");

    fireEvent.change(textarea, { target: { value: "Motivo corto" } });
    fireEvent.click(submitBtn);

    const errorMsg1 = await screen.findByTestId("error-validacion-modal");
    expect(errorMsg1.textContent).toContain("al menos 20 caracteres");

    // 2. Motivo >= 20 caracteres pero sin referencia KC-#### ni SUP-####
    fireEvent.change(textarea, {
      target: { value: "Este es un motivo suficientemente largo pero sin ninguna referencia" },
    });
    fireEvent.click(submitBtn);

    const errorMsg2 = await screen.findByTestId("error-validacion-modal");
    expect(errorMsg2.textContent).toContain("referencia obligatoria a un ticket válido");
  });

  it("5. envía correctamente POST /admin/v1/access-grants, invalida la caché y desenmascara los datos automáticamente", async () => {
    renderCustomerDetail();

    await waitFor(() => {
      expect(screen.getByTestId("btn-solicitar-revelacion")).toBeDefined();
    });

    // Abrir modal
    fireEvent.click(screen.getByTestId("btn-solicitar-revelacion"));

    // Rellenar formulario válido con motivo y referencia a ticket KC-1049
    const textarea = screen.getByTestId("input-concesion-motivo");
    fireEvent.change(textarea, {
      target: { value: "Investigación técnica para ticket KC-1049 sobre sincronización de repositorios" },
    });

    const submitBtn = screen.getByTestId("btn-confirmar-concesion");
    fireEvent.click(submitBtn);

    // Esperar a que el modal se cierre y aparezca la notificación viva
    await waitFor(() => {
      expect(screen.getByTestId("banner-feedback-concesion")).toBeDefined();
    });

    expect(screen.getByTestId("banner-feedback-concesion").textContent).toContain(
      "Concesión de acceso autorizada. Los datos sensibles han sido revelados en claro."
    );

    // Los datos deben reflejar la concesión activa y datos desenmascarados
    await waitFor(() => {
      expect(screen.getByTestId("badge-concesion-activa")).toBeDefined();
    });

    // Comprobar que la razón social y el dominio ahora se muestran en claro
    expect(screen.getByRole("heading", { name: "Acme Logística S.L." })).toBeDefined();
    expect(screen.getAllByText("acme.com").length).toBeGreaterThanOrEqual(1);

    // Comprobar que los usuarios y las integraciones ya no muestran datos ofuscados
    const cardUsuarios = screen.getByTestId("card-usuarios-organizacion");
    expect(cardUsuarios.textContent).toContain("admin@acme.com");
    expect(cardUsuarios.textContent).toContain("Juan Pérez");

    const cardInteg = screen.getByTestId("card-integraciones");
    expect(cardInteg.textContent).toContain("acme-corp/core-api");

    // El banner de enmascaramiento ya no debe estar presente
    expect(screen.queryByTestId("banner-enmascaramiento-e6")).toBeNull();
  });

  it("6. maneja el error 404 NO_ENCONTRADO con tarjeta de error, reintento y enlace al listado", async () => {
    renderCustomerDetail({ tenantId: "org_inexistente" });

    await waitFor(() => {
      expect(screen.getByTestId("customer-detail-error")).toBeDefined();
    });

    const errorCard = screen.getByTestId("customer-detail-error");
    expect(errorCard.textContent).toContain("Organización Cliente No Encontrada (404)");
    expect(screen.getByRole("button", { name: /Reintentar/ })).toBeDefined();
    expect(screen.getByRole("link", { name: /Volver al Listado/ })).toBeDefined();
  });

  it("7. maneja el error 503 AGREGADO_NO_DISPONIBLE mostrando el código, mensaje y X-Trace-Id", async () => {
    server.use(
      http.get("*/admin/v1/business/customers/:tenant_id", () => {
        return HttpResponse.json(
          {
            error: {
              codigo: "AGREGADO_NO_DISPONIBLE",
              code: "agregado_no_disponible",
              mensaje: "La capa de agregados analíticos está en refresco temporal.",
              trace_id: "trc_503_test_detail",
            },
          },
          {
            status: 503,
            headers: {
              "x-trace-id": "trc_503_test_detail",
            },
          }
        );
      })
    );

    renderCustomerDetail();

    await waitFor(() => {
      expect(screen.getByTestId("customer-detail-error")).toBeDefined();
    });

    const errorCard = screen.getByTestId("customer-detail-error");
    expect(errorCard.textContent).toContain("Agregados Analíticos No Disponibles (503)");
    expect(screen.getByTestId("error-trace-id").textContent).toBe("trc_503_test_detail");
  });

  it("8. bloquea el acceso con tarjeta de advertencia 403 ROL_STAFF_INSUFICIENTE si el usuario es staff_operaciones", async () => {
    renderCustomerDetail({
      usuario: {
        staff_id: "st_ops_001",
        email: "ops@kallicode.com",
        nombre: "Staff Operaciones",
        role: "staff_operaciones",
        mfa_validado: true,
      },
    });

    const rbacError = await screen.findByTestId("error-403-rol");
    expect(rbacError).toBeDefined();
    expect(rbacError.textContent).toContain("Acceso Restringido (403 ROL_STAFF_INSUFICIENTE)");
    expect(rbacError.textContent).toContain("staff_operaciones");
    expect(screen.getByRole("link", { name: /Ir a Operaciones de Agentes/ })).toBeDefined();
  });

  it("9. permite el acceso regular para roles autorizados staff_soporte y staff_admin", async () => {
    // Probar staff_soporte
    const { unmount } = renderCustomerDetail({
      usuario: {
        staff_id: "st_soporte_001",
        email: "soporte@kallicode.com",
        nombre: "Staff Soporte",
        role: "staff_soporte",
        mfa_validado: true,
      },
    });

    await waitFor(() => {
      expect(screen.getByTestId("card-identificacion-suscripcion")).toBeDefined();
    });
    unmount();

    // Probar staff_admin
    renderCustomerDetail({
      usuario: {
        staff_id: "st_admin_001",
        email: "admin@kallicode.com",
        nombre: "Staff Admin",
        role: "staff_admin",
        mfa_validado: true,
      },
    });

    await waitFor(() => {
      expect(screen.getByTestId("card-identificacion-suscripcion")).toBeDefined();
    });
  });

  it("10. permite cerrar el modal de concesión mediante el botón Cancelar o la tecla Escape", async () => {
    renderCustomerDetail();

    await waitFor(() => {
      expect(screen.getByTestId("btn-solicitar-revelacion")).toBeDefined();
    });

    // Abrir modal
    fireEvent.click(screen.getByTestId("btn-solicitar-revelacion"));
    expect(screen.getByText("Solicitud de Concesión de Acceso a Datos de Cliente")).toBeDefined();

    // Cerrar con botón Cancelar
    const cancelBtn = screen.getByRole("button", { name: "Cancelar" });
    fireEvent.click(cancelBtn);

    await waitFor(() => {
      expect(screen.queryByText("Solicitud de Concesión de Acceso a Datos de Cliente")).toBeNull();
    });

    // Abrir de nuevo y cerrar con Escape
    fireEvent.click(screen.getByTestId("btn-solicitar-revelacion"));
    expect(screen.getByText("Solicitud de Concesión de Acceso a Datos de Cliente")).toBeDefined();

    fireEvent.keyDown(window, { key: "Escape", code: "Escape" });

    await waitFor(() => {
      expect(screen.queryByText("Solicitud de Concesión de Acceso a Datos de Cliente")).toBeNull();
    });
  });
});
