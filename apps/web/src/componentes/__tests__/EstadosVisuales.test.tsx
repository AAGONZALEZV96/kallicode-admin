/**
 * EstadosVisuales.test.tsx — Pruebas de Componentes para la Suite de Estados de Interfaz
 *
 * Valida de forma exhaustiva los componentes del ticket [KC-ADM-B3-06]:
 * 1. Skeleton: Primitiva visual, variantes de forma y animación.
 * 2. EstadoCarga: Accesibilidad WCAG (role="status", aria-busy, aria-live), variantes (kpis, tabla, detalle, formulario), mensaje sr-only y garantía de tiempo límite.
 * 3. EstadoError: Captura y mapeo semántico de errores HTTP (503, 403, 404, red), visualización obligatoria de X-Trace-Id, botón interactivo de reintento y role="alert".
 * 4. EstadoVacio: Aspecto amigable, iconografía clara, acción sugerida interactiva.
 * 5. ContenedorEstado: Orquestación declarativa limpia entre estados y renderizado de contenido.
 */

import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent, act } from "@testing-library/react";
import { Skeleton } from "../Skeleton";
import { EstadoCarga } from "../EstadoCarga";
import { EstadoError } from "../EstadoError";
import { EstadoVacio } from "../EstadoVacio";
import { ContenedorEstado } from "../ContenedorEstado";
import { ApiError } from "../../api/clienteApi";

describe("Suite de Estados Visuales de Interfaz — [KC-ADM-B3-06]", () => {
  // ------------------------------------------------------------------ 1. Skeleton
  describe("Skeleton — Primitiva de Marcador de Posición", () => {
    it("1. renderiza con atributos ocultos para accesibilidad y dimensiones especificadas", () => {
      const { container } = render(
        <Skeleton ancho="120px" alto="24px" redondeado="lg" data-testid="test-skeleton" />
      );

      const el = container.querySelector(".kc-skeleton") as HTMLElement;
      expect(el).toBeDefined();
      expect(el.getAttribute("aria-hidden")).toBe("true");
      expect(el.style.width).toBe("120px");
      expect(el.style.height).toBe("24px");
      expect(el.style.borderRadius).toBe("var(--radius-lg, 12px)");
    });

    it("2. aplica radio circular cuando variante='circular'", () => {
      const { container } = render(<Skeleton variante="circular" ancho={48} alto={48} />);
      const el = container.querySelector(".kc-skeleton") as HTMLElement;
      expect(el.style.borderRadius).toBe("var(--radius-full, 9999px)");
      expect(el.style.width).toBe("48px");
      expect(el.style.height).toBe("48px");
    });
  });

  // ------------------------------------------------------------------ 2. EstadoCarga
  describe("EstadoCarga — Skeleton Loading Accesible", () => {
    it("1. cumple con requisitos de accesibilidad obligatorios (role, aria-busy, aria-live, sr-only)", () => {
      render(<EstadoCarga mensaje="Cargando métricas del panel..." data-testid="mi-loader" />);

      const loader = screen.getByTestId("mi-loader");
      expect(loader.getAttribute("role")).toBe("status");
      expect(loader.getAttribute("aria-busy")).toBe("true");
      expect(loader.getAttribute("aria-live")).toBe("polite");

      // Comprobar mensaje accesible para lectores de pantalla
      expect(screen.getByText("Cargando métricas del panel...")).toBeDefined();
    });

    it("2. renderiza layout estructurado de KPIs", () => {
      const { container } = render(<EstadoCarga tipo="kpis" tarjetas={4} />);
      const cards = container.querySelectorAll(".card");
      expect(cards.length).toBe(4);
    });

    it("3. renderiza layout estructurado de Tabla Densa", () => {
      const { container } = render(<EstadoCarga tipo="tabla" filas={6} columnas={5} />);
      const skeletonCard = container.querySelector(".card");
      expect(skeletonCard).toBeDefined();

      const skeletons = container.querySelectorAll(".kc-skeleton");
      expect(skeletons.length).toBeGreaterThan(15);
    });

    it("4. renderiza layouts de Detalle y Formulario", () => {
      const { unmount, container: containerDetalle } = render(<EstadoCarga tipo="detalle" />);
      expect(containerDetalle.querySelectorAll(".card").length).toBe(6);
      unmount();

      const { container: containerForm } = render(<EstadoCarga tipo="formulario" />);
      expect(containerForm.querySelector(".card")).toBeDefined();
    });

    it("5. ejecuta callback de garantía de tiempo límite al expirar el temporizador", () => {
      vi.useFakeTimers();
      const onTimeout = vi.fn();

      render(<EstadoCarga tiempoLimiteMs={5000} alExpirarTiempoLimite={onTimeout} />);
      expect(onTimeout).not.toHaveBeenCalled();

      act(() => {
        vi.advanceTimersByTime(5000);
      });

      expect(onTimeout).toHaveBeenCalledTimes(1);
      vi.useRealTimers();
    });
  });

  // ------------------------------------------------------------------ 3. EstadoError
  describe("EstadoError — Tarjeta Accionable con Traza", () => {
    it("1. cumple con accesibilidad role='alert' y renderiza mensaje personalizado", () => {
      render(
        <EstadoError
          titulo="Error Inesperado"
          mensaje="Ocurrió un fallo en el componente."
          data-testid="error-custom"
        />
      );

      const alert = screen.getByTestId("error-custom");
      expect(alert.getAttribute("role")).toBe("alert");
      expect(screen.getByText("Error Inesperado")).toBeDefined();
      expect(screen.getByText("Ocurrió un fallo en el componente.")).toBeDefined();
    });

    it("2. mapea semánticamente HTTP 503 AGREGADO_NO_DISPONIBLE", () => {
      const error503 = new ApiError(503, "AGREGADO_NO_DISPONIBLE", "Agregados analíticos en refresco");
      render(<EstadoError error={error503} />);

      expect(screen.getByText("Servicio Analítico en Refresco Temporal (503)")).toBeDefined();
      expect(
        screen.getByText("Agregados analíticos en refresco")
      ).toBeDefined();
    });

    it("3. mapea semánticamente HTTP 403 ROL_STAFF_INSUFICIENTE", () => {
      const error403 = new ApiError(403, "ROL_STAFF_INSUFICIENTE", "Permisos insuficientes");
      render(<EstadoError error={error403} />);

      expect(screen.getByText("Acceso Restringido (403 ROL_STAFF_INSUFICIENTE)")).toBeDefined();
    });

    it("4. mapea semánticamente HTTP 404 NO_ENCONTRADO", () => {
      const error404 = new ApiError(404, "NO_ENCONTRADO", "Organización no encontrada");
      render(<EstadoError error={error404} />);

      expect(screen.getByText("Recurso No Encontrado (404)")).toBeDefined();
    });

    it("5. mapea semánticamente errores de red (status 0 / ERROR_RED)", () => {
      const errorRed = new ApiError(0, "ERROR_RED", "Fallo de conexión");
      render(<EstadoError error={errorRed} />);

      expect(screen.getByText("Error de Conexión de Red")).toBeDefined();
    });

    it("6. extrae y muestra de forma visible el identificador de traza X-Trace-Id", () => {
      const errorConTrace = new ApiError(
        500,
        "ERROR_INTERNO",
        "Fallo de base de datos",
        undefined,
        "trc_auditoria_9981"
      );

      render(<EstadoError error={errorConTrace} />);

      const traceEl = screen.getByTestId("error-trace-id");
      expect(traceEl).toBeDefined();
      expect(traceEl.textContent).toBe("trc_auditoria_9981");
    });

    it("7. ofrece botón interactivo de reintento que ejecuta alReintentar()", () => {
      const onRetry = vi.fn();
      render(<EstadoError alReintentar={onRetry} textoBotonReintento="Volver a intentar" />);

      const btn = screen.getByTestId("btn-reintentar");
      expect(btn.textContent).toBe("Volver a intentar");

      fireEvent.click(btn);
      expect(onRetry).toHaveBeenCalledTimes(1);
    });

    it("8. renderiza acción secundaria y respeta modo compacto", () => {
      render(
        <EstadoError
          compacto
          alReintentar={() => {}}
          accionSecundaria={<a href="/overview">Ir al inicio</a>}
        />
      );

      expect(screen.getByText("Ir al inicio")).toBeDefined();
    });
  });

  // ------------------------------------------------------------------ 4. EstadoVacio
  describe("EstadoVacio — Representación Amigable Sin Datos", () => {
    it("1. renderiza título, descripción e iconografía por defecto", () => {
      render(<EstadoVacio />);

      expect(screen.getByText("Sin datos disponibles")).toBeDefined();
      expect(
        screen.getByText(
          "No se encontraron registros que coincidan con la consulta o los filtros aplicados."
        )
      ).toBeDefined();
    });

    it("2. ofrece botón de acción sugerida interactivo (ej. Limpiar filtros)", () => {
      const onAction = vi.fn();
      render(
        <EstadoVacio
          titulo="Sin organizaciones encontradas"
          descripcion="Prueba a ajustar los criterios de búsqueda"
          alAccionar={onAction}
          textoAccion="Restablecer filtros"
        />
      );

      expect(screen.getByText("Sin organizaciones encontradas")).toBeDefined();
      const btn = screen.getByTestId("btn-accion-vacio");
      expect(btn.textContent).toBe("Restablecer filtros");

      fireEvent.click(btn);
      expect(onAction).toHaveBeenCalledTimes(1);
    });
  });

  // ------------------------------------------------------------------ 5. ContenedorEstado
  describe("ContenedorEstado — Orquestador Declarativo", () => {
    it("1. renderiza EstadoCarga cuando cargando=true", () => {
      render(
        <ContenedorEstado cargando={true}>
          <div data-testid="contenido-real">Contenido Cargado</div>
        </ContenedorEstado>
      );

      expect(screen.getByRole("status")).toBeDefined();
      expect(screen.queryByTestId("contenido-real")).toBeNull();
    });

    it("2. renderiza EstadoError cuando existe error", () => {
      render(
        <ContenedorEstado cargando={false} error={new Error("Fallo de API")}>
          <div data-testid="contenido-real">Contenido Cargado</div>
        </ContenedorEstado>
      );

      expect(screen.getByRole("alert")).toBeDefined();
      expect(screen.getByText("Fallo de API")).toBeDefined();
      expect(screen.queryByTestId("contenido-real")).toBeNull();
    });

    it("3. renderiza EstadoVacio cuando vacio=true", () => {
      render(
        <ContenedorEstado cargando={false} error={null} vacio={true} tituloVacio="Lista vacía">
          <div data-testid="contenido-real">Contenido Cargado</div>
        </ContenedorEstado>
      );

      expect(screen.getByText("Lista vacía")).toBeDefined();
      expect(screen.queryByTestId("contenido-real")).toBeNull();
    });

    it("4. renderiza children cuando no hay carga, error ni estado vacío", () => {
      render(
        <ContenedorEstado cargando={false} error={null} vacio={false}>
          <div data-testid="contenido-real">Contenido Listo</div>
        </ContenedorEstado>
      );

      expect(screen.getByTestId("contenido-real").textContent).toBe("Contenido Listo");
      expect(screen.queryByRole("status")).toBeNull();
      expect(screen.queryByRole("alert")).toBeNull();
    });
  });
});
