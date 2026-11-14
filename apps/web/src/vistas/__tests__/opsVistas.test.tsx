import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, act } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { OpsAgents } from "../OpsAgents";
import { OpsModels } from "../OpsModels";
import { OpsSLA } from "../OpsSLA";

function envolverQuery(ui: React.ReactElement) {
  const client = new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
      },
    },
  });
  return <QueryClientProvider client={client}>{ui}</QueryClientProvider>;
}

describe("Vistas Operativas con LiveRefresh", () => {
  beforeEach(() => {
    Object.defineProperty(document, "hidden", {
      configurable: true,
      get: () => false,
    });
  });

  afterEach(() => {
    vi.clearAllTimers();
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("OpsAgents renderiza correctamente con indicador EN VIVO y opciones oficiales", () => {
    render(<OpsAgents />);
    expect(screen.getByText("Estado de Agentes y Colas de Producción")).toBeDefined();
    expect(screen.getByTestId("live-badge-activo")).toBeDefined();
    expect(screen.getByText("EN VIVO")).toBeDefined();
    expect(screen.getByText("triage")).toBeDefined();

    const selector = screen.getByTestId("live-select-intervalo") as HTMLSelectElement;
    const etiquetas = Array.from(selector.options).map((o) => o.textContent);
    expect(etiquetas).toEqual([
      "Cada 15 segundos (Recomendado)",
      "Cada 30 segundos",
      "Cada 60 segundos",
      "Pausado / Manual",
    ]);
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

  it("ninguna pantalla de operaciones consulta en segundo plano cuando document.hidden es true", async () => {
    vi.useFakeTimers();

    const obtenerAgentes = vi.fn().mockResolvedValue({
      ventana: "1h",
      telemetria: { disponible: true, antiguedad_s: 5, ultimo_latido: "2026-11-13T20:00:00Z" },
      lineas: { activas: 3, mantenimiento: 0, libres: 1 },
      etapas: [],
      alertas: [],
    });
    const obtenerColas = vi.fn().mockResolvedValue({
      colas: [],
    });
    const obtenerModelos = vi.fn().mockResolvedValue({
      ventana: "24h",
      modelos: [],
      proveedores: [],
      escalados: [],
    });
    const obtenerSla = vi.fn().mockResolvedValue({
      ciclo: "2026-11",
      muestra_suficiente: true,
      objetivos: [],
      resumen_planes: [],
      casos: [],
      total: 0,
      page: 1,
      page_size: 10,
      pages: 1,
    });

    render(
      envolverQuery(
        <>
          <OpsAgents obtenerAgentes={obtenerAgentes} obtenerColas={obtenerColas} />
          <OpsModels obtenerDatos={obtenerModelos} />
          <OpsSLA obtenerDatos={obtenerSla} />
        </>
      )
    );

    // Permitir montaje inicial y queries iniciales de TanStack Query (1 llamada por fuente)
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });

    const llamadasInicialesAgentes = obtenerAgentes.mock.calls.length;
    const llamadasInicialesColas = obtenerColas.mock.calls.length;
    const llamadasInicialesModelos = obtenerModelos.mock.calls.length;
    const llamadasInicialesSla = obtenerSla.mock.calls.length;

    expect(llamadasInicialesAgentes).toBeGreaterThanOrEqual(1);
    expect(llamadasInicialesModelos).toBeGreaterThanOrEqual(1);
    expect(llamadasInicialesSla).toBeGreaterThanOrEqual(1);

    // Simular cambio a segundo plano (pestaña oculta)
    await act(async () => {
      Object.defineProperty(document, "hidden", { configurable: true, get: () => true });
      document.dispatchEvent(new Event("visibilitychange"));
    });

    // Avanzar 90 segundos en segundo plano -> cero nuevas consultas en las 3 vistas
    await act(async () => {
      vi.advanceTimersByTime(90_000);
    });

    expect(obtenerAgentes).toHaveBeenCalledTimes(llamadasInicialesAgentes);
    expect(obtenerColas).toHaveBeenCalledTimes(llamadasInicialesColas);
    expect(obtenerModelos).toHaveBeenCalledTimes(llamadasInicialesModelos);
    expect(obtenerSla).toHaveBeenCalledTimes(llamadasInicialesSla);

    // Al volver a la pestaña activa, las vistas retoman y refrescan inmediatamente
    await act(async () => {
      Object.defineProperty(document, "hidden", { configurable: true, get: () => false });
      document.dispatchEvent(new Event("visibilitychange"));
      await Promise.resolve();
    });

    expect(obtenerAgentes.mock.calls.length).toBeGreaterThan(llamadasInicialesAgentes);
    expect(obtenerColas.mock.calls.length).toBeGreaterThan(llamadasInicialesColas);
    expect(obtenerModelos.mock.calls.length).toBeGreaterThan(llamadasInicialesModelos);
    expect(obtenerSla.mock.calls.length).toBeGreaterThan(llamadasInicialesSla);
  });
});
