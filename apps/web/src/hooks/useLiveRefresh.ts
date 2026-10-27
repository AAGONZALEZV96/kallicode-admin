import { useState, useEffect, useRef, useCallback } from "react";

export interface UseLiveRefreshOpciones {
  /**
   * Intervalo de refresco en milisegundos.
   * Valor por defecto: 15.000 ms (15 segundos).
   * Un valor de 0 desactiva el temporizador automático.
   */
  intervaloMs?: number;

  /**
   * Indica si el auto-refresco se encuentra habilitado por el usuario.
   * Valor por defecto: true.
   */
  activo?: boolean;

  /**
   * Callback asíncrono que realiza la consulta o recarga de datos.
   */
  alRefrescar: () => Promise<void> | void;

  /**
   * Si es true, pausa automáticamente el polling cuando la pestaña pasa a segundo plano
   * mediante la Page Visibility API (document.hidden === true).
   * Valor por defecto: true.
   */
  pausarEnSegundoPlano?: boolean;

  /**
   * Si es true, pausa el polling cuando la ventana del navegador pierde el foco.
   * Valor por defecto: true.
   */
  pausarEnPerdidaFoco?: boolean;

  /**
   * Presupuesto máximo de peticiones por minuto (Político RL-4: 60 req/min por empleado).
   * Valor por defecto: 60.
   */
  presupuestoMaximoPorMinuto?: number;

  /**
   * Si es true, ejecuta una llamada inmediatamente al montar el hook si está activo.
   * Valor por defecto: false (para no duplicar consultas iniciales ya montadas por Query).
   */
  ejecutarAlInicio?: boolean;
}

export interface UseLiveRefreshResultado {
  /** Estado de activación del usuario (Play / Pausa). */
  activo: boolean;
  setActivo: (activo: boolean | ((prev: boolean) => boolean)) => void;
  alternarActivo: () => void;

  /** Intervalo configurado en ms. */
  intervaloMs: number;
  setIntervaloMs: (intervaloMs: number) => void;

  /** Indica si hay una consulta asíncrona en curso. */
  refrescando: boolean;

  /** Fecha y hora de la última actualización exitosa. */
  ultimaActualizacion: Date | null;

  /** Segundos transcurridos desde la última actualización. */
  segundosDesdeUltimaActualizacion: number;

  /** Dispara un refresco inmediato manual respetando prevención de solapamiento y RL-4. */
  refrescarAhora: () => Promise<void>;

  /** Estado de visibilidad de la pestaña (document.hidden === false). */
  estaVisible: boolean;

  /** Estado de foco de la ventana (document.hasFocus()). */
  tieneFoco: boolean;

  /** True si el hook está configurado como activo pero pausado por pestaña oculta o sin foco. */
  enPausaPorVisibilidad: boolean;
}

export function useLiveRefresh({
  intervaloMs: intervaloInicial = 15_000,
  activo: activoInicial = true,
  alRefrescar,
  pausarEnSegundoPlano = true,
  pausarEnPerdidaFoco = true,
  presupuestoMaximoPorMinuto = 60,
  ejecutarAlInicio = false,
}: UseLiveRefreshOpciones): UseLiveRefreshResultado {
  const [activo, setActivo] = useState<boolean>(activoInicial);
  const [intervaloMs, setIntervaloMs] = useState<number>(intervaloInicial);
  const [refrescando, setRefrescando] = useState<boolean>(false);
  const [ultimaActualizacion, setUltimaActualizacion] = useState<Date | null>(null);
  const [segundosDesdeUltima, setSegundosDesdeUltima] = useState<number>(0);

  // Estados de entorno de navegador
  const [estaVisible, setEstaVisible] = useState<boolean>(() => {
    if (typeof document !== "undefined") {
      return !document.hidden;
    }
    return true;
  });

  const [tieneFoco, setTieneFoco] = useState<boolean>(true);

  // Referencias para evitar capturas obsoletas en callbacks asíncronos y temporizadores
  const alRefrescarRef = useRef(alRefrescar);
  alRefrescarRef.current = alRefrescar;

  const temporizadorRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const contadorIntervaloRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const ejecutandoRef = useRef<boolean>(false);
  const desmontadoRef = useRef<boolean>(false);

  // Registro de marcas de tiempo de peticiones para controlar el presupuesto RL-4
  const registroLlamadasRef = useRef<number[]>([]);

  // Determinar si el refresco está pausado automáticamente por contexto de ventana
  const enPausaPorVisibilidad =
    activo &&
    ((pausarEnSegundoPlano && !estaVisible) || (pausarEnPerdidaFoco && !tieneFoco));

  const puedeEjecutar =
    activo &&
    intervaloMs > 0 &&
    (!pausarEnSegundoPlano || estaVisible) &&
    (!pausarEnPerdidaFoco || tieneFoco);

  // Limpiar temporizador programado
  const limpiarTemporizador = useCallback(() => {
    if (temporizadorRef.current !== null) {
      clearTimeout(temporizadorRef.current);
      temporizadorRef.current = null;
    }
  }, []);

  // Verificar si la petición cumple la cuota de presupuesto RL-4
  const cumplePresupuestoRL4 = useCallback((): boolean => {
    const ahora = Date.now();
    const unMinutoAtras = ahora - 60_000;

    // Filtrar llamadas de los últimos 60 segundos
    registroLlamadasRef.current = registroLlamadasRef.current.filter((ts) => ts > unMinutoAtras);

    if (registroLlamadasRef.current.length >= presupuestoMaximoPorMinuto) {
      // Excede el presupuesto de 60 req/min
      return false;
    }

    registroLlamadasRef.current.push(ahora);
    return true;
  }, [presupuestoMaximoPorMinuto]);

  // Ejecución segura de refresco con prevención de solapamiento
  const ejecutarRefresco = useCallback(async (): Promise<void> => {
    // Prevención estricta de consultas concurrentes o solapadas
    if (ejecutandoRef.current || desmontadoRef.current) {
      return;
    }

    // Comprobar política RL-4
    if (!cumplePresupuestoRL4()) {
      return;
    }

    ejecutandoRef.current = true;
    setRefrescando(true);

    try {
      await alRefrescarRef.current();
      if (!desmontadoRef.current) {
        const ahora = new Date();
        setUltimaActualizacion(ahora);
        setSegundosDesdeUltima(0);
      }
    } catch (error) {
      // Silenciar o permitir que el llamador gestione errores de red/query
      // El temporizador continuará planificándose normalmente
    } finally {
      if (!desmontadoRef.current) {
        ejecutandoRef.current = false;
        setRefrescando(false);
      }
    }
  }, [cumplePresupuestoRL4]);

  // Planificador del siguiente ciclo (setTimeout recursivo post-ejecución)
  const programarSiguienteCiclo = useCallback(() => {
    limpiarTemporizador();

    if (!puedeEjecutar || desmontadoRef.current) {
      return;
    }

    temporizadorRef.current = setTimeout(async () => {
      await ejecutarRefresco();
      if (!desmontadoRef.current) {
        // Encolar siguiente ciclo únicamente tras finalizar la ejecución activa
        programarSiguienteCiclo();
      }
    }, intervaloMs);
  }, [puedeEjecutar, intervaloMs, limpiarTemporizador, ejecutarRefresco]);

  // Disparo manual público
  const refrescarAhora = useCallback(async (): Promise<void> => {
    limpiarTemporizador();
    await ejecutarRefresco();
    if (puedeEjecutar) {
      programarSiguienteCiclo();
    }
  }, [limpiarTemporizador, ejecutarRefresco, puedeEjecutar, programarSiguienteCiclo]);

  // Alternador Play / Pausa
  const alternarActivo = useCallback(() => {
    setActivo((prev) => !prev);
  }, []);

  // 1. Escuchar Page Visibility API
  useEffect(() => {
    if (typeof document === "undefined") return;

    const manejarVisibilidad = () => {
      const visible = !document.hidden;
      setEstaVisible(visible);

      if (!visible) {
        // Detener inmediatamente el temporizador al perder visibilidad
        limpiarTemporizador();
      }
    };

    document.addEventListener("visibilitychange", manejarVisibilidad);
    return () => {
      document.removeEventListener("visibilitychange", manejarVisibilidad);
    };
  }, [limpiarTemporizador]);

  // 2. Escuchar Foco de Ventana (Window Focus / Blur)
  useEffect(() => {
    if (typeof window === "undefined") return;

    const manejarFocus = () => {
      setTieneFoco(true);
    };

    const manejarBlur = () => {
      setTieneFoco(false);
      if (pausarEnPerdidaFoco) {
        limpiarTemporizador();
      }
    };

    window.addEventListener("focus", manejarFocus);
    window.addEventListener("blur", manejarBlur);

    return () => {
      window.removeEventListener("focus", manejarFocus);
      window.removeEventListener("blur", manejarBlur);
    };
  }, [pausarEnPerdidaFoco, limpiarTemporizador]);

  // 3. Orquestador del ciclo de vida del polling
  useEffect(() => {
    desmontadoRef.current = false;

    if (ejecutarAlInicio && puedeEjecutar) {
      void ejecutarRefresco().then(() => {
        if (!desmontadoRef.current) {
          programarSiguienteCiclo();
        }
      });
    } else if (puedeEjecutar) {
      programarSiguienteCiclo();
    } else {
      limpiarTemporizador();
    }

    return () => {
      desmontadoRef.current = true;
      limpiarTemporizador();
    };
  }, [puedeEjecutar, programarSiguienteCiclo, limpiarTemporizador, ejecutarAlInicio, ejecutarRefresco]);

  // 4. Contador de segundos transcurridos desde la última actualización
  useEffect(() => {
    contadorIntervaloRef.current = setInterval(() => {
      if (ultimaActualizacion) {
        const segs = Math.floor((Date.now() - ultimaActualizacion.getTime()) / 1000);
        setSegundosDesdeUltima(segs);
      }
    }, 1000);

    return () => {
      if (contadorIntervaloRef.current !== null) {
        clearInterval(contadorIntervaloRef.current);
      }
    };
  }, [ultimaActualizacion]);

  return {
    activo,
    setActivo,
    alternarActivo,
    intervaloMs,
    setIntervaloMs,
    refrescando,
    ultimaActualizacion,
    segundosDesdeUltimaActualizacion: segundosDesdeUltima,
    refrescarAhora,
    estaVisible,
    tieneFoco,
    enPausaPorVisibilidad,
  };
}
