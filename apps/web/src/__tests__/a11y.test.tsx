import fs from "node:fs";
import path from "node:path";
import React, { useState } from "react";
import { describe, it, expect, beforeAll } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import axeCore, { Result } from "axe-core";
import * as axeMatchers from "vitest-axe/matchers";
import { AuthProvider, UsuarioStaff } from "../estado/auth";

declare module "vitest" {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  interface Assertion<T = any> {
    toHaveNoViolations(): T;
  }
}
import { AdminLayout } from "../componentes/AdminLayout";
import { Modal } from "../componentes/Modal";
import { EstadoCarga } from "../componentes/EstadoCarga";
import { EstadoError } from "../componentes/EstadoError";
import { EstadoVacio } from "../componentes/EstadoVacio";
import { ControlesLiveRefresh } from "../componentes/ControlesLiveRefresh";
import { SolicitudConcesionModal } from "../componentes/SolicitudConcesionModal";
import { ControlExportarReporte } from "../componentes/ControlExportarReporte";
import { DetalleRelojSLA } from "../componentes/DetalleRelojSLA";
import { useLiveRefresh } from "../hooks/useLiveRefresh";
import { BizOverview } from "../vistas/BizOverview";
import { BizCustomers } from "../vistas/BizCustomers";
import { CustomerDetail } from "../vistas/CustomerDetail";
import { BizSubscriptions } from "../vistas/BizSubscriptions";
import { BizTokens } from "../vistas/BizTokens";
import { OpsAgents } from "../vistas/OpsAgents";
import { OpsModels } from "../vistas/OpsModels";
import { OpsSLA } from "../vistas/OpsSLA";

expect.extend(axeMatchers);

const ADMIN_STAFF: UsuarioStaff = {
  staff_id: "st_admin_a11y",
  email: "admin@kallicode.com",
  nombre: "Admin A11y",
  role: "staff_admin",
  mfa_validado: true,
};

function crearQueryClient() {
  return new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
}

function renderEnAdminLayout(initialRoute: string, element: React.ReactElement, routePath = initialRoute) {
  const qc = crearQueryClient();
  return render(
    <MemoryRouter initialEntries={[initialRoute]}>
      <AuthProvider sesionInicial={{ usuario: ADMIN_STAFF, token: "jwt_admin_a11y" }}>
        <QueryClientProvider client={qc}>
          <Routes>
            <Route element={<AdminLayout />}>
              <Route path={routePath} element={element} />
            </Route>
          </Routes>
        </QueryClientProvider>
      </AuthProvider>
    </MemoryRouter>
  );
}

async function auditarConAxe(container: HTMLElement): Promise<void> {
  const results = await axeCore.run(container, {
    runOnly: {
      type: "tag",
      values: ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "best-practice"],
    },
    rules: {
      // JSDOM no computa estilos CSS externos para cálculo de color; el contraste se verifica en el test #4
      "color-contrast": { enabled: false },
    },
  });

  const gravesOCriticas = results.violations.filter(
    (v: Result) => v.impact === "critical" || v.impact === "serious"
  );

  expect(
    gravesOCriticas,
    `Violaciones critical/serious detectadas:\n${gravesOCriticas
      .map((v) => `- [${v.impact}] ${v.id}: ${v.help} (${v.nodes.length} nodos)`)
      .join("\n")}`
  ).toEqual([]);

  expect(results).toHaveNoViolations();
}

// ------------------------------------------------------------------ Helpers WCAG 2.1 Contraste
function hexToRgb(hex: string): [number, number, number] {
  const limpio = hex.replace("#", "").trim();
  const num = parseInt(limpio, 16);
  return [(num >> 16) & 255, (num >> 8) & 255, num & 255];
}

function relativeLuminance(rgb: [number, number, number]): number {
  const canales = rgb.map((c) => {
    const s = c / 255;
    return s <= 0.03928 ? s / 12.92 : Math.pow((s + 0.055) / 1.055, 2.4);
  });
  return 0.2126 * canales[0] + 0.7152 * canales[1] + 0.0722 * canales[2];
}

function contrastRatio(fgHex: string, bgHex: string): number {
  const l1 = relativeLuminance(hexToRgb(fgHex));
  const l2 = relativeLuminance(hexToRgb(bgHex));
  const lighter = Math.max(l1, l2);
  const darker = Math.min(l1, l2);
  return (lighter + 0.05) / (darker + 0.05);
}

function extraerTokensBloque(css: string, selectorRegex: RegExp): Record<string, string> {
  const match = selectorRegex.exec(css);
  if (!match) return {};
  const cuerpo = match[1];
  const mapa: Record<string, string> = {};
  const re = /(--[a-z0-9-]+)\s*:\s*([^;]+);/gi;
  let m: RegExpExecArray | null;
  while ((m = re.exec(cuerpo)) !== null) {
    mapa[m[1]] = m[2].trim();
  }
  return mapa;
}

const ControlesLiveRefreshHarness: React.FC = () => {
  const hook = useLiveRefresh({
    intervaloMs: 15_000,
    ejecutarAlInicio: false,
    alRefrescar: async () => {},
  });
  return <ControlesLiveRefresh hook={hook} />;
};

const ModalFocusHarness: React.FC = () => {
  const [abierto, setAbierto] = useState(false);
  return (
    <main>
      <button type="button" data-testid="btn-abrir-modal" onClick={() => setAbierto(true)}>
        Abrir diálogo
      </button>
      <Modal
        abierto={abierto}
        alCerrar={() => setAbierto(false)}
        titulo="Diálogo de prueba de foco"
        pie={
          <button type="button" data-testid="btn-footer-modal" onClick={() => setAbierto(false)}>
            Confirmar
          </button>
        }
      >
        <input data-testid="input-en-modal" aria-label="Campo dentro del modal" />
      </Modal>
    </main>
  );
};

describe("KC-ADM-B6-04 — Auditoría de Accesibilidad WCAG 2.1 AA con axe-core", () => {
  beforeAll(() => {
    // Asegurar entorno limpio
  });

  it("1. las 7 pantallas operativas y CustomerDetail cumplen WCAG 2.1 AA con 0 violaciones critical/serious", async () => {
    // 1. BizOverview
    const vOverview = renderEnAdminLayout("/overview", <BizOverview />);
    await waitFor(() => expect(vOverview.getByTestId("kpi-mrr")).toBeDefined());
    await auditarConAxe(vOverview.container);
    vOverview.unmount();

    // 2. BizCustomers
    const vCustomers = renderEnAdminLayout("/business/customers", <BizCustomers />);
    await waitFor(() => expect(vCustomers.container.querySelector(".kc-table")).not.toBeNull());
    await auditarConAxe(vCustomers.container);
    vCustomers.unmount();

    // 3. CustomerDetail
    const vDetail = renderEnAdminLayout(
      "/business/customers/org_acme",
      <CustomerDetail />,
      "/business/customers/:tenant_id"
    );
    await waitFor(() => expect(vDetail.getByTestId("card-identificacion-suscripcion")).toBeDefined());
    await auditarConAxe(vDetail.container);
    vDetail.unmount();

    // 4a. BizSubscriptions (Renovaciones)
    const vSubs = renderEnAdminLayout("/business/subscriptions", <BizSubscriptions />);
    await waitFor(() => expect(vSubs.container.querySelector(".kc-table")).not.toBeNull());
    await auditarConAxe(vSubs.container);
    // 4b. BizSubscriptions (Cola de Upgrades)
    fireEvent.click(vSubs.getByTestId("tab-solicitudes"));
    await waitFor(() => expect(vSubs.getByRole("table")).toBeDefined());
    await auditarConAxe(vSubs.container);
    vSubs.unmount();

    // 5. BizTokens
    const vTokens = renderEnAdminLayout("/business/tokens", <BizTokens />);
    await waitFor(() => expect(vTokens.getByTestId("card-total-tokens")).toBeDefined());
    await auditarConAxe(vTokens.container);
    vTokens.unmount();

    // 6. OpsAgents
    const vAgents = renderEnAdminLayout("/ops/agents", <OpsAgents />);
    await waitFor(() => expect(vAgents.getByTestId("tabla-colas-ops")).toBeDefined());
    await auditarConAxe(vAgents.container);
    vAgents.unmount();

    // 7. OpsModels
    const vModels = renderEnAdminLayout("/ops/models", <OpsModels />);
    await waitFor(() => expect(vModels.getByTestId("tabla-modelos-estandar")).toBeDefined());
    await auditarConAxe(vModels.container);
    vModels.unmount();

    // 8. OpsSLA
    const vSla = renderEnAdminLayout("/ops/sla", <OpsSLA />);
    await waitFor(() => expect(vSla.getByTestId("kpi-cumplimiento-global")).toBeDefined());
    await auditarConAxe(vSla.container);
    vSla.unmount();
  }, 30000);

  it("2. modales y componentes transversales (EstadoCarga, EstadoError, EstadoVacio, ControlesLiveRefresh) pasan axe-core sin violaciones", async () => {
    const qc = crearQueryClient();

    // SolicitudConcesionModal
    const mGrant = render(
      <MemoryRouter>
        <AuthProvider sesionInicial={{ usuario: ADMIN_STAFF, token: "jwt_admin_a11y" }}>
          <QueryClientProvider client={qc}>
            <main>
              <SolicitudConcesionModal abierto alCerrar={() => {}} tenantId="org_acme" razonSocial="A•••• S.L." />
            </main>
          </QueryClientProvider>
        </AuthProvider>
      </MemoryRouter>
    );
    await auditarConAxe(mGrant.container);
    mGrant.unmount();

    // ControlExportarReporte
    const mExport = render(
      <MemoryRouter>
        <AuthProvider sesionInicial={{ usuario: ADMIN_STAFF, token: "jwt_admin_a11y" }}>
          <main>
            <ControlExportarReporte tipo="clientes" />
          </main>
        </AuthProvider>
      </MemoryRouter>
    );
    fireEvent.click(screen.getByTestId("btn-exportar-clientes"));
    await auditarConAxe(mExport.container);
    mExport.unmount();

    // DetalleRelojSLA
    const mSla = render(
      <MemoryRouter>
        <QueryClientProvider client={qc}>
          <main>
            <DetalleRelojSLA jobId="job_sla_ent_01" abierto alCerrar={() => {}} />
          </main>
        </QueryClientProvider>
      </MemoryRouter>
    );
    await waitFor(() => expect(mSla.getByTestId("ecuacion-reloj-sla")).toBeDefined());
    await auditarConAxe(mSla.container);
    mSla.unmount();

    // Estados transversales + ControlesLiveRefresh
    const estados = render(
      <main>
        <h1>Estados transversales</h1>
        <EstadoCarga tipo="kpis" />
        <EstadoError error={{ status: 503, message: "Refrescando agregados" }} alReintentar={() => {}} />
        <EstadoVacio alAccionar={() => {}} />
        <ControlesLiveRefreshHarness />
      </main>
    );
    await auditarConAxe(estados.container);
    estados.unmount();
  });

  it("3. navegación por teclado: focus trap y restauración de foco en Modal, skip-link y botones ordenables en tablas", async () => {
    // 3.1 Focus trap y retorno de foco en Modal
    const { unmount } = render(<ModalFocusHarness />);
    const trigger = screen.getByTestId("btn-abrir-modal");
    trigger.focus();
    expect(document.activeElement).toBe(trigger);

    fireEvent.click(trigger);
    const closeBtn = screen.getByLabelText("Cerrar modal");
    const footerBtn = screen.getByTestId("btn-footer-modal");
    expect(document.activeElement).toBe(closeBtn);

    // Shift+Tab desde primer elemento cicla al último del modal
    fireEvent.keyDown(window, { key: "Tab", shiftKey: true });
    expect(document.activeElement).toBe(footerBtn);

    // Tab desde último elemento cicla al primero del modal
    fireEvent.keyDown(window, { key: "Tab" });
    expect(document.activeElement).toBe(closeBtn);

    // Escape cierra y restaura foco al botón disparador
    fireEvent.keyDown(window, { key: "Escape" });
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(document.activeElement).toBe(trigger);
    unmount();

    // 3.2 Skip-link y cabeceras ordenables enfocables en BizCustomers dentro de AdminLayout
    const vCust = renderEnAdminLayout("/business/customers", <BizCustomers />);
    await waitFor(() => expect(vCust.container.querySelector(".kc-table")).not.toBeNull());

    const skipLink = vCust.getByText("Saltar al contenido principal");
    expect(skipLink.getAttribute("href")).toBe("#main-content");
    expect(vCust.container.querySelectorAll("main").length).toBe(1);

    const sortButtons = vCust.container.querySelectorAll("th button.kc-sort-btn");
    expect(sortButtons.length).toBeGreaterThanOrEqual(5);
    vCust.unmount();
  });

  it("4. valida matemáticamente los ratios de contraste WCAG 2.1 AA (>= 4.5:1) en tokens.css (modos oscuro y claro)", () => {
    const tokensPath = path.resolve(__dirname, "../estilos/tokens.css");
    const css = fs.readFileSync(tokensPath, "utf8");

    const darkTokens = extraerTokensBloque(css, /:root,\s*\[data-theme="dark"\]\s*\{([\s\S]*?)\}/);
    const lightTokens = extraerTokensBloque(css, /\[data-theme="light"\]\s*\{([\s\S]*?)\}/);

    // Tema oscuro: texto normal >= 4.5:1 sobre --bg, --surface y --surface2
    expect(contrastRatio(darkTokens["--text"], darkTokens["--bg"])).toBeGreaterThanOrEqual(4.5);
    expect(contrastRatio(darkTokens["--text"], darkTokens["--surface"])).toBeGreaterThanOrEqual(4.5);
    expect(contrastRatio(darkTokens["--text"], darkTokens["--surface2"])).toBeGreaterThanOrEqual(4.5);
    expect(contrastRatio(darkTokens["--muted"], darkTokens["--surface"])).toBeGreaterThanOrEqual(4.5);
    expect(contrastRatio(darkTokens["--muted"], darkTokens["--surface2"])).toBeGreaterThanOrEqual(4.5);
    expect(contrastRatio(darkTokens["--accent"], darkTokens["--surface"])).toBeGreaterThanOrEqual(4.5);
    expect(contrastRatio(darkTokens["--accent"], darkTokens["--surface2"])).toBeGreaterThanOrEqual(4.5);
    expect(contrastRatio(darkTokens["--text-inverse"], darkTokens["--accent"])).toBeGreaterThanOrEqual(4.5);
    expect(contrastRatio(darkTokens["--good"], darkTokens["--surface"])).toBeGreaterThanOrEqual(4.5);
    expect(contrastRatio(darkTokens["--warn"], darkTokens["--surface"])).toBeGreaterThanOrEqual(4.5);
    expect(contrastRatio(darkTokens["--bad"], darkTokens["--surface"])).toBeGreaterThanOrEqual(4.5);
    expect(contrastRatio(darkTokens["--purple"], darkTokens["--surface"])).toBeGreaterThanOrEqual(4.5);

    // Tema claro: texto normal >= 4.5:1 sobre --bg, --surface y --surface2
    expect(contrastRatio(lightTokens["--text"], lightTokens["--bg"])).toBeGreaterThanOrEqual(4.5);
    expect(contrastRatio(lightTokens["--text"], lightTokens["--surface"])).toBeGreaterThanOrEqual(4.5);
    expect(contrastRatio(lightTokens["--text"], lightTokens["--surface2"])).toBeGreaterThanOrEqual(4.5);
    expect(contrastRatio(lightTokens["--muted"], lightTokens["--surface"])).toBeGreaterThanOrEqual(4.5);
    expect(contrastRatio(lightTokens["--muted"], lightTokens["--surface2"])).toBeGreaterThanOrEqual(4.5);
    expect(contrastRatio(lightTokens["--accent"], lightTokens["--surface"])).toBeGreaterThanOrEqual(4.5);
    expect(contrastRatio(lightTokens["--accent"], lightTokens["--surface2"])).toBeGreaterThanOrEqual(4.5);
    expect(contrastRatio(lightTokens["--text-inverse"], lightTokens["--accent"])).toBeGreaterThanOrEqual(4.5);
    expect(contrastRatio(lightTokens["--good"], lightTokens["--surface"])).toBeGreaterThanOrEqual(4.5);
    expect(contrastRatio(lightTokens["--warn"], lightTokens["--surface"])).toBeGreaterThanOrEqual(4.5);
    expect(contrastRatio(lightTokens["--bad"], lightTokens["--surface"])).toBeGreaterThanOrEqual(4.5);
    expect(contrastRatio(lightTokens["--purple"], lightTokens["--surface"])).toBeGreaterThanOrEqual(4.5);
  });
});
