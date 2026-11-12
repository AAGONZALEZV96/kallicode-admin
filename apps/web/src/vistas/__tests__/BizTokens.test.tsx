/**
 * BizTokens.test.tsx — Pruebas de Componentes React para Gráficos de Tendencias de Tokens
 *
 * Implementa el ticket [KC-ADM-B4-10] (Épica EAD4 / ADM-G08 / ADM-G12 / §18.21):
 * 1. Renderizado Visual y Precisión Matemática:
 *    - Validación de métricas obligatorias (tokens_in, tokens_out, tokens_total, coste, cuota).
 *    - Representación precisa de cifras formateadas con separadores de miles y moneda EUR.
 * 2. Regla Inviolable de Fable:
 *    - Fable posee serie independiente en barra proporcional, tarjeta visual y tabla accesible.
 *    - Fable posee color independiente (var(--warn)) diferenciado de pro (var(--purple)) y flash (var(--accent)).
 *    - Fable NO se agrupa ni diluye en pro o flash.
 *    - Garantía matemática estricta: suma exacta de porcentajes = 100%.
 * 3. Accesibilidad (A11Y) y Alternativa Textual:
 *    - Región semántica con role="region" y aria-label.
 *    - Alternativa textual descriptiva en barra role="img" con aria-label.
 *    - Tabla semántica accesible con summary, caption/cabeceras y aria-live="polite".
 *    - Anuncios reactivos mediante aria-live="polite" ante cambios dinámicos de filtros (periodo, plan, agrupación, búsqueda).
 * 4. Simulación de Estados de Interfaz:
 *    - Estado de Carga (EstadoCarga con aria-busy="true" y skeleton accesible).
 *    - Estado Vacío (EstadoVacio sin errores JavaScript ni divisiones por cero, con botón de reseteo).
 *    - Estado de Error (EstadoError con HTTP 503 AGREGADO_NO_DISPONIBLE, X-Trace-Id y botón Reintentar).
 *    - Control de Acceso RBAC (403 ROL_STAFF_INSUFICIENTE para operaciones y soporte, permitido para negocio y admin).
 * 5. Filtros Dinámicos, Paginación y Privacidad E6:
 *    - Filtrado reactivo por periodo (mes_actual, mes_anterior, trimestre, ano), plan comercial y agrupación.
 *    - Búsqueda debounced por organización cliente.
 *    - Paginación transversal (cambio de tamaño y navegación).
 *    - Política E6 de enmascaramiento por defecto y revelación con concesión activa.
 */

import { describe, it, expect, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { MemoryRouter, Routes, Route } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { http, HttpResponse, delay } from "msw";
import { server } from "../../pruebas/server";
import { setMockConcesionActiva, resetMockState } from "../../pruebas/msw_handlers";
import { AuthProvider, UsuarioStaff } from "../../estado/auth";
import { BizTokens } from "../BizTokens";

function renderBizTokens(opciones?: {
  usuario?: UsuarioStaff;
  rutaInicial?: string;
  queryClient?: QueryClient;
}) {
  const queryClient =
    opciones?.queryClient ??
    new QueryClient({
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

describe("BizTokens — Pruebas de Componentes React y Gráficos de Tendencias [KC-ADM-B4-10]", () => {
  beforeEach(() => {
    resetMockState();
    setMockConcesionActiva(false);
  });

  // ============================================================================
  // 1. Renderizado Visual y Métricas Matemáticas (FinOps)
  // ============================================================================
  describe("1. Renderizado Visual y Métricas Matemáticas", () => {
    it("renderiza las tarjetas de resumen ejecutivo de FinOps con datos matemáticos precisos", async () => {
      renderBizTokens();

      await waitFor(() => {
        expect(screen.getByTestId("card-total-tokens")).toBeDefined();
      });

      // Total Tokens
      const cardTokens = screen.getByTestId("card-total-tokens");
      expect(cardTokens.textContent).toContain("Total Tokens Consumidos");
      expect(cardTokens.textContent).toMatch(/32[.,]500[.,]000/);

      // Coste Consolidado
      const cardCoste = screen.getByTestId("card-coste-consolidado");
      expect(cardCoste.textContent).toContain("Coste Consolidado");
      expect(cardCoste.textContent).toContain("325,50");

      // Cuota de Consumo Media
      const cardCuota = screen.getByTestId("card-porcentaje-cuota");
      expect(cardCuota.textContent).toContain("Consumo Medio de Cuota");
      expect(cardCuota.textContent).toContain("83.8%");
      expect(cardCuota.textContent).toContain("AVISO");

      // Cuadre con Facturación
      const cardFacturacion = screen.getByTestId("card-estado-facturacion");
      expect(cardFacturacion.textContent).toContain("Cuadre Facturación");
      expect(cardFacturacion.textContent).toContain("100% Conciliado");
    });

    it("muestra badge SATURADA (>100%) cuando la cuota media supera el 100%", async () => {
      server.use(
        http.get("*/admin/v1/business/usage/tokens", () => {
          return HttpResponse.json({
            items: [
              {
                clave: "org_acme",
                tenant_id: "org_acme",
                razon_social: "A•••• S.L.",
                plan: "growth",
                tokens_in: 5000000,
                tokens_out: 2000000,
                tokens_total: 7000000,
                coste: 70.0,
                coste_estimado_eur: 70.0,
                cuota_pct: 120.0,
                cuadra_con_facturacion: true,
                enmascarado: true,
              },
            ],
            total: 1,
            page: 1,
            page_size: 25,
            pages: 1,
            cuadra_con_facturacion: true,
            resumen: {
              total_tokens: 7000000,
              coste_consolidado: 70.0,
              porcentaje_medio_cuota: 120.0,
              moneda: "EUR",
            },
          });
        })
      );

      renderBizTokens();

      await waitFor(() => {
        expect(screen.getByTestId("card-porcentaje-cuota")).toBeDefined();
      });

      const cardCuota = screen.getByTestId("card-porcentaje-cuota");
      expect(cardCuota.textContent).toContain("SATURADA (>100%)");
      expect(cardCuota.textContent).toContain("120.0%");
    });

    it("muestra badge NORMAL cuando la cuota media es inferior al 80%", async () => {
      server.use(
        http.get("*/admin/v1/business/usage/tokens", () => {
          return HttpResponse.json({
            items: [
              {
                clave: "org_acme",
                tenant_id: "org_acme",
                razon_social: "A•••• S.L.",
                plan: "growth",
                tokens_in: 2000000,
                tokens_out: 1000000,
                tokens_total: 3000000,
                coste: 30.0,
                coste_estimado_eur: 30.0,
                cuota_pct: 55.0,
                cuadra_con_facturacion: true,
                enmascarado: true,
              },
            ],
            total: 1,
            page: 1,
            page_size: 25,
            pages: 1,
            cuadra_con_facturacion: true,
            resumen: {
              total_tokens: 3000000,
              coste_consolidado: 30.0,
              porcentaje_medio_cuota: 55.0,
              moneda: "EUR",
            },
          });
        })
      );

      renderBizTokens();

      await waitFor(() => {
        expect(screen.getByTestId("card-porcentaje-cuota")).toBeDefined();
      });

      const cardCuota = screen.getByTestId("card-porcentaje-cuota");
      expect(cardCuota.textContent).toContain("NORMAL");
      expect(cardCuota.textContent).toContain("55.0%");
    });
  });

  // ============================================================================
  // 2. Regla Inviolable de Fable y Distribución por Tier
  // ============================================================================
  describe("2. Regla Inviolable de Fable y Distribución por Tier", () => {
    it("renderiza el panel de tendencias con serie, color y representación independiente para fable", async () => {
      renderBizTokens();

      await waitFor(() => {
        expect(screen.getByTestId("panel-graficos-tendencias")).toBeDefined();
      });

      const panel = screen.getByTestId("panel-graficos-tendencias");
      expect(panel.getAttribute("role")).toBe("region");
      expect(panel.getAttribute("aria-label")).toContain("Panel de tendencias");

      // Barra proporcional con role="img"
      const barra = screen.getByTestId("barra-distribucion-proporcional");
      expect(barra.getAttribute("role")).toBe("img");

      // Segmentos independientes de cada tier
      const segFlash = screen.getByTestId("segmento-flash");
      const segPro = screen.getByTestId("segmento-pro");
      const segFable = screen.getByTestId("segmento-fable");

      expect(segFlash).toBeDefined();
      expect(segPro).toBeDefined();
      expect(segFable).toBeDefined();

      // Colores estrictamente independientes
      expect(segFlash.style.backgroundColor).toBe("var(--accent)");
      expect(segPro.style.backgroundColor).toBe("var(--purple)");
      expect(segFable.style.backgroundColor).toBe("var(--warn)");

      // Prohibición arquitectónica: fable != pro y fable != flash
      expect(segFable.style.backgroundColor).not.toBe(segPro.style.backgroundColor);
      expect(segFable.style.backgroundColor).not.toBe(segFlash.style.backgroundColor);

      // Tarjetas visuales independientes
      const tarjetaFable = screen.getByTestId("tier-desglose-fable");
      expect(tarjetaFable.textContent).toContain("Tier Fable");
      expect(tarjetaFable.textContent).toContain("Razonamiento Avanzado");
      expect(tarjetaFable.textContent).toContain("cómputo especializado");

      const tarjetaPro = screen.getByTestId("tier-desglose-pro");
      expect(tarjetaPro.textContent).toContain("Tier Pro");
      expect(tarjetaPro.textContent).toContain("Capacidad Estándar");

      const tarjetaFlash = screen.getByTestId("tier-desglose-flash");
      expect(tarjetaFlash.textContent).toContain("Tier Flash");
      expect(tarjetaFlash.textContent).toContain("Alta Velocidad");
    });

    it("garantiza matemáticamente que la suma de porcentajes de los tiers es exactamente 100%", async () => {
      renderBizTokens();

      await waitFor(() => {
        expect(screen.getByTestId("barra-distribucion-proporcional")).toBeDefined();
      });

      const segFlash = screen.getByTestId("segmento-flash");
      const segPro = screen.getByTestId("segmento-pro");
      const segFable = screen.getByTestId("segmento-fable");

      const pctFlash = parseInt(segFlash.style.width.replace("%", ""), 10);
      const pctPro = parseInt(segPro.style.width.replace("%", ""), 10);
      const pctFable = parseInt(segFable.style.width.replace("%", ""), 10);

      // Validación de tolerancia cero: suma exacta = 100%
      expect(pctFlash + pctPro + pctFable).toBe(100);
      expect(pctFable).toBeGreaterThan(0);
      expect(pctPro).toBeGreaterThan(0);
      expect(pctFlash).toBeGreaterThan(0);
    });

    it("mantiene fable 100% segregado y nunca diluido en la tabla accesible de tiers", async () => {
      renderBizTokens();

      await waitFor(() => {
        expect(screen.getByTestId("tabla-accesible-tiers")).toBeDefined();
      });

      const tablaTiers = screen.getByTestId("tabla-accesible-tiers");
      expect(tablaTiers.textContent).toContain("Flash");
      expect(tablaTiers.textContent).toContain("Inferencia Ligera");
      expect(tablaTiers.textContent).toContain("Pro");
      expect(tablaTiers.textContent).toContain("Inferencia General");
      expect(tablaTiers.textContent).toContain("Fable");
      expect(tablaTiers.textContent).toContain("Razonamiento Agéntico");
    });
  });

  // ============================================================================
  // 3. Accesibilidad (A11Y) y Alternativa Textual en Gráficos
  // ============================================================================
  describe("3. Accesibilidad (A11Y) y Alternativa Textual", () => {
    it("provee alternativa textual accesible con role='img' y aria-label descriptivo", async () => {
      renderBizTokens();

      await waitFor(() => {
        expect(screen.getByTestId("barra-distribucion-proporcional")).toBeDefined();
      });

      const barra = screen.getByTestId("barra-distribucion-proporcional");
      const ariaLabel = barra.getAttribute("aria-label") || "";
      expect(ariaLabel).toMatch(/Distribución por tier:/);
      expect(ariaLabel).toMatch(/Flash \d+%/);
      expect(ariaLabel).toMatch(/Pro \d+%/);
      expect(ariaLabel).toMatch(/Fable \d+%/);
    });

    it("incluye summary estructurado y contenedor con aria-live='polite' en tabla accesible", async () => {
      renderBizTokens();

      await waitFor(() => {
        expect(screen.getByTestId("tabla-accesible-tiers")).toBeDefined();
      });

      const tabla = screen.getByTestId("tabla-accesible-tiers");
      expect(tabla.getAttribute("summary")).toBe(
        "Tabla de resumen accesible de tokens consumidos por tier de modelo"
      );

      const contenedorTabla = tabla.parentElement;
      expect(contenedorTabla?.getAttribute("aria-live")).toBe("polite");
    });

    it("anuncia reactivamente los cambios de filtros mediante aria-live='polite'", async () => {
      renderBizTokens();

      await waitFor(() => {
        expect(screen.getByTestId("anuncio-filtros-dinamicos")).toBeDefined();
      });

      const anuncio = screen.getByTestId("anuncio-filtros-dinamicos");
      expect(anuncio.getAttribute("aria-live")).toBe("polite");
      expect(anuncio.getAttribute("role")).toBe("status");
      expect(anuncio.textContent).toContain("Periodo mes_actual");

      // 1. Cambio de periodo a mes_anterior
      fireEvent.change(screen.getByTestId("select-periodo"), {
        target: { value: "mes_anterior" },
      });
      await waitFor(() => {
        expect(anuncio.textContent).toContain("Periodo mes_anterior");
      });

      // 2. Cambio de plan a growth
      fireEvent.change(screen.getByTestId("select-plan"), {
        target: { value: "growth" },
      });
      await waitFor(() => {
        expect(anuncio.textContent).toContain("Plan growth");
      });

      // 3. Cambio de agrupación a tier
      fireEvent.change(screen.getByTestId("select-agrupacion"), {
        target: { value: "tier" },
      });
      await waitFor(() => {
        expect(anuncio.textContent).toContain("Agrupación tier");
      });

      // 4. Cambio de agrupación a dia
      fireEvent.change(screen.getByTestId("select-agrupacion"), {
        target: { value: "dia" },
      });
      await waitFor(() => {
        expect(anuncio.textContent).toContain("Agrupación dia");
      });
    });
  });

  // ============================================================================
  // 4. Simulación de Estados de Interfaz (Carga, Vacío, Error, RBAC)
  // ============================================================================
  describe("4. Simulación de Estados de Interfaz", () => {
    it("renderiza EstadoCarga con aria-busy='true' y skeleton mientras los datos están pendientes", async () => {
      server.use(
        http.get("*/admin/v1/business/usage/tokens", async () => {
          await delay(200);
          return HttpResponse.json({
            items: [],
            total: 0,
            page: 1,
            page_size: 25,
            pages: 1,
          });
        })
      );

      renderBizTokens();

      // Debe mostrar el contenedor de carga con role="status" y aria-busy="true"
      const estadoCarga = screen.getByTestId("estado-carga");
      expect(estadoCarga).toBeDefined();
      expect(estadoCarga.getAttribute("role")).toBe("status");
      expect(estadoCarga.getAttribute("aria-busy")).toBe("true");
    });

    it("renderiza EstadoVacio cuando los filtros no arrojan datos sin errores ni divisiones por cero", async () => {
      server.use(
        http.get("*/admin/v1/business/usage/tokens", () => {
          return HttpResponse.json({
            items: [],
            total: 0,
            page: 1,
            page_size: 25,
            pages: 1,
            cuadra_con_facturacion: true,
            resumen: {
              total_tokens: 0,
              coste_consolidado: 0,
              porcentaje_medio_cuota: 0,
              moneda: "EUR",
            },
          });
        })
      );

      renderBizTokens();

      await waitFor(() => {
        expect(screen.getByTestId("estado-vacio")).toBeDefined();
      });

      expect(screen.getByText("Sin datos de consumo de tokens")).toBeDefined();
      expect(
        screen.getByText(
          "No existen registros de consumo de inferencia para los filtros y periodo seleccionados."
        )
      ).toBeDefined();

      // Botón de acción para limpiar filtros
      const btnLimpiar = screen.getByTestId("btn-accion-vacio");
      expect(btnLimpiar).toBeDefined();
      expect(btnLimpiar.textContent).toContain("Limpiar Filtros");

      // Al hacer click, limpia los parámetros
      fireEvent.click(btnLimpiar);
      expect(screen.getByTestId("estado-vacio")).toBeDefined();
    });

    it("renderiza EstadoError ante un fallo HTTP 503 con código AGREGADO_NO_DISPONIBLE y botón de reintento", async () => {
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
      const btnReintentar = screen.getByRole("button", { name: "Reintentar" });
      expect(btnReintentar).toBeDefined();

      // Probar que el botón reintentar se puede pulsar
      fireEvent.click(btnReintentar);
    });

    it("renderiza EstadoError ante un error de red genérico", async () => {
      server.use(
        http.get("*/admin/v1/business/usage/tokens", () => {
          return HttpResponse.json(
            {
              error: {
                codigo: "ERROR_INTERNO",
                mensaje: "Fallo inesperado del subsistema analítico.",
                trace_id: "trc_test_500",
              },
            },
            { status: 500 }
          );
        })
      );

      renderBizTokens();

      await waitFor(() => {
        expect(screen.getByText("Error al cargar consumo de tokens")).toBeDefined();
      });

      expect(screen.getByTestId("error-trace-id").textContent).toBe("trc_test_500");
    });

    it("bloquea el acceso con 403 ROL_STAFF_INSUFICIENTE para staff_operaciones", async () => {
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

    it("bloquea el acceso con 403 ROL_STAFF_INSUFICIENTE para staff_soporte", async () => {
      renderBizTokens({
        usuario: {
          staff_id: "st_sop_001",
          email: "soporte@kallicode.com",
          nombre: "Staff Soporte",
          role: "staff_soporte",
          mfa_validado: true,
        },
      });

      expect(screen.getByTestId("tokens-error")).toBeDefined();
      expect(screen.getByText("403 ROL_STAFF_INSUFICIENTE")).toBeDefined();
      expect(screen.getByText(/Acceso denegado para el rol staff_soporte/)).toBeDefined();
    });

    it("permite acceso normal a staff_admin", async () => {
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

  // ============================================================================
  // 5. Filtros Dinámicos, Búsqueda, Paginación y Privacidad E6
  // ============================================================================
  describe("5. Filtros Dinámicos, Paginación y Privacidad E6", () => {
    it("filtra clientes por plan comercial growth y enterprise", async () => {
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

    it("actualiza la consulta al cambiar el selector de periodo temporal", async () => {
      renderBizTokens();

      await waitFor(() => {
        expect(screen.getByTestId("select-periodo")).toBeDefined();
      });

      fireEvent.change(screen.getByTestId("select-periodo"), { target: { value: "trimestre" } });

      await waitFor(() => {
        expect(screen.getByTestId("select-periodo")).toHaveProperty("value", "trimestre");
      });
    });

    it("filtra organizaciones mediante el input de búsqueda con debounce", async () => {
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

    it("soporta agrupación analítica por tier de modelo", async () => {
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

    it("soporta agrupación analítica por serie diaria", async () => {
      renderBizTokens();

      await waitFor(() => {
        expect(screen.getByTestId("select-agrupacion")).toBeDefined();
      });

      fireEvent.change(screen.getByTestId("select-agrupacion"), { target: { value: "dia" } });

      await waitFor(() => {
        expect(screen.getByTestId("fila-dia-2026-11-10")).toBeDefined();
      });
    });

    it("muestra alerta visual crítica cuando existe descuadre con facturación", async () => {
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
                cuadra_con_facturacion: false,
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

    it("permite ordenar por allowlist y cambiar paginación", async () => {
      renderBizTokens();

      await waitFor(() => {
        expect(screen.getByTestId("select-ordenacion")).toBeDefined();
      });

      // Cambio de ordenación
      fireEvent.change(screen.getByTestId("select-ordenacion"), {
        target: { value: "tokens_total_desc" },
      });
      expect(screen.getByTestId("select-ordenacion")).toHaveProperty("value", "tokens_total_desc");

      // Cambio de tamaño de página una vez cargados los datos
      await waitFor(() => {
        expect(screen.getByTestId("select-page-size")).toBeDefined();
      });
      fireEvent.change(screen.getByTestId("select-page-size"), {
        target: { value: "50" },
      });
      await waitFor(() => {
        expect(screen.getByTestId("select-page-size")).toHaveProperty("value", "50");
      });

      // Botón de refresco manual
      const btnRefetch = screen.getByTestId("btn-refetch-tokens");
      expect(btnRefetch).toBeDefined();
      fireEvent.click(btnRefetch);
    });

    it("enmascara por defecto la razón social y permite solicitar acceso mediante modal E6", async () => {
      setMockConcesionActiva(false);
      renderBizTokens();

      await waitFor(() => {
        expect(screen.getByTestId("fila-cliente-org_acme")).toBeDefined();
      });

      const filaAcme = screen.getByTestId("fila-cliente-org_acme");
      expect(filaAcme.textContent).toContain("A•••• S.L.");
      expect(filaAcme.textContent).not.toContain("Acme Logística S.L.");
      expect(filaAcme.textContent).toContain("ENMASCARADO");

      // Abrir modal de concesión
      fireEvent.click(screen.getByTestId("btn-concesion-org_acme"));

      await waitFor(() => {
        expect(screen.getByText("Solicitar Revelación de Datos de Cliente (E6)")).toBeDefined();
      });

      expect(screen.getByTestId("input-concesion-tenant")).toBeDefined();
      expect(screen.getByTestId("input-concesion-motivo")).toBeDefined();
      expect(screen.getByTestId("btn-confirmar-concesion")).toBeDefined();

      // Cerrar modal
      fireEvent.click(screen.getByRole("button", { name: "Cancelar" }));
    });

    it("revela la razón social en claro cuando existe concesión activa", async () => {
      setMockConcesionActiva(true);
      renderBizTokens();

      await waitFor(() => {
        expect(screen.getByTestId("fila-cliente-org_acme")).toBeDefined();
      });

      const filaAcme = screen.getByTestId("fila-cliente-org_acme");
      expect(filaAcme.textContent).toContain("Acme Logística S.L.");
      expect(filaAcme.textContent).toContain("EN CLARO");
    });
  });
});
