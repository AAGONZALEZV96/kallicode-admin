import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { OpsAgents } from "../OpsAgents";
import { OpsModels } from "../OpsModels";
import { OpsSLA } from "../OpsSLA";

describe("Vistas Operativas con LiveRefresh", () => {
  it("OpsAgents renderiza correctamente con indicador EN VIVO", () => {
    render(<OpsAgents />);
    expect(screen.getByText("Estado de Agentes y Colas de Producción")).toBeDefined();
    expect(screen.getByTestId("live-badge-activo")).toBeDefined();
    expect(screen.getByText("EN VIVO")).toBeDefined();
    expect(screen.getByText("triage")).toBeDefined();
  });

  it("OpsAgents muestra banner de advertencia cuando no hay telemetría", () => {
    render(
      <OpsAgents
        datosIniciales={{
          telemetria: { disponible: false, antiguedad_s: 0 },
          lineas: { activas: 0, mantenimiento: 0, libres: 0 },
          etapas: [],
          colas: [],
        }}
      />
    );
    expect(screen.getByTestId("banner-sin-telemetria")).toBeDefined();
    expect(screen.getByText(/Sin telemetría disponible/)).toBeDefined();
  });

  it("OpsModels renderiza telemetría de modelos LLM y servicios core", () => {
    render(<OpsModels />);
    expect(screen.getByText("Métricas de Modelos LLM y Servicios Core")).toBeDefined();
    expect(screen.getByText("gemini-2.5-flash")).toBeDefined();
    expect(screen.getByText("FLASH")).toBeDefined();
    expect(screen.getByText("PRO")).toBeDefined();
    expect(screen.getByText("FABLE")).toBeDefined();
  });

  it("OpsSLA renderiza cumplimiento y casos en riesgo", () => {
    render(<OpsSLA />);
    expect(screen.getByText("Cumplimiento de SLA e Incidentes de Servicio")).toBeDefined();
    expect(screen.getByText("Cumplimiento Global")).toBeDefined();
    expect(screen.getByText("job_991823")).toBeDefined();
  });
});
