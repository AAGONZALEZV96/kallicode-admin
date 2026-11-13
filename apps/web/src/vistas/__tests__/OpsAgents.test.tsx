/**
 * OpsAgents.test.tsx — Pruebas de componente para la pantalla OpsAgents
 *
 * Valida:
 * 1. Skeleton de carga accesible (ContenedorEstado), KPIs (líneas, agentes, colas),
 *    6 etapas canónicas (triage, design, build, qa, security, deploy) y alertas por etapa.
 * 2. Selector de ventana temporal (5m, 1h, 24h) sincronizado con TanStack Query.
 * 3. Tabla densa de colas ordenada (critico -> atencion -> normal y por profundidad),
 *    badges semánticos y filtro toggle incluir_dlq.
 * 4. Indicador de frescura de telemetría y alerta visual cuando supera 5 minutos.
 * 5. Diferenciación estricta entre sin telemetría (guiones / Sin telemetría sin ceros)
 *    y sin carga de trabajo (disponible=true con ocupados=0).
 * 6. Manejo de error 503 TELEMETRIA_NO_DISPONIBLE con X-Trace-Id y botón de reintento,
 *    además de estado vacío en tabla de colas.
 * 7. Control de acceso RBAC por rol de personal (staff_operaciones y staff_admin).
 */

import { describe, it, expect } from "vitest";
import { render, screen, waitFor, fireEvent, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { http, HttpResponse } from "msw";
import { server } from "../../pruebas/server";
import { AuthProvider, UsuarioStaff } from "../../estado/auth";
import { OpsAgents } from "../OpsAgents";

function renderOpsAgents(opciones?: { usuario?: UsuarioStaff }) {
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

  return render(
    <AuthProvider
      sesionInicial={{
        usuario: usuarioOps,
        token: `mock_jwt_${usuarioOps.role}`,
      }}
    >
      <QueryClientProvider client={queryClient}>
        <OpsAgents />
      </QueryClientProvider>
    </AuthProvider>
  );
}

describe("OpsAgents — Estado de Agentes de Producción, Colas y Rendimiento", () => {
  it("1. renderiza skeleton inicial, KPIs agregados, 6 etapas canónicas con alertas y tabla de colas ordenada", async () => {
    renderOpsAgents();

    const loader = screen.getByTestId("ops-agents-loading");
    expect(loader.getAttribute("role")).toBe("status");
    expect(loader.getAttribute("aria-busy")).toBe("true");

    await waitFor(() => {
      expect(screen.getByTestId("kpi-lineas")).toBeDefined();
    });

    // Indicador de telemetría disponible y frescura
    const telemetria = screen.getByTestId("indicador-telemetria");
    expect(telemetria.textContent).toContain("Telemetría disponible");
    expect(telemetria.textContent).toContain("Actualizado hace 4 s");

    // Tarjetas de resumen
    const kpiLineas = screen.getByTestId("kpi-lineas");
    expect(kpiLineas.textContent).toContain("12 activas");
    expect(kpiLineas.textContent).toContain("Mantenimiento: 1");
    expect(kpiLineas.textContent).toContain("Libres: 5");

    const kpiAgentes = screen.getByTestId("kpi-agentes");
    expect(kpiAgentes.textContent).toContain("18 / 25 ocupados");
    expect(kpiAgentes.textContent).toContain("Caídos: 1");

    const kpiColas = screen.getByTestId("kpi-colas");
    expect(kpiColas.textContent).toContain("104 pendientes");
    expect(kpiColas.textContent).toContain("Fallidos (DLQ): 2");

    // 6 etapas canónicas
    for (const etapa of ["triage", "design", "build", "qa", "security", "deploy"]) {
      expect(screen.getByTestId(`etapa-${etapa}`)).toBeDefined();
    }

    const etapaBuild = screen.getByTestId("etapa-build");
    expect(etapaBuild.textContent).toContain("Alerta");
    expect(etapaBuild.textContent).toContain("54.2 s");
    expect(screen.getByTestId("lista-alertas-etapas").textContent).toContain(
      "1 agente sin latido en etapa build"
    );

    // Ordenación de colas: CRITICO (kc:dlq) -> ATENCION (cola_generacion) -> NORMAL (kc:inbox, cola_ingesta)
    const tabla = screen.getByTestId("tabla-colas-ops");
    const filas = within(tabla).getAllByRole("row").slice(1);
    expect(filas[0].textContent).toContain("kc:dlq");
    expect(filas[0].textContent).toContain("CRITICO");
    expect(filas[1].textContent).toContain("cola_generacion");
    expect(filas[1].textContent).toContain("ATENCION");
    expect(filas[2].textContent).toContain("kc:inbox");
    expect(filas[2].textContent).toContain("NORMAL");
    expect(filas[3].textContent).toContain("cola_ingesta");
  });

  it("2. sincroniza selector de ventana temporal (5m, 1h, 24h) con el endpoint /ops/agents", async () => {
    const ventanasConsultadas: string[] = [];
    server.use(
      http.get("*/admin/v1/ops/agents", ({ request }) => {
        const url = new URL(request.url);
        const ventana = url.searchParams.get("ventana") || "1h";
        ventanasConsultadas.push(ventana);
        const jobsTriage = ventana === "5m" ? 8 : ventana === "24h" ? 336 : 42;
        return HttpResponse.json({
          ventana,
          telemetria: { disponible: true, antiguedad_s: 3 },
          agentes_total: 25,
          agentes_ocupados: 18,
          agentes_caidos: 0,
          lineas: { activas: 12, mantenimiento: 0, libres: 5 },
          etapas: [
            { etapa: "triage", agentes_total: 4, agentes_ocupados: 2, agentes_caidos: 0, jobs_completados: jobsTriage, duracion_p95_s: 10.5 },
            { etapa: "design", agentes_total: 4, agentes_ocupados: 3, agentes_caidos: 0, jobs_completados: 28, duracion_p95_s: 20.0 },
            { etapa: "build", agentes_total: 8, agentes_ocupados: 6, agentes_caidos: 0, jobs_completados: 36, duracion_p95_s: 50.0 },
            { etapa: "qa", agentes_total: 4, agentes_ocupados: 3, agentes_caidos: 0, jobs_completados: 19, duracion_p95_s: 40.0 },
            { etapa: "security", agentes_total: 3, agentes_ocupados: 2, agentes_caidos: 0, jobs_completados: 11, duracion_p95_s: 30.0 },
            { etapa: "deploy", agentes_total: 2, agentes_ocupados: 2, agentes_caidos: 0, jobs_completados: 6, duracion_p95_s: 45.0 },
          ],
          alertas: [],
        });
      })
    );

    renderOpsAgents();

    await waitFor(() => {
      expect(screen.getByTestId("etapa-triage").textContent).toContain("42");
    });

    expect(screen.getByTestId("btn-ventana-1h").getAttribute("aria-pressed")).toBe("true");

    fireEvent.click(screen.getByTestId("btn-ventana-5m"));
    await waitFor(() => {
      expect(screen.getByTestId("etapa-triage").textContent).toContain("8");
    });

    fireEvent.click(screen.getByTestId("btn-ventana-24h"));
    await waitFor(() => {
      expect(screen.getByTestId("etapa-triage").textContent).toContain("336");
    });

    expect(ventanasConsultadas).toContain("1h");
    expect(ventanasConsultadas).toContain("5m");
    expect(ventanasConsultadas).toContain("24h");
  });

  it("3. permite incluir o excluir Dead Letter Queues con el toggle incluir_dlq", async () => {
    renderOpsAgents();

    await waitFor(() => {
      expect(screen.getByTestId("fila-cola-kc:dlq")).toBeDefined();
    });

    const toggle = screen.getByTestId("toggle-incluir-dlq") as HTMLInputElement;
    expect(toggle.checked).toBe(true);

    fireEvent.click(toggle);

    await waitFor(() => {
      expect(screen.queryByTestId("fila-cola-kc:dlq")).toBeNull();
      const kpiColas = screen.getByTestId("kpi-colas");
      expect(kpiColas.textContent).toContain("102 pendientes");
      expect(kpiColas.textContent).toContain("Fallidos (DLQ): 0");
    });
  });

  it("4. alerta visualmente cuando la antigüedad de telemetría supera los 5 minutos", async () => {
    server.use(
      http.get("*/admin/v1/ops/agents", () =>
        HttpResponse.json({
          ventana: "1h",
          telemetria: {
            disponible: true,
            antiguedad_s: 360,
            desde: new Date(Date.now() - 360 * 1000).toISOString(),
          },
          agentes_total: 25,
          agentes_ocupados: 10,
          agentes_caidos: 0,
          lineas: { activas: 10, mantenimiento: 1, libres: 7 },
          etapas: [
            { etapa: "triage", agentes_total: 4, agentes_ocupados: 1, agentes_caidos: 0, jobs_completados: 10, duracion_p95_s: 12.0 },
          ],
          alertas: [],
        })
      )
    );

    renderOpsAgents();

    await waitFor(() => {
      expect(screen.getByTestId("banner-telemetria-desactualizada")).toBeDefined();
    });

    expect(screen.getByTestId("indicador-telemetria").textContent).toContain(
      "Telemetría desactualizada"
    );
    expect(screen.getByTestId("banner-telemetria-desactualizada").getAttribute("role")).toBe(
      "alert"
    );
  });

  it("5. muestra guiones y Sin telemetría cuando disponible=false, diferenciándolo de sin carga de trabajo", async () => {
    server.use(
      http.get("*/admin/v1/ops/agents", () =>
        HttpResponse.json({
          ventana: "1h",
          telemetria: { disponible: false, antiguedad_s: null, desde: null },
          agentes_total: null,
          agentes_ocupados: null,
          agentes_caidos: null,
          lineas: null,
          etapas: null,
          alertas: [],
        })
      )
    );

    renderOpsAgents();

    await waitFor(() => {
      expect(screen.getByTestId("banner-sin-telemetria")).toBeDefined();
    });

    expect(screen.getByTestId("kpi-lineas").textContent).toContain("— activas");
    expect(screen.getByTestId("kpi-agentes").textContent).toContain("— / — ocupados");
    expect(screen.getByTestId("etapa-build").textContent).toContain("Sin telemetría");
    expect(screen.getByTestId("etapa-build").textContent).toContain("—");
  });

  it("6. diferencia correctamente telemetría disponible sin carga activa (agentes_ocupados=0)", async () => {
    server.use(
      http.get("*/admin/v1/ops/agents", () =>
        HttpResponse.json({
          ventana: "1h",
          telemetria: { disponible: true, antiguedad_s: 5, desde: new Date().toISOString() },
          agentes_total: 25,
          agentes_ocupados: 0,
          agentes_caidos: 0,
          lineas: { activas: 12, mantenimiento: 0, libres: 5 },
          etapas: [
            { etapa: "triage", agentes_total: 4, agentes_ocupados: 0, agentes_caidos: 0, jobs_completados: 0, duracion_p95_s: null },
            { etapa: "design", agentes_total: 4, agentes_ocupados: 0, agentes_caidos: 0, jobs_completados: 0, duracion_p95_s: null },
            { etapa: "build", agentes_total: 8, agentes_ocupados: 0, agentes_caidos: 0, jobs_completados: 0, duracion_p95_s: null },
            { etapa: "qa", agentes_total: 4, agentes_ocupados: 0, agentes_caidos: 0, jobs_completados: 0, duracion_p95_s: null },
            { etapa: "security", agentes_total: 3, agentes_ocupados: 0, agentes_caidos: 0, jobs_completados: 0, duracion_p95_s: null },
            { etapa: "deploy", agentes_total: 2, agentes_ocupados: 0, agentes_caidos: 0, jobs_completados: 0, duracion_p95_s: null },
          ],
          alertas: [],
        })
      )
    );

    renderOpsAgents();

    await waitFor(() => {
      expect(screen.getByTestId("kpi-agentes").textContent).toContain("0 / 25 ocupados");
    });

    expect(screen.queryByTestId("banner-sin-telemetria")).toBeNull();
    expect(screen.getByTestId("etapa-triage").textContent).toContain("Operativa");
    expect(screen.getByTestId("etapa-triage").textContent).toContain("—"); // p95 null cuando 0 jobs
  });

  it("7. maneja error 503 TELEMETRIA_NO_DISPONIBLE con ContenedorEstado, X-Trace-Id y recuperación al reintentar", async () => {
    let llamadas = 0;
    server.use(
      http.get("*/admin/v1/ops/agents", () => {
        llamadas += 1;
        if (llamadas === 1) {
          return HttpResponse.json(
            {
              error: {
                codigo: "TELEMETRIA_NO_DISPONIBLE",
                mensaje: "La telemetría del pipeline no está disponible (> 15 min).",
              },
            },
            { status: 503, headers: { "x-trace-id": "trc_503_agents_fail" } }
          );
        }
        return HttpResponse.json({
          ventana: "1h",
          telemetria: { disponible: true, antiguedad_s: 2 },
          agentes_total: 25,
          agentes_ocupados: 18,
          agentes_caidos: 0,
          lineas: { activas: 12, mantenimiento: 0, libres: 5 },
          etapas: [{ etapa: "triage", agentes_total: 4, agentes_ocupados: 2, agentes_caidos: 0 }],
          alertas: [],
        });
      }),
      http.get("*/admin/v1/ops/queues", () => {
        if (llamadas <= 1) {
          return HttpResponse.json(
            {
              error: {
                codigo: "TELEMETRIA_NO_DISPONIBLE",
                mensaje: "La telemetría de colas no está disponible.",
              },
            },
            { status: 503, headers: { "x-trace-id": "trc_503_agents_fail" } }
          );
        }
        return HttpResponse.json({
          resumen: { criticas: 0, atencion: 0, pendientes_total: 10, fallidos_total: 0 },
          colas: [
            {
              nombre: "kc:inbox",
              pendientes: 10,
              reclamados: 2,
              fallidos: 0,
              antiguedad_max_s: 8,
              estado: "normal",
            },
          ],
        });
      })
    );

    renderOpsAgents();

    await waitFor(() => {
      expect(screen.getByTestId("ops-agents-error")).toBeDefined();
    });

    const tarjetaError = screen.getByTestId("ops-agents-error");
    expect(tarjetaError.getAttribute("role")).toBe("alert");
    expect(screen.getByTestId("ops-agents-trace-id").textContent).toContain(
      "trc_503_agents_fail"
    );

    fireEvent.click(screen.getByRole("button", { name: /Reintentar/i }));

    await waitFor(() => {
      expect(screen.getByTestId("kpi-agentes").textContent).toContain("18 / 25 ocupados");
    });
  });

  it("8. muestra estado vacío accesible cuando no existen colas activas", async () => {
    server.use(
      http.get("*/admin/v1/ops/queues", () =>
        HttpResponse.json({
          resumen: { criticas: 0, atencion: 0, pendientes_total: 0, fallidos_total: 0 },
          colas: [],
        })
      )
    );

    renderOpsAgents();

    await waitFor(() => {
      expect(screen.getByText("Sin colas activas")).toBeDefined();
    });
  });

  it("9. bloquea el acceso a roles no autorizados (staff_soporte / staff_negocio) y permite staff_admin", async () => {
    renderOpsAgents({
      usuario: {
        staff_id: "st_soporte_001",
        email: "soporte@kallicode.com",
        nombre: "Soporte L1",
        role: "staff_soporte",
        mfa_validado: true,
      },
    });

    const bloqueo = screen.getByTestId("ops-agents-rbac-bloqueado");
    expect(bloqueo.getAttribute("role")).toBe("alert");
    expect(bloqueo.textContent).toContain("403 ROL_STAFF_INSUFICIENTE");

    // staff_admin tiene acceso completo
    renderOpsAgents({
      usuario: {
        staff_id: "st_adm_001",
        email: "admin@kallicode.com",
        nombre: "Admin Root",
        role: "staff_admin",
        mfa_validado: true,
      },
    });

    await waitFor(() => {
      expect(screen.getByTestId("kpi-lineas")).toBeDefined();
    });
  });
});
