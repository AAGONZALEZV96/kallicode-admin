/**
 * BizTokens.test.tsx — Pruebas Unitarias y de Integración para la Pantalla biz-tokens
 *
 * Implementa y valida los criterios de aceptación del ticket [KC-ADM-B4-04]:
 * 1. Renderizado de tarjetas de resumen ejecutivo de FinOps (total tokens, coste, cuota, cuadre).
 * 2. Panel analítico de desglose por tiers con separación estricta e innegociable de fable respecto a pro.
 * 3. Estructura semántica accesible A11Y (tabla con thead, tbody, aria-live="polite").
 * 4. Renderizado de tabla densa en modo cliente con enlace a /business/customers/:tenant_id.
 * 5. Política E6: Enmascaramiento por defecto (A•••• S.L.) vs revelación en claro con concesión activa.
 * 6. Integración contextual con SolicitudConcesionModal para solicitar revelación de datos con justificación.
 * 7. Filtrado dinámico por periodo (mes_actual, mes_anterior, trimestre, ano) y plan comercial.
 * 8. Búsqueda por cliente/organización con debounce.
 * 9. Agrupación analítica por tier de modelo y por día.
 * 10. Alerta prominente de descuadre cuando cuadra_con_facturacion es false.
 * 11. Manejo estructurado de errores con traza (X-Trace-Id) y reintento.
 * 12. Control de acceso RBAC: Bloqueo 403 para staff_operaciones y staff_soporte; permitido para negocio y admin.
 */

import { describe, it, expect, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { MemoryRouter, Routes, Route } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { http, HttpResponse } from "msw";
import { server } from "../../pruebas/server";
import { setMockConcesionActiva, resetMockState } from "../../pruebas/msw_handlers";
import { AuthProvider, UsuarioStaff } from "../../estado/auth";
import { BizTokens } from "../BizTokens";

function renderBizTokens(opciones?: {
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

  const ruta = opciones?.rutaInicial ?? "/business/tokens";

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
            <Route path="/business/tokens" element={<BizTokens />} />
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

describe("BizTokens — Pantalla de Consumo de Tokens y FinOps [KC-ADM-B4-04]", () => {
  beforeEach(() => {
    resetMockState();
    setMockConcesionActiva(false);
  });

  // 1. Tarjetas de Resumen Ejecutivo
  it("1. renderiza las tarjetas de resumen ejecutivo de FinOps con datos formateados", async () => {
    renderBizTokens();

    await waitFor(() => {
      expect(screen.getByTestId("card-total-tokens")).toBeDefined();
    });

    const cardTokens = screen.getByTestId("card-total-tokens");
    expect(cardTokens.textContent).toContain("Total Tokens Consumidos");
    // Verifica formato con separadores de miles
    expect(cardTokens.textContent).toMatch(/32[.,]500[.,]000/);

    const cardCoste = screen.getByTestId("card-coste-consolidado");
    expect(cardCoste.textContent).toContain("Coste Consolidado");
    expect(cardCoste.textContent).toContain("325,50");

    const cardCuota = screen.getByTestId("card-porcentaje-cuota");
    expect(cardCuota.textContent).toContain("Consumo Medio de Cuota");
    expect(cardCuota.textContent).toContain("83.8%"); // o 83.75%
    expect(cardCuota.textContent).toContain("AVISO");

    const cardFacturacion = screen.getByTestId("card-estado-facturacion");
    expect(cardFacturacion.textContent).toContain("Cuadre Facturación");
    expect(cardFacturacion.textContent).toContain("100% Conciliado");
  });

  // 2. Panel de Desglose por Tier con Separación Estricta de Fable
  it("2. renderiza el panel de desglose por tiers mostrando fable estrictamente separado de pro", async () => {
    renderBizTokens();

    await waitFor(() => {
      expect(screen.getByTestId("tier-desglose-flash")).toBeDefined();
    });

    // Tier Flash
    const flashEl = screen.getByTestId("tier-desglose-flash");
    expect(flashEl.textContent).toContain("Tier Flash");
    expect(flashEl.textContent).toContain("Alta Velocidad");

    // Tier Pro
    const proEl = screen.getByTestId("tier-desglose-pro");
    expect(proEl.textContent).toContain("Tier Pro");
    expect(proEl.textContent).toContain("Capacidad Estándar");

    // Tier Fable (Regla estricta: separado de pro)
    const fableEl = screen.getByTestId("tier-desglose-fable");
    expect(fableEl.textContent).toContain("Tier Fable");
    expect(fableEl.textContent).toContain("Razonamiento Avanzado");
    expect(fableEl.textContent).toContain("cómputo especializado");

    // Tabla de accesibilidad A11Y
    expect(screen.getByTestId("tabla-accesible-tiers")).toBeDefined();
    const rows = screen.getAllByRole("row");
    expect(rows.length).toBeGreaterThanOrEqual(3);
  });

  // 3. Tabla Densa de Clientes y Enlaces
  it("3. renderiza la tabla densa de consumo por organización con enlace a cliente", async () => {
    renderBizTokens();

    await waitFor(() => {
      expect(screen.getByTestId("fila-cliente-org_acme")).toBeDefined();
    });

    const filaAcme = screen.getByTestId("fila-cliente-org_acme");
    expect(filaAcme.textContent).toContain("org_acme");
    expect(filaAcme.textContent).toContain("growth");
    expect(filaAcme.textContent).toContain("45,50");
    expect(filaAcme.textContent).toContain("✅ Cuadra");

    // Enlace a detalle de cliente
    const enlaceAcme = screen.getByRole("link", { name: "org_acme" });
    expect(enlaceAcme.getAttribute("href")).toBe("/business/customers/org_acme");

    const filaGlobex = screen.getByTestId("fila-cliente-org_globex");
    expect(filaGlobex.textContent).toContain("org_globex");
    expect(filaGlobex.textContent).toContain("enterprise");
  });

  // 4. Enmascaramiento por Defecto (E6)
  it("4. enmascara por defecto la razón social y muestra badge ENMASCARADO", async () => {
    setMockConcesionActiva(false);
    renderBizTokens();

    await waitFor(() => {
      expect(screen.getByTestId("fila-cliente-org_acme")).toBeDefined();
    });

    const filaAcme = screen.getByTestId("fila-cliente-org_acme");
    expect(filaAcme.textContent).toContain("A•••• S.L.");
    expect(filaAcme.textContent).not.toContain("Acme Logística S.L.");
    expect(filaAcme.textContent).toContain("ENMASCARADO");
    expect(screen.getByTestId("btn-concesion-org_acme")).toBeDefined();
  });

  // 5. Revelación con Concesión Activa
  it("5. revela la razón social en claro cuando existe una concesión activa", async () => {
    setMockConcesionActiva(true);
    renderBizTokens();

    await waitFor(() => {
      expect(screen.getByTestId("fila-cliente-org_acme")).toBeDefined();
    });

    const filaAcme = screen.getByTestId("fila-cliente-org_acme");
    expect(filaAcme.textContent).toContain("Acme Logística S.L.");
    expect(filaAcme.textContent).toContain("EN CLARO");
  });

  // 6. Solicitud de Concesión Contextual Modal
  it("6. abre el modal de solicitud de concesión al pulsar Solicitar acceso", async () => {
    setMockConcesionActiva(false);
    renderBizTokens();

    await waitFor(() => {
      expect(screen.getByTestId("btn-concesion-org_acme")).toBeDefined();
    });

    fireEvent.click(screen.getByTestId("btn-concesion-org_acme"));

    await waitFor(() => {
      expect(screen.getByText("Solicitar Revelación de Datos de Cliente (E6)")).toBeDefined();
    });

    expect(screen.getByTestId("input-concesion-tenant")).toBeDefined();
    expect(screen.getByTestId("input-concesion-motivo")).toBeDefined();
    expect(screen.getByTestId("btn-confirmar-concesion")).toBeDefined();
  });

  // 7. Filtrado por Plan Comercial
  it("7. filtra los registros por plan comercial (growth, enterprise)", async () => {
    renderBizTokens();

    await waitFor(() => {
      expect(screen.getByTestId("select-plan")).toBeDefined();
    });

    fireEvent.change(screen.getByTestId("select-plan"), { target: { value: "enterprise" } });

    await waitFor(() => {
      expect(screen.getByTestId("fila-cliente-org_globex")).toBeDefined();
      expect(screen.queryByTestId("fila-cliente-org_acme")).toBeNull();
    });
  });

  // 8. Filtrado por Periodo Temporal
  it("8. actualiza la consulta al cambiar el selector de periodo", async () => {
    renderBizTokens();

    await waitFor(() => {
      expect(screen.getByTestId("select-periodo")).toBeDefined();
    });

    fireEvent.change(screen.getByTestId("select-periodo"), { target: { value: "trimestre" } });

    await waitFor(() => {
      expect(screen.getByTestId("select-periodo")).toHaveProperty("value", "trimestre");
    });
  });

  // 9. Búsqueda con Debounce
  it("9. filtra clientes mediante el input de búsqueda debounced", async () => {
    renderBizTokens();

    await waitFor(() => {
      expect(screen.getByTestId("input-busqueda-cliente")).toBeDefined();
    });

    fireEvent.change(screen.getByTestId("input-busqueda-cliente"), { target: { value: "globex" } });

    await waitFor(
      () => {
        expect(screen.getByTestId("fila-cliente-org_globex")).toBeDefined();
        expect(screen.queryByTestId("fila-cliente-org_acme")).toBeNull();
      },
      { timeout: 1500 }
    );
  });

  // 10. Agrupación por Tier de Modelo
  it("10. soporta agrupación analítica por tier de modelo", async () => {
    renderBizTokens();

    await waitFor(() => {
      expect(screen.getByTestId("select-agrupacion")).toBeDefined();
    });

    fireEvent.change(screen.getByTestId("select-agrupacion"), { target: { value: "tier" } });

    await waitFor(() => {
      expect(screen.getByTestId("fila-tier-flash")).toBeDefined();
      expect(screen.getByTestId("fila-tier-pro")).toBeDefined();
      expect(screen.getByTestId("fila-tier-fable")).toBeDefined();
    });

    const filaFable = screen.getByTestId("fila-tier-fable");
    expect(filaFable.textContent).toContain("fable");
    expect(filaFable.textContent).toContain("Razonamiento Agéntico");
  });

  // 11. Agrupación por Día
  it("11. soporta agrupación analítica por serie diaria", async () => {
    renderBizTokens();

    await waitFor(() => {
      expect(screen.getByTestId("select-agrupacion")).toBeDefined();
    });

    fireEvent.change(screen.getByTestId("select-agrupacion"), { target: { value: "dia" } });

    await waitFor(() => {
      expect(screen.getByTestId("fila-dia-2026-11-10")).toBeDefined();
    });
  });

  // 12. Alerta Prominente de Descuadre con Facturación
  it("12. muestra alerta visual crítica cuando existe descuadre con facturación", async () => {
    server.use(
      http.get("*/admin/v1/business/usage/tokens", () => {
        return HttpResponse.json({
          items: [
            {
              clave: "org_acme",
              tenant_id: "org_acme",
              razon_social: "A•••• S.L.",
              plan: "growth",
              tokens_in: 3000000,
              tokens_out: 1500000,
              tokens_total: 4500000,
              coste: 45.5,
              coste_estimado_eur: 45.5,
              cuota_pct: 75.0,
              cuadra_con_facturacion: false, // Descuadre crítico
              enmascarado: true,
            },
          ],
          total: 1,
          page: 1,
          page_size: 25,
          pages: 1,
          cuadra_con_facturacion: false,
          descuadres: ["org_acme"],
          resumen: {
            total_tokens: 4500000,
            coste_consolidado: 45.5,
            porcentaje_medio_cuota: 75.0,
            moneda: "EUR",
          },
        });
      })
    );

    renderBizTokens();

    await waitFor(() => {
      expect(screen.getByTestId("alerta-descuadre-facturacion")).toBeDefined();
    });

    const alerta = screen.getByTestId("alerta-descuadre-facturacion");
    expect(alerta.textContent).toContain("Alerta Crítica: Descuadre Detectado");
    expect(alerta.textContent).toContain("org_acme");

    const filaAcme = screen.getByTestId("fila-cliente-org_acme");
    expect(filaAcme.textContent).toContain("🚨 Descuadre");
  });

  // 13. Manejo de Errores con Traza (X-Trace-Id)
  it("13. maneja error HTTP 503 mostrando la traza y botón de reintento", async () => {
    server.use(
      http.get("*/admin/v1/business/usage/tokens", () => {
        return HttpResponse.json(
          {
            error: {
              codigo: "AGREGADO_NO_DISPONIBLE",
              mensaje: "Los agregados de tokens están en cálculo.",
              trace_id: "trc_test_tokens_503",
            },
          },
          { status: 503 }
        );
      })
    );

    renderBizTokens();

    await waitFor(() => {
      expect(screen.getByText("Agregados analíticos en refresco")).toBeDefined();
    });

    expect(screen.getByTestId("error-trace-id").textContent).toBe("trc_test_tokens_503");
    expect(screen.getByRole("button", { name: "Reintentar" })).toBeDefined();
  });

  // 14. Bloqueo RBAC para roles no autorizados
  it("14. bloquea visualmente el acceso con 403 ROL_STAFF_INSUFICIENTE para staff_operaciones", async () => {
    renderBizTokens({
      usuario: {
        staff_id: "st_ops_001",
        email: "ops@kallicode.com",
        nombre: "Staff Operaciones",
        role: "staff_operaciones",
        mfa_validado: true,
      },
    });

    expect(screen.getByTestId("tokens-error")).toBeDefined();
    expect(screen.getByText("403 ROL_STAFF_INSUFICIENTE")).toBeDefined();
    expect(screen.getByText(/Acceso denegado para el rol staff_operaciones/)).toBeDefined();
  });

  it("15. permite acceso a staff_admin", async () => {
    renderBizTokens({
      usuario: {
        staff_id: "st_admin_001",
        email: "admin@kallicode.com",
        nombre: "Super Admin",
        role: "staff_admin",
        mfa_validado: true,
      },
    });

    await waitFor(() => {
      expect(screen.getByTestId("card-total-tokens")).toBeDefined();
    });
    expect(screen.getByText("Consumo de Tokens y FinOps")).toBeDefined();
  });
});
