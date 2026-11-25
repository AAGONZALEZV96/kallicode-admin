import { describe, it, expect, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor, act } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useNavigate } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { AuthProvider, UsuarioStaff } from "../estado/auth";
import { AdminLayout } from "../componentes/AdminLayout";
import {
  Tabla,
  TablaEncabezado,
  TablaCuerpo,
  TablaFila,
  TablaCeldaEncabezado,
  TablaCelda,
} from "../componentes/Tabla";
import { SolicitudConcesionModal } from "../componentes/SolicitudConcesionModal";
import { ControlExportarReporte } from "../componentes/ControlExportarReporte";
import { DetalleRelojSLA } from "../componentes/DetalleRelojSLA";
import { BizCustomers } from "../vistas/BizCustomers";
import { BizSubscriptions } from "../vistas/BizSubscriptions";
import { BizTokens } from "../vistas/BizTokens";
import { OpsAgents } from "../vistas/OpsAgents";
import { OpsModels } from "../vistas/OpsModels";
import { OpsSLA } from "../vistas/OpsSLA";
import { CustomerDetail } from "../vistas/CustomerDetail";

const ORIGINAL_INNER_WIDTH = window.innerWidth;
const ORIGINAL_MATCH_MEDIA = window.matchMedia;

type MediaChangeListener = (event: MediaQueryListEvent) => void;
const activeMediaListeners = new Set<{ query: string; listener: MediaChangeListener }>();

function evaluateMediaQuery(query: string, width: number): boolean {
  const minMatch = /\(min-width:\s*(\d+)px\)/.exec(query);
  const maxMatch = /\(max-width:\s*(\d+)px\)/.exec(query);

  let ok = true;
  if (minMatch) {
    ok = ok && width >= Number(minMatch[1]);
  }
  if (maxMatch) {
    ok = ok && width <= Number(maxMatch[1]);
  }
  return ok;
}

function mockViewport(width: number): void {
  Object.defineProperty(window, "innerWidth", {
    writable: true,
    configurable: true,
    value: width,
  });

  window.matchMedia = ((query: string): MediaQueryList => {
    const matches = evaluateMediaQuery(query, window.innerWidth);
    const listeners = new Set<MediaChangeListener>();

    return {
      matches,
      media: query,
      onchange: null,
      addListener: (cb: (e: MediaQueryListEvent) => void) => {
        listeners.add(cb);
        activeMediaListeners.add({ query, listener: cb });
      },
      removeListener: (cb: (e: MediaQueryListEvent) => void) => {
        listeners.delete(cb);
        for (const item of activeMediaListeners) {
          if (item.listener === cb) activeMediaListeners.delete(item);
        }
      },
      addEventListener: (type: string, cb: EventListenerOrEventListenerObject) => {
        if (type === "change" && typeof cb === "function") {
          const fn = cb as MediaChangeListener;
          listeners.add(fn);
          activeMediaListeners.add({ query, listener: fn });
        }
      },
      removeEventListener: (type: string, cb: EventListenerOrEventListenerObject) => {
        if (type === "change" && typeof cb === "function") {
          const fn = cb as MediaChangeListener;
          listeners.delete(fn);
          for (const item of activeMediaListeners) {
            if (item.listener === fn) activeMediaListeners.delete(item);
          }
        }
      },
      dispatchEvent: () => true,
    } as unknown as MediaQueryList;
  }) as typeof window.matchMedia;

  act(() => {
    for (const item of activeMediaListeners) {
      item.listener({
        matches: evaluateMediaQuery(item.query, width),
        media: item.query,
      } as MediaQueryListEvent);
    }
    window.dispatchEvent(new Event("resize"));
  });
}

afterEach(() => {
  activeMediaListeners.clear();
  Object.defineProperty(window, "innerWidth", {
    writable: true,
    configurable: true,
    value: ORIGINAL_INNER_WIDTH,
  });
  window.matchMedia = ORIGINAL_MATCH_MEDIA;
  document.body.style.overflow = "";
});

const ADMIN_STAFF: UsuarioStaff = {
  staff_id: "st_admin_resp",
  email: "admin@kallicode.com",
  nombre: "Admin Responsive",
  role: "staff_admin",
  mfa_validado: true,
};

function crearQueryClient() {
  return new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
}

function renderWithProviders(ui: React.ReactElement, initialRoute = "/") {
  const qc = crearQueryClient();
  return render(
    <MemoryRouter initialEntries={[initialRoute]}>
      <AuthProvider sesionInicial={{ usuario: ADMIN_STAFF, token: "jwt_admin_resp" }}>
        <QueryClientProvider client={qc}>{ui}</QueryClientProvider>
      </AuthProvider>
    </MemoryRouter>
  );
}

const BotonNavegacionAux: React.FC = () => {
  const navigate = useNavigate();
  return (
    <button type="button" data-testid="btn-nav-programatico" onClick={() => navigate("/ops/sla")}>
      Ir a SLA
    </button>
  );
};

describe("KC-ADM-B6-09 — Diseño Adaptable (Responsive) de Tablas Densas e Interfaz", () => {
  it("1. AdminLayout abre el drawer en 1024px, 768px y 375px y cierra al cambiar ruta, pulsar Escape o crecer a escritorio", async () => {
    for (const ancho of [1024, 768, 375]) {
      mockViewport(ancho);
      const { unmount } = render(
        <MemoryRouter initialEntries={["/overview"]}>
          <AuthProvider sesionInicial={{ usuario: ADMIN_STAFF, token: "jwt_admin_resp" }}>
            <Routes>
              <Route element={<AdminLayout />}>
                <Route path="/overview" element={<BotonNavegacionAux />} />
                <Route path="/ops/sla" element={<div>Vista SLA</div>} />
              </Route>
            </Routes>
          </AuthProvider>
        </MemoryRouter>
      );

      // Abrir drawer con el toggle móvil
      const toggleBtn = screen.getByLabelText("Abrir menú de navegación");
      expect(toggleBtn.getAttribute("aria-expanded")).toBe("false");
      fireEvent.click(toggleBtn);

      expect(screen.getByRole("dialog", { name: "Navegación móvil" })).toBeDefined();
      expect(toggleBtn.getAttribute("aria-expanded")).toBe("true");
      expect(document.body.style.overflow).toBe("hidden");

      // Cierre con Escape
      fireEvent.keyDown(window, { key: "Escape" });
      await waitFor(() => {
        expect(screen.queryByRole("dialog", { name: "Navegación móvil" })).toBeNull();
      });
      expect(document.body.style.overflow).toBe("");

      // Reabrir y verificar cierre automático al cambiar ruta
      fireEvent.click(screen.getByLabelText("Abrir menú de navegación"));
      expect(screen.getByRole("dialog", { name: "Navegación móvil" })).toBeDefined();
      fireEvent.click(screen.getByTestId("btn-nav-programatico"));
      await waitFor(() => {
        expect(screen.queryByRole("dialog", { name: "Navegación móvil" })).toBeNull();
      });

      // Reabrir y verificar cierre automático al redimensionar a escritorio (>= 1025px)
      fireEvent.click(screen.getByLabelText("Abrir menú de navegación"));
      expect(screen.getByRole("dialog", { name: "Navegación móvil" })).toBeDefined();
      mockViewport(1280);
      await waitFor(() => {
        expect(screen.queryByRole("dialog", { name: "Navegación móvil" })).toBeNull();
      });

      unmount();
    }
  });

  it("2. Tabla expone scroll autónomo, región accesible, sticky column, prioridades y sombras laterales", () => {
    const { container, rerender } = render(
      <Tabla densidad="alta" aria-label="Tabla de prueba responsiva">
        <TablaEncabezado>
          <TablaFila>
            <TablaCeldaEncabezado fija>Tenant ID</TablaCeldaEncabezado>
            <TablaCeldaEncabezado prioridad="media">Métrica Media</TablaCeldaEncabezado>
            <TablaCeldaEncabezado prioridad="baja">Métrica Secundaria</TablaCeldaEncabezado>
          </TablaFila>
        </TablaEncabezado>
        <TablaCuerpo>
          <TablaFila>
            <TablaCelda fija>org_acme</TablaCelda>
            <TablaCelda prioridad="media">120</TablaCelda>
            <TablaCelda prioridad="baja">Extra</TablaCelda>
          </TablaFila>
        </TablaCuerpo>
      </Tabla>
    );

    const region = container.querySelector(".table-container") as HTMLElement;
    expect(region).not.toBeNull();
    expect(region.getAttribute("role")).toBe("region");
    expect(region.getAttribute("tabindex")).toBe("0");
    expect(region.getAttribute("aria-label")).toBe("Tabla de prueba responsiva");
    expect(region.classList.contains("tabla-mostrar-todas")).toBe(false);

    // Clases sticky y prioridad
    expect(container.querySelectorAll(".kc-col-sticky").length).toBe(2);
    expect(container.querySelectorAll(".kc-col-priority-media").length).toBe(2);
    expect(container.querySelectorAll(".kc-col-priority-baja").length).toBe(2);

    // Simular overflow horizontal y scroll
    Object.defineProperty(region, "scrollWidth", { configurable: true, value: 900 });
    Object.defineProperty(region, "clientWidth", { configurable: true, value: 360 });
    Object.defineProperty(region, "scrollLeft", { writable: true, configurable: true, value: 0 });
    fireEvent.scroll(region);
    expect(region.getAttribute("data-scroll-left")).toBe("false");
    expect(region.getAttribute("data-scroll-right")).toBe("true");

    region.scrollLeft = 80;
    fireEvent.scroll(region);
    expect(region.getAttribute("data-scroll-left")).toBe("true");
    expect(region.getAttribute("data-scroll-right")).toBe("true");

    // Alternar mostrarTodasColumnas
    rerender(
      <Tabla densidad="alta" mostrarTodasColumnas aria-label="Tabla de prueba responsiva">
        <TablaEncabezado>
          <TablaFila>
            <TablaCeldaEncabezado fija>Tenant ID</TablaCeldaEncabezado>
          </TablaFila>
        </TablaEncabezado>
        <TablaCuerpo>
          <TablaFila>
            <TablaCelda fija>org_acme</TablaCelda>
          </TablaFila>
        </TablaCuerpo>
      </Tabla>
    );
    expect(region.classList.contains("tabla-mostrar-todas")).toBe(true);
  });

  it("3. BizCustomers, BizSubscriptions, BizTokens, OpsAgents, OpsModels, OpsSLA y CustomerDetail adaptan sus tablas, filtros y toggles en 1024px, 768px y 375px", async () => {
    for (const width of [1024, 768, 375]) {
      mockViewport(width);

      // BizCustomers
      const vCust = renderWithProviders(<BizCustomers />);
      await waitFor(() => expect(vCust.container.querySelector(".table-container")).not.toBeNull());
      expect(vCust.container.querySelector(".kc-filter-bar")).not.toBeNull();
      expect(vCust.container.querySelector(".kc-pagination")).not.toBeNull();
      expect(vCust.container.querySelectorAll(".kc-col-sticky").length).toBeGreaterThan(0);
      const toggleCust = vCust.getByTestId("toggle-columnas-completas");
      fireEvent.click(toggleCust);
      expect(toggleCust.getAttribute("aria-pressed")).toBe("true");
      expect(vCust.container.querySelector(".table-container")?.classList.contains("tabla-mostrar-todas")).toBe(true);
      vCust.unmount();

      // BizSubscriptions
      const vSubs = renderWithProviders(<BizSubscriptions />);
      await waitFor(() => expect(vSubs.container.querySelector(".table-container")).not.toBeNull());
      expect(vSubs.container.querySelector(".kc-tabs-scroll")).not.toBeNull();
      expect(vSubs.container.querySelector(".kc-filter-bar")).not.toBeNull();
      expect(vSubs.container.querySelectorAll(".kc-col-sticky").length).toBeGreaterThan(0);
      vSubs.unmount();

      // BizTokens
      const vTok = renderWithProviders(<BizTokens />);
      await waitFor(() => expect(vTok.container.querySelector(".table-container")).not.toBeNull());
      expect(vTok.container.querySelector(".kc-filter-bar")).not.toBeNull();
      expect(vTok.container.querySelector(".kc-grid-cards")).not.toBeNull();
      expect(vTok.container.querySelectorAll(".kc-col-sticky").length).toBeGreaterThan(0);
      vTok.unmount();

      // OpsAgents
      const vAgents = renderWithProviders(<OpsAgents />);
      await waitFor(() => expect(vAgents.container.querySelector(".table-container")).not.toBeNull());
      expect(vAgents.container.querySelector(".kc-view-container")).not.toBeNull();
      expect(vAgents.container.querySelectorAll(".kc-col-sticky").length).toBeGreaterThan(0);
      vAgents.unmount();

      // OpsModels
      const vModels = renderWithProviders(<OpsModels />);
      await waitFor(() => expect(vModels.container.querySelector(".table-container")).not.toBeNull());
      expect(vModels.container.querySelector(".kc-view-container")).not.toBeNull();
      expect(vModels.container.querySelector(".kc-filter-bar")).not.toBeNull();
      expect(vModels.container.querySelectorAll(".kc-col-sticky").length).toBeGreaterThan(0);
      vModels.unmount();

      // OpsSLA
      const vSla = renderWithProviders(<OpsSLA />);
      await waitFor(() => expect(vSla.container.querySelector(".table-container")).not.toBeNull());
      expect(vSla.container.querySelector(".kc-filter-bar")).not.toBeNull();
      expect(vSla.container.querySelector(".kc-pagination")).not.toBeNull();
      expect(vSla.container.querySelectorAll(".kc-col-sticky").length).toBeGreaterThan(0);
      vSla.unmount();

      // CustomerDetail
      const qcDetail = crearQueryClient();
      const vDetail = render(
        <MemoryRouter initialEntries={["/business/customers/org_acme"]}>
          <AuthProvider sesionInicial={{ usuario: ADMIN_STAFF, token: "jwt_admin_resp" }}>
            <QueryClientProvider client={qcDetail}>
              <Routes>
                <Route path="/business/customers/:tenant_id" element={<CustomerDetail />} />
              </Routes>
            </QueryClientProvider>
          </AuthProvider>
        </MemoryRouter>
      );
      await waitFor(() => expect(vDetail.container.querySelectorAll(".table-container").length).toBeGreaterThanOrEqual(3));
      expect(vDetail.container.querySelector(".kc-grid-detail")).not.toBeNull();
      expect(vDetail.container.querySelectorAll(".kc-col-sticky").length).toBeGreaterThanOrEqual(3);
      vDetail.unmount();
    }
  }, 20000);

  it("4. Modales (SolicitudConcesionModal, ControlExportarReporte, DetalleRelojSLA) mantienen estructura adaptable en 375px", async () => {
    mockViewport(375);

    // 4.1 SolicitudConcesionModal
    const m1 = renderWithProviders(
      <SolicitudConcesionModal abierto alCerrar={() => {}} tenantId="org_acme" razonSocial="A•••• S.L." />
    );
    expect(screen.getByRole("dialog")).toBeDefined();
    expect(m1.container.querySelector(".modal-body")).not.toBeNull();
    expect(m1.container.querySelector(".kc-modal-grid-2")).not.toBeNull();
    m1.unmount();

    // 4.2 ControlExportarReporte
    const m2 = renderWithProviders(<ControlExportarReporte tipo="clientes" />);
    fireEvent.click(screen.getByTestId("btn-exportar-clientes"));
    expect(screen.getByRole("dialog")).toBeDefined();
    expect(m2.container.querySelector(".modal-body")).not.toBeNull();
    expect(m2.container.querySelector(".kc-modal-grid-2")).not.toBeNull();
    m2.unmount();

    // 4.3 DetalleRelojSLA
    const m3 = renderWithProviders(
      <DetalleRelojSLA jobId="job_sla_ent_01" abierto alCerrar={() => {}} />
    );
    await waitFor(() => {
      expect(m3.container.querySelector(".kc-sla-equation-grid")).not.toBeNull();
    });
    expect(screen.getByRole("dialog")).toBeDefined();
    expect(m3.container.querySelector(".modal-body")).not.toBeNull();
    m3.unmount();
  });
});
