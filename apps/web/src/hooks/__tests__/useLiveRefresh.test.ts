import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { useLiveRefresh } from "../useLiveRefresh";

describe("useLiveRefresh", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    // Resetear visibilidad por defecto a visible
    Object.defineProperty(document, "hidden", {
      configurable: true,
      get: () => false,
    });
    Object.defineProperty(document, "visibilityState", {
      configurable: true,
      get: () => "visible",
    });
    Object.defineProperty(document, "hasFocus", {
      configurable: true,
      value: () => true,
    });
  });

  afterEach(() => {
    vi.clearAllTimers();
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("1. ejecuta el callback periódicamente cuando está activo", async () => {
    const alRefrescar = vi.fn().mockResolvedValue(undefined);

    renderHook(() =>
      useLiveRefresh({
        intervaloMs: 15_000,
        activo: true,
        alRefrescar,
      })
    );

    expect(alRefrescar).not.toHaveBeenCalled();

    // Avanzar 15 segundos
    await act(async () => {
      vi.advanceTimersByTime(15_000);
    });
    expect(alRefrescar).toHaveBeenCalledTimes(1);

    // Avanzar otros 15 segundos
    await act(async () => {
      vi.advanceTimersByTime(15_000);
    });
    expect(alRefrescar).toHaveBeenCalledTimes(2);
  });

  it("2. pausa automáticamente el polling cuando la pestaña pasa a segundo plano (document.hidden === true)", async () => {
    const alRefrescar = vi.fn().mockResolvedValue(undefined);

    const { result } = renderHook(() =>
      useLiveRefresh({
        intervaloMs: 10_000,
        activo: true,
        alRefrescar,
        pausarEnSegundoPlano: true,
      })
    );

    // Ocultar pestaña
    act(() => {
      Object.defineProperty(document, "hidden", {
        configurable: true,
        get: () => true,
      });
      document.dispatchEvent(new Event("visibilitychange"));
    });

    expect(result.current.estaVisible).toBe(false);
    expect(result.current.enPausaPorVisibilidad).toBe(true);

    // Avanzar tiempo con la pestaña oculta
    await act(async () => {
      vi.advanceTimersByTime(30_000);
    });

    // No debe haber llamado al callback en segundo plano
    expect(alRefrescar).not.toHaveBeenCalled();
  });

  it("3. reanuda automáticamente el polling cuando la pestaña vuelve a estar visible", async () => {
    const alRefrescar = vi.fn().mockResolvedValue(undefined);

    const { result } = renderHook(() =>
      useLiveRefresh({
        intervaloMs: 10_000,
        activo: true,
        alRefrescar,
        pausarEnSegundoPlano: true,
      })
    );

    // Ocultar pestaña
    act(() => {
      Object.defineProperty(document, "hidden", {
        configurable: true,
        get: () => true,
      });
      document.dispatchEvent(new Event("visibilitychange"));
    });

    expect(result.current.enPausaPorVisibilidad).toBe(true);

    // Volver a hacer visible la pestaña
    act(() => {
      Object.defineProperty(document, "hidden", {
        configurable: true,
        get: () => false,
      });
      document.dispatchEvent(new Event("visibilitychange"));
    });

    expect(result.current.estaVisible).toBe(true);
    expect(result.current.enPausaPorVisibilidad).toBe(false);

    // Avanzar intervalo
    await act(async () => {
      vi.advanceTimersByTime(10_000);
    });

    expect(alRefrescar).toHaveBeenCalledTimes(1);
  });

  it("4. pausa el polling cuando la ventana pierde el foco (window.blur) y reanuda en window.focus", async () => {
    const alRefrescar = vi.fn().mockResolvedValue(undefined);

    const { result } = renderHook(() =>
      useLiveRefresh({
        intervaloMs: 10_000,
        activo: true,
        alRefrescar,
        pausarEnPerdidaFoco: true,
      })
    );

    // Pérdida de foco
    act(() => {
      window.dispatchEvent(new Event("blur"));
    });

    expect(result.current.tieneFoco).toBe(false);
    expect(result.current.enPausaPorVisibilidad).toBe(true);

    // Avanzar tiempo sin foco
    await act(async () => {
      vi.advanceTimersByTime(20_000);
    });
    expect(alRefrescar).not.toHaveBeenCalled();

    // Recuperar foco
    act(() => {
      window.dispatchEvent(new Event("focus"));
    });
    expect(result.current.tieneFoco).toBe(true);

    // Avanzar intervalo
    await act(async () => {
      vi.advanceTimersByTime(10_000);
    });
    expect(alRefrescar).toHaveBeenCalledTimes(1);
  });

  it("5. prevención estricta de consultas concurrentes o solapadas", async () => {
    let resolverLlamada!: () => void;
    const promesaLenta = new Promise<void>((resolve) => {
      resolverLlamada = resolve;
    });

    const alRefrescar = vi.fn().mockImplementation(() => promesaLenta);

    const { result } = renderHook(() =>
      useLiveRefresh({
        intervaloMs: 10_000,
        activo: true,
        alRefrescar,
      })
    );

    // Disparar primer tick
    await act(async () => {
      vi.advanceTimersByTime(10_000);
    });
    expect(alRefrescar).toHaveBeenCalledTimes(1);
    expect(result.current.refrescando).toBe(true);

    // Avanzar otros 20 segundos mientras la promesa sigue pendiente
    await act(async () => {
      vi.advanceTimersByTime(20_000);
    });

    // NO debe haber llamado una segunda vez porque la primera aún está ejecutando
    expect(alRefrescar).toHaveBeenCalledTimes(1);

    // Resolver la primera promesa lenta
    await act(async () => {
      resolverLlamada();
    });
    expect(result.current.refrescando).toBe(false);

    // Tras resolver, el siguiente ciclo debe planificarse
    await act(async () => {
      vi.advanceTimersByTime(10_000);
    });
    expect(alRefrescar).toHaveBeenCalledTimes(2);
  });

  it("6. detiene el polling cuando el usuario lo pausa manualmente", async () => {
    const alRefrescar = vi.fn().mockResolvedValue(undefined);

    const { result } = renderHook(() =>
      useLiveRefresh({
        intervaloMs: 10_000,
        activo: true,
        alRefrescar,
      })
    );

    // Pausar
    act(() => {
      result.current.setActivo(false);
    });
    expect(result.current.activo).toBe(false);

    // Avanzar tiempo
    await act(async () => {
      vi.advanceTimersByTime(30_000);
    });
    expect(alRefrescar).not.toHaveBeenCalled();

    // Reanudar mediante alternarActivo
    act(() => {
      result.current.alternarActivo();
    });
    expect(result.current.activo).toBe(true);

    await act(async () => {
      vi.advanceTimersByTime(10_000);
    });
    expect(alRefrescar).toHaveBeenCalledTimes(1);
  });

  it("7. permite cambiar dinámicamente la frecuencia de refresco", async () => {
    const alRefrescar = vi.fn().mockResolvedValue(undefined);

    const { result } = renderHook(() =>
      useLiveRefresh({
        intervaloMs: 15_000,
        activo: true,
        alRefrescar,
      })
    );

    // Cambiar a 30 segundos
    act(() => {
      result.current.setIntervaloMs(30_000);
    });
    expect(result.current.intervaloMs).toBe(30_000);

    // Avanzar 15 segundos: no debe disparar aún
    await act(async () => {
      vi.advanceTimersByTime(15_000);
    });
    expect(alRefrescar).not.toHaveBeenCalled();

    // Avanzar otros 15 segundos (total 30s): debe disparar
    await act(async () => {
      vi.advanceTimersByTime(15_000);
    });
    expect(alRefrescar).toHaveBeenCalledTimes(1);
  });

  it("8. refrescarAhora ejecuta de inmediato y reinicia el temporizador", async () => {
    const alRefrescar = vi.fn().mockResolvedValue(undefined);

    const { result } = renderHook(() =>
      useLiveRefresh({
        intervaloMs: 15_000,
        activo: true,
        alRefrescar,
      })
    );

    // Disparar manualmente antes del intervalo
    await act(async () => {
      await result.current.refrescarAhora();
    });
    expect(alRefrescar).toHaveBeenCalledTimes(1);
    expect(result.current.ultimaActualizacion).not.toBeNull();

    // Avanzar 10 segundos (no debe llamar)
    await act(async () => {
      vi.advanceTimersByTime(10_000);
    });
    expect(alRefrescar).toHaveBeenCalledTimes(1);

    // Avanzar otros 5 segundos (completando los 15s desde el disparo manual)
    await act(async () => {
      vi.advanceTimersByTime(5_000);
    });
    expect(alRefrescar).toHaveBeenCalledTimes(2);
  });

  it("9. calcula correctamente los segundos desde la última actualización", async () => {
    const alRefrescar = vi.fn().mockResolvedValue(undefined);

    const { result } = renderHook(() =>
      useLiveRefresh({
        intervaloMs: 10_000,
        activo: true,
        alRefrescar,
      })
    );

    expect(result.current.segundosDesdeUltimaActualizacion).toBe(0);

    // Disparar refresco
    await act(async () => {
      await result.current.refrescarAhora();
    });
    expect(result.current.segundosDesdeUltimaActualizacion).toBe(0);

    // Avanzar 5 segundos en el reloj
    act(() => {
      vi.advanceTimersByTime(5_000);
    });
    expect(result.current.segundosDesdeUltimaActualizacion).toBe(5);
  });

  it("10. respeta el límite de cuota de presupuesto RL-4 (máximo 60 peticiones/minuto)", async () => {
    const alRefrescar = vi.fn().mockResolvedValue(undefined);

    const { result } = renderHook(() =>
      useLiveRefresh({
        intervaloMs: 100, // intervalo muy rápido para simular estrés
        activo: true,
        alRefrescar,
        presupuestoMaximoPorMinuto: 5, // límite bajo para verificar bloqueo
      })
    );

    // Intentar disparar 10 llamadas rápidas manuales
    await act(async () => {
      for (let i = 0; i < 10; i++) {
        await result.current.refrescarAhora();
      }
    });

    // Debe haberse bloqueado a 5 llamadas por el presupuesto configurado
    expect(alRefrescar).toHaveBeenCalledTimes(5);
  });
});
