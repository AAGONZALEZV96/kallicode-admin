import { describe, it, expect } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import i18n, { changeAppLanguage, STORAGE_LANG_KEY } from "../i18n";
import es from "../i18n/locales/es.json";
import en from "../i18n/locales/en.json";
import {
  formatCurrencyEUR,
  formatDate,
  formatNumber,
  formatPercent,
  formatTokens,
} from "../i18n/formatters";
import { AuthProvider, UsuarioStaff } from "../estado/auth";
import { AdminLayout } from "../componentes/AdminLayout";
import { EstadoCarga } from "../componentes/EstadoCarga";
import { BizOverview } from "../vistas/BizOverview";
import { BizCustomers } from "../vistas/BizCustomers";
import { CustomerDetail } from "../vistas/CustomerDetail";
import { BizSubscriptions } from "../vistas/BizSubscriptions";
import { BizTokens } from "../vistas/BizTokens";
import { OpsAgents } from "../vistas/OpsAgents";
import { OpsModels } from "../vistas/OpsModels";
import { OpsSLA } from "../vistas/OpsSLA";

type JsonRecord = { [key: string]: unknown };

function flattenKeys(obj: JsonRecord, prefix = ""): Record<string, string> {
  const result: Record<string, string> = {};
  for (const [key, value] of Object.entries(obj)) {
    const path = prefix ? `${prefix}.${key}` : key;
    if (value !== null && typeof value === "object" && !Array.isArray(value)) {
      Object.assign(result, flattenKeys(value as JsonRecord, path));
    } else {
      result[path] = String(value ?? "");
    }
  }
  return result;
}

function extractPlaceholders(template: string): string[] {
  const matches = template.match(/\{\{\s*([a-zA-Z0-9_]+)\s*\}\}/g) ?? [];
  return matches.map((m) => m.replace(/\{\{|\}\}/g, "").trim()).sort();
}

function crearQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: { retry: false },
    },
  });
}

const ADMIN_STAFF: UsuarioStaff = {
  staff_id: "st_admin_i18n",
  email: "admin@kallicode.com",
  nombre: "Admin Staff",
  role: "staff_admin",
  mfa_validado: true,
};

function renderWithProviders(ui: React.ReactElement, initialRoute = "/") {
  const qc = crearQueryClient();
  return render(
    <MemoryRouter initialEntries={[initialRoute]}>
      <AuthProvider sesionInicial={{ usuario: ADMIN_STAFF, token: "jwt_admin_i18n" }}>
        <QueryClientProvider client={qc}>{ui}</QueryClientProvider>
      </AuthProvider>
    </MemoryRouter>
  );
}

describe("KC-ADM-B6-05 — Internacionalización Completa (i18n ES / EN)", () => {
  it("1. mantiene simetría estricta de claves, valores no vacíos e interpolación entre es.json y en.json", () => {
    const esFlat = flattenKeys(es as JsonRecord);
    const enFlat = flattenKeys(en as JsonRecord);

    const esKeys = Object.keys(esFlat).sort();
    const enKeys = Object.keys(enFlat).sort();

    const missingInEn = esKeys.filter((k) => !(k in enFlat));
    const extraInEn = enKeys.filter((k) => !(k in esFlat));

    expect(missingInEn).toEqual([]);
    expect(extraInEn).toEqual([]);
    expect(esKeys.length).toBeGreaterThan(150);

    for (const key of esKeys) {
      expect(esFlat[key].trim().length, `Clave vacía en es.json: ${key}`).toBeGreaterThan(0);
      expect(enFlat[key].trim().length, `Clave vacía en en.json: ${key}`).toBeGreaterThan(0);
      expect(
        extractPlaceholders(enFlat[key]),
        `Variables de interpolación distintas en clave: ${key}`
      ).toEqual(extractPlaceholders(esFlat[key]));
    }
  });

  it("2. formatea números, tokens, porcentajes, moneda EUR y fechas según el locale activo (Intl)", () => {
    expect(formatNumber(45000, undefined, "es")).toBe("45.000");
    expect(formatNumber(45000, undefined, "en")).toBe("45,000");

    expect(formatCurrencyEUR(120.5, "EUR", "es")).toContain("120,50");
    expect(formatCurrencyEUR(120.5, "EUR", "es")).toContain("€");
    expect(formatCurrencyEUR(120.5, "EUR", "en")).toBe("€120.50");

    expect(formatPercent(71.4, { decimals: 1, lang: "es" })).toContain("71,4");
    expect(formatPercent(71.4, { decimals: 1, lang: "en" })).toBe("71.4%");
    expect(formatPercent(12.5, { decimals: 1, includeSign: true, lang: "en" })).toBe("+12.5%");

    expect(formatTokens(80_000_000, { compact: true, lang: "en" })).toBe("80.0M");
    expect(formatDate("2026-11-21T10:00:00Z", undefined, "en")).toContain("Nov");
  });

  it("3. el selector de idioma en AdminLayout cambia entre es y en, persiste preferencia y actualiza <html lang>", async () => {
    render(
      <MemoryRouter initialEntries={["/overview"]}>
        <AuthProvider sesionInicial={{ usuario: ADMIN_STAFF, token: "jwt_admin_i18n" }}>
          <Routes>
            <Route element={<AdminLayout />}>
              <Route path="/overview" element={<div>contenido</div>} />
            </Route>
          </Routes>
        </AuthProvider>
      </MemoryRouter>
    );

    expect(document.documentElement.lang).toBe("es");
    expect(screen.getByText("Panel Negocio")).toBeDefined();
    expect(screen.getByText("Cerrar Sesión")).toBeDefined();

    const selector = screen.getByTestId("selector-idioma") as HTMLSelectElement;
    expect(selector.value).toBe("es");

    fireEvent.change(selector, { target: { value: "en" } });

    await waitFor(() => {
      expect(document.documentElement.lang).toBe("en");
      expect(i18n.language).toBe("en");
      expect(window.localStorage.getItem(STORAGE_LANG_KEY)).toBe("en");
      expect(screen.getByText("Business Overview")).toBeDefined();
      expect(screen.getByText("Subscriptions")).toBeDefined();
      expect(screen.getByText("Token Usage")).toBeDefined();
      expect(screen.getByText("Customers")).toBeDefined();
      expect(screen.getByText("Agents")).toBeDefined();
      expect(screen.getByText("Models")).toBeDefined();
      expect(screen.getByText("Sign Out")).toBeDefined();
    });
  });

  it("4. EstadoCarga traduce el mensaje accesible por defecto en es y en", async () => {
    const { rerender } = render(<EstadoCarga tipo="kpis" />);
    expect(screen.getByText("Cargando datos...")).toBeDefined();

    await changeAppLanguage("en");
    rerender(<EstadoCarga tipo="kpis" />);
    expect(screen.getByText("Loading data...")).toBeDefined();
  });

  it("5. BizOverview, BizCustomers, CustomerDetail, BizSubscriptions y BizTokens renderizan en es y en", async () => {
    await changeAppLanguage("en");

    // BizOverview
    const v1 = renderWithProviders(<BizOverview />);
    await waitFor(() => {
      expect(screen.getByText("Business Overview")).toBeDefined();
    });
    expect(screen.getByText("Monthly Recurring Revenue")).toBeDefined();
    expect(screen.getByTestId("kpi-mrr").textContent).toContain("€45,000.00");
    v1.unmount();

    // BizCustomers
    const v2 = renderWithProviders(<BizCustomers />);
    await waitFor(() => {
      expect(screen.getByText("Customers & Organizations Directory")).toBeDefined();
    });
    expect(screen.getByText("Legal Name")).toBeDefined();
    v2.unmount();

    // CustomerDetail
    const qc3 = crearQueryClient();
    const v3 = render(
      <MemoryRouter initialEntries={["/business/customers/org_acme"]}>
        <AuthProvider sesionInicial={{ usuario: ADMIN_STAFF, token: "jwt_admin_i18n" }}>
          <QueryClientProvider client={qc3}>
            <Routes>
              <Route path="/business/customers/:tenant_id" element={<CustomerDetail />} />
            </Routes>
          </QueryClientProvider>
        </AuthProvider>
      </MemoryRouter>
    );
    await waitFor(() => {
      expect(screen.getByText("1. Identification & Subscription")).toBeDefined();
    });
    expect(screen.getByText("6. Pipeline Activity & CodeMapping Structure")).toBeDefined();
    v3.unmount();

    // BizSubscriptions
    const v4 = renderWithProviders(<BizSubscriptions />);
    await waitFor(() => {
      expect(screen.getByText("Subscriptions & Renewals Management")).toBeDefined();
    });
    expect(screen.getByTestId("tab-renovaciones").textContent).toContain("Renewals Radar");
    v4.unmount();

    // BizTokens
    const v5 = renderWithProviders(<BizTokens />);
    await waitFor(() => {
      expect(screen.getByText("Token Usage & FinOps")).toBeDefined();
      expect(screen.getByText("Consolidated Cost")).toBeDefined();
    });
    v5.unmount();
  });

  it("6. OpsAgents, OpsModels y OpsSLA renderizan correctamente en inglés sin claves crudas", async () => {
    await changeAppLanguage("en");

    // OpsAgents
    const v1 = renderWithProviders(<OpsAgents />);
    await waitFor(() => {
      expect(screen.getByText("Production Agents & Queues Status")).toBeDefined();
      expect(screen.getByText("Throughput by Pipeline Stage")).toBeDefined();
    });
    expect(screen.getByText("LIVE")).toBeDefined();
    v1.unmount();

    // OpsModels
    const v2 = renderWithProviders(<OpsModels />);
    await waitFor(() => {
      expect(screen.getByText("LLM Models & Core Services Metrics")).toBeDefined();
      expect(screen.getByTestId("card-tier-flash").textContent).toContain("€120.50");
    });
    expect(screen.getByText("Core Services & Dependencies Health")).toBeDefined();
    v2.unmount();

    // OpsSLA
    const v3 = renderWithProviders(<OpsSLA />);
    await waitFor(() => {
      expect(screen.getByText("SLA Compliance & Service Incidents")).toBeDefined();
      expect(screen.getByTestId("kpi-cumplimiento-global").textContent).toContain("71.4%");
    });
    expect(screen.getByText("Global Compliance")).toBeDefined();
    v3.unmount();
  });
});
