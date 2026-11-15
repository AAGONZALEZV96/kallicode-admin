/**
 * OpsSLA.test.tsx — Pruebas de componente para la pantalla Ops SLA y DetalleRelojSLA
 *
 * Valida:
 * 1. Renderizado de KPIs ejecutivos, desglose por plan (Starter 72h, Growth 24h, Enterprise 8h) y p95.
 * 2. Regla estadística de muestra mínima ("N/A" cuando casos evaluados < 5).
 * 3. Indicador de frescura relativa y alerta > 6 horas sin exponer texto técnico interno.
 * 4. Filtros dinámicos (ciclo AAAA-MM, plan, solo riesgo/incumplidos) y paginación.
 * 5. Apertura del modal DetalleRelojSLA con ecuación de consistencia, tramos computables/pausas y reglas.
 * 6. Estados de ContenedorEstado (skeleton carga, error 503 con X-Trace-Id + reintento, estado vacío).
 * 7. Enmascaramiento por defecto, revelación con concesión activa y guarda RBAC por rol.
 */

import { describe, it, expect } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { http, HttpResponse } from "msw";
import { server } from "../../pruebas/server";
import {
  setMockConcesionActiva,
  setMockFrescura,
  setMockRolStaff,
} from "../../pruebas/msw_handlers";
import { AuthProvider, UsuarioStaff } from "../../estado/auth";
import { OpsSLA } from "../OpsSLA";

function renderOpsSLA(opciones?: { usuario?: UsuarioStaff }) {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
      },
    },
  });

  const usuarioOps: UsuarioStaff = opciones?.usuario ?? {
    staff_id: "st_ops_001",
    email: "ops@kallicode.com",
    nombre: "Staff Operaciones",
    role: "staff_operaciones",
    mfa_validado: true,
  };

  setMockRolStaff(usuarioOps.role);

  return render(
    <AuthProvider
      sesionInicial={{
        usuario: usuarioOps,
        token: `mock_jwt_${usuarioOps.role}`,
      }}
    >
      <QueryClientProvider client={queryClient}>
        <OpsSLA />
      </QueryClientProvider>
    </AuthProvider>
  );
}

describe("OpsSLA — Cumplimiento de Niveles de Servicio y Reloj de Incidencias", () => {
  it("1. renderiza KPIs ejecutivos, desglose por plan (Starter, Growth, Enterprise), p95 y tabla enmascarada", async () => {
    setMockConcesionActiva(false);
    setMockFrescura(new Date(Date.now() - 15 * 60 * 1000).toISOString());

    renderOpsSLA();

    // Skeleton de carga inicial accesible
    const loader = screen.getByTestId("ops-sla-loading");
    expect(loader.getAttribute("role")).toBe("status");
    expect(loader.getAttribute("aria-busy")).toBe("true");

    await waitFor(() => {
      expect(screen.getByTestId("kpi-cumplimiento-global")).toBeDefined();
    });

    // KPIs principales (5 dentro / 7 evaluados = 71.4%)
    const kpiGlobal = screen.getByTestId("kpi-cumplimiento-global");
    expect(kpiGlobal.textContent).toContain("71.4%");
    expect(screen.getByTestId("kpi-casos-en-riesgo").textContent).toContain("2");
    expect(screen.getByTestId("kpi-casos-incumplidos").textContent).toContain("2");
    expect(screen.getByTestId("kpi-total-evaluados").textContent).toContain("7");

    // Desglose por plan comercial con objetivos 72h, 24h y 8h + p95 + casos
    const planStarter = screen.getByTestId("plan-sla-starter");
    const planGrowth = screen.getByTestId("plan-sla-growth");
    const planEnterprise = screen.getByTestId("plan-sla-enterprise");
    expect(planStarter.textContent).toContain("Starter (72 horas)");
    expect(planStarter.textContent).toContain("p95:");
    expect(planGrowth.textContent).toContain("Growth (24 horas)");
    expect(planEnterprise.textContent).toContain("Enterprise (8 horas)");

    // Frescura relativa visible sin textos técnicos prohibidos
    const frescura = screen.getByTestId("indicador-frescura-sla");
    expect(frescura.textContent).toContain("Actualizado hace 15 min");

    // Enmascaramiento por defecto en tabla
    expect(screen.getAllByText("G••••• S.A.").length).toBeGreaterThan(0);
    expect(screen.getAllByText("ENMASCARADO").length).toBeGreaterThan(0);

    // Prohibido exponer símbolos de especificación o nombres crudos de tablas SQL
    const textoCompleto = document.body.textContent || "";
    expect(textoCompleto).not.toContain("§18");
    expect(textoCompleto).not.toContain("admin.sla_clock_segments");
    expect(textoCompleto).not.toContain("admin.sla_cases");
  });

  it("2. muestra N/A en Cumplimiento Global cuando los casos evaluados son menores a 5", async () => {
    server.use(
      http.get("*/admin/v1/ops/sla", () =>
        HttpResponse.json({
          ciclo: "2026-11",
          frescura: new Date(Date.now() - 10 * 60 * 1000).toISOString(),
          sin_definicion: [],
          resumen: {
            casos_totales: 3,
            casos_evaluados: 3,
            casos_dentro: 2,
            casos_incumplidos: 1,
            casos_en_riesgo: 0,
            casos_en_curso: 0,
            cumplimiento_pct: null,
            incumplidos: 1,
            en_riesgo: 0,
          },
          por_plan: {
            starter: { plan: "starter", objetivo_h: 72, casos: 1, cumplimiento_pct: null, p95_h: 48.0 },
            growth: { plan: "growth", objetivo_h: 24, casos: 1, cumplimiento_pct: null, p95_h: 26.4 },
            enterprise: { plan: "enterprise", objetivo_h: 8, casos: 1, cumplimiento_pct: null, p95_h: 5.2 },
          },
          casos: [
            {
              job_id: "job_sla_ent_01",
              ticket_numero: "KC-401",
              tenant_id: "org_••••",
              razon_social: "G••••• S.A.",
              plan: "enterprise",
              objetivo_h: 8,
              transcurrido_h: 5.2,
              bruto_h: 9.2,
              pausa_total_h: 4.0,
              resultado: "dentro",
              enmascarado: true,
            },
          ],
          total: 1,
          page: 1,
          page_size: 10,
          pages: 1,
        })
      )
    );

    renderOpsSLA();

    await waitFor(() => {
      expect(screen.getByTestId("kpi-cumplimiento-global")).toBeDefined();
    });

    const kpiGlobal = screen.getByTestId("kpi-cumplimiento-global");
    expect(kpiGlobal.textContent).toContain("N/A");
    expect(kpiGlobal.textContent).toContain("mínimo 5 casos evaluados");
  });

  it("3. alerta visualmente cuando la frescura supera las 6 horas sin exponer textos técnicos de backend", async () => {
    setMockFrescura(new Date(Date.now() - 8 * 60 * 60 * 1000).toISOString());

    renderOpsSLA();

    await waitFor(() => {
      expect(screen.getByTestId("kpi-cumplimiento-global")).toBeDefined();
      expect(screen.getByTestId("indicador-frescura-sla").textContent).toContain(
        "Datos desactualizados (> 6 h)"
      );
    });

    const frescura = screen.getByTestId("indicador-frescura-sla");
    expect(frescura.textContent).toContain("Datos desactualizados (> 6 h)");
    expect(frescura.textContent).toContain("Actualizado hace 8 h");
    expect(frescura.textContent).not.toContain("admin.ops");
  });

  it("4. abre el modal DetalleRelojSLA al hacer clic en un job_id y verifica deducción de pausas justificadas", async () => {
    setMockConcesionActiva(false);

    renderOpsSLA();

    await waitFor(() => {
      expect(screen.getByText("job_sla_gro_01")).toBeDefined();
    });

    fireEvent.click(screen.getByText("job_sla_gro_01"));

    await waitFor(() => {
      expect(screen.getByTestId("ecuacion-reloj-sla")).toBeDefined();
    });

    // Ecuación: Tiempo Bruto (31.50 h) = Tiempo Computado (19.50 h) + Pausa Justificada (12.00 h)
    const ecuacion = screen.getByTestId("ecuacion-reloj-sla");
    expect(ecuacion.textContent).toContain("31.50 h");
    expect(ecuacion.textContent).toContain("19.50 h");
    expect(ecuacion.textContent).toContain("12.00 h");

    // Línea de tiempo con tramos computables y pausas justificadas tipificadas
    const timeline = screen.getByTestId("timeline-tramos-sla");
    expect(timeline.textContent).toContain("Computa al SLA");
    expect(timeline.textContent).toContain("Pausa justificada");
    expect(timeline.textContent).toContain("Espera de firma del cliente");
    expect(timeline.textContent).toContain("Indisponibilidad de proveedor LLM");

    // Reglas ADR-003 explicativas sin exposición de tablas SQL
    const reglas = screen.getByTestId("reglas-adr003-sla");
    expect(reglas.textContent).toContain("Criterios y deducciones aplicadas en el reloj");
    expect(reglas.textContent).not.toContain("admin.");
  });

  it("5. filtra por plan y por solo casos en riesgo o incumplidos y permite paginar", async () => {
    renderOpsSLA();

    await waitFor(() => {
      expect(screen.getByTestId("fila-sla-job_sla_ent_01")).toBeDefined();
    });

    // Activar casilla Solo casos en riesgo o incumplidos
    const checkSoloRiesgo = screen.getByLabelText("Solo casos en riesgo o incumplidos");
    fireEvent.click(checkSoloRiesgo);

    await waitFor(() => {
      expect(screen.queryByTestId("fila-sla-job_sla_ent_01")).toBeNull();
      expect(screen.getByTestId("fila-sla-job_sla_ent_02")).toBeDefined();
      expect(screen.getByTestId("fila-sla-job_sla_gro_02")).toBeDefined();
    });

    // Filtrar por plan enterprise -> queda solo job_sla_ent_02
    const selectPlan = screen.getByLabelText("Plan comercial");
    fireEvent.change(selectPlan, { target: { value: "enterprise" } });

    await waitFor(() => {
      expect(screen.getByTestId("fila-sla-job_sla_ent_02")).toBeDefined();
      expect(screen.queryByTestId("fila-sla-job_sla_gro_02")).toBeNull();
    });

    // Restablecer filtros y probar paginación cambiando a 5 por página
    fireEvent.click(screen.getByText("Restablecer filtros"));
    await waitFor(() => {
      expect(screen.getByTestId("fila-sla-job_sla_ent_01")).toBeDefined();
    });

    const selectTamano = screen.getByLabelText("Registros por página");
    fireEvent.change(selectTamano, { target: { value: "5" } });

    await waitFor(() => {
      expect(screen.getByTestId("paginacion-ops-sla").textContent).toContain("Total: 10 casos");
      expect(screen.getByTestId("paginacion-ops-sla").textContent).toContain("Mostrando página 1 de 2");
    });

    fireEvent.click(screen.getByText("Siguiente"));

    await waitFor(() => {
      expect(screen.getByTestId("paginacion-ops-sla").textContent).toContain("Mostrando página 2 de 2");
      expect(screen.getByTestId("fila-sla-job_sla_sta_01")).toBeDefined();
    });
  });

  it("6. maneja error HTTP 503 con X-Trace-Id, permite reintentar y renderiza estado vacío", async () => {
    let falloInicial = true;
    server.use(
      http.get("*/admin/v1/ops/sla", () => {
        if (falloInicial) {
          falloInicial = false;
          return HttpResponse.json(
            {
              error: {
                codigo: "AGREGADO_NO_DISPONIBLE",
                mensaje: "Agregado SLA temporalmente no disponible.",
                trace_id: "trc_sla_error_503",
              },
            },
            { status: 503, headers: { "x-trace-id": "trc_sla_error_503" } }
          );
        }
        return HttpResponse.json({
          ciclo: "2026-11",
          frescura: new Date().toISOString(),
          sin_definicion: [],
          resumen: {
            casos_totales: 0,
            casos_evaluados: 0,
            casos_dentro: 0,
            casos_incumplidos: 0,
            casos_en_riesgo: 0,
            casos_en_curso: 0,
            cumplimiento_pct: null,
            incumplidos: 0,
            en_riesgo: 0,
          },
          por_plan: {},
          casos_en_riesgo: [],
          casos: [],
          items: [],
          total: 0,
          page: 1,
          page_size: 10,
          pages: 0,
        });
      })
    );

    renderOpsSLA();

    await waitFor(() => {
      expect(screen.getByTestId("ops-sla-error")).toBeDefined();
    });

    expect(screen.getByTestId("ops-sla-trace-id").textContent).toContain("trc_sla_error_503");

    // Al reintentar, el endpoint responde 200 sin casos -> EstadoVacío
    fireEvent.click(screen.getByText("Reintentar"));

    await waitFor(() => {
      expect(screen.getByText("Sin casos de SLA para los filtros seleccionados")).toBeDefined();
    });
  });

  it("7. revela clientes con concesión activa y bloquea al rol staff_soporte", async () => {
    // Caso A: Con concesión activa se revelan nombres reales
    setMockConcesionActiva(true);
    const { unmount } = renderOpsSLA();

    await waitFor(() => {
      expect(screen.getAllByText("Globex Industrial S.A.").length).toBeGreaterThan(0);
      expect(screen.getAllByText("EN CLARO").length).toBeGreaterThan(0);
    });
    unmount();

    // Caso B: staff_soporte queda bloqueado
    renderOpsSLA({
      usuario: {
        staff_id: "st_sop_001",
        email: "soporte@kallicode.com",
        nombre: "Staff Soporte",
        role: "staff_soporte",
        mfa_validado: true,
      },
    });

    expect(screen.getByTestId("ops-sla-rbac-bloqueado")).toBeDefined();
    expect(screen.getByText("403 ROL_STAFF_INSUFICIENTE")).toBeDefined();
  });
});
