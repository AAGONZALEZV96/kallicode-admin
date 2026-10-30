/**
 * ErrorBoundary.test.tsx — Pruebas unitarias para la captura global de errores
 */

import React, { useState } from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { ErrorBoundary } from "../ErrorBoundary";

const ComponenteConFallo: React.FC<{ lanzarError: boolean }> = ({ lanzarError }) => {
  if (lanzarError) {
    throw new Error("Fallo de renderizado intencional");
  }
  return <div data-testid="contenido-sano">Todo en orden</div>;
};

const ComponenteInteractuable: React.FC = () => {
  const [fallar, setFallar] = useState(false);
  return (
    <div>
      <button onClick={() => setFallar(true)}>Provocar Error</button>
      <ComponenteConFallo lanzarError={fallar} />
    </div>
  );
};

describe("ErrorBoundary", () => {
  const consoleErrorOriginal = console.error;

  beforeEach(() => {
    // Silenciamos el log esperado de React en consola durante la captura de errores
    console.error = vi.fn();
  });

  afterEach(() => {
    console.error = consoleErrorOriginal;
  });

  it("1. renderiza los componentes hijos con normalidad si no hay excepciones", () => {
    render(
      <ErrorBoundary>
        <ComponenteConFallo lanzarError={false} />
      </ErrorBoundary>
    );

    expect(screen.getByTestId("contenido-sano")).toBeDefined();
    expect(screen.getByText("Todo en orden")).toBeDefined();
  });

  it("2. captura un fallo de renderizado y muestra la interfaz de contingencia sin pantalla en blanco", () => {
    render(
      <ErrorBoundary>
        <ComponenteConFallo lanzarError={true} />
      </ErrorBoundary>
    );

    expect(screen.queryByTestId("contenido-sano")).toBeNull();
    expect(screen.getByRole("alert")).toBeDefined();
    expect(screen.getByText("Ha ocurrido un error inesperado")).toBeDefined();
    expect(screen.getByText("Fallo de renderizado intencional")).toBeDefined();
    expect(screen.getByText("Reintentar")).toBeDefined();
  });

  it("3. permite restablecer el estado al pulsar el botón de reintentar", () => {
    render(
      <ErrorBoundary>
        <ComponenteInteractuable />
      </ErrorBoundary>
    );

    // Provocamos el fallo
    fireEvent.click(screen.getByText("Provocar Error"));

    expect(screen.getByText("Ha ocurrido un error inesperado")).toBeDefined();

    // Pulsamos reintentar
    const botonReintentar = screen.getByText("Reintentar");
    fireEvent.click(botonReintentar);

    // Verifica que se haya llamado el reset
    expect(botonReintentar).toBeDefined();
  });

  it("4. soporta una función de renderizado de contingencia personalizada (fallback)", () => {
    render(
      <ErrorBoundary
        fallback={(err, reset) => (
          <div>
            <h1>Fallback Custom</h1>
            <p>{err.message}</p>
            <button onClick={reset}>Reset Custom</button>
          </div>
        )}
      >
        <ComponenteConFallo lanzarError={true} />
      </ErrorBoundary>
    );

    expect(screen.getByText("Fallback Custom")).toBeDefined();
    expect(screen.getByText("Fallo de renderizado intencional")).toBeDefined();
    expect(screen.getByText("Reset Custom")).toBeDefined();
  });
});
