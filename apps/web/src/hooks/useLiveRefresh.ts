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

  /**
   * Estado de carga en vuelo reportado por TanStack Query (isFetching).
   * Si es true, se pospone/salta el tick para evitar consultas concurrentes.
   */
  estaConsultando?: boolean;

  /**
   * Si es true, al volver a la pestaña visible (document.hidden === false) dispara
   * un refresco inmediato si no está pausado ni en vuelo (Decisión A1).
   * Valor por defecto: false.
   */
  refrescarAlVolverVisible?: boolean;

  /**
   * Número de peticiones HTTP emitidas por cada ciclo de refresco (para RL-4).
   * Por defecto: 1 (ej. OpsAgents consume 2: agents + queues).
   */
  peticionesPorCiclo?: number;
}

export interface UseLiveRefreshResultado {
  /** Estado de activación efectivo (activo por usuario y con cadencia > 0). */
  activo: boolean;
  setActivo: (activo: boolean | ((prev: boolean) => boolean)) => void;
  setPausado: (pausado: boolean) => void;
  alternarActivo: () => void;

  /** Intervalo configurado en ms y en segundos. */
  intervaloMs: number;
  intervaloSegundos: number;
  setIntervaloMs: (intervaloMs: number) => void;
  setIntervaloSegundos: (segundos: number) => void;

  /** Indica si hay una consulta asíncrona en curso (interna o de TanStack Query). */
  refrescando: boolean;

  /** Fecha y hora de la última actualización exitosa. */
  ultimaActualizacion: Date | null;

  /** Segundos transcurridos desde la última actualización. */
  segundosDesdeUltimaActualizacion: number;

  /** Segundos restantes estimados hasta el próximo refresco automático. */
  tiempoRestanteSegundos: number;

  /** Porcentaje restante (0-100) hacia el próximo refresco automático. */
  porcentajeRestante: number;

  /** Peticiones disponibles restantes dentro de la ventana deslizante de 60s (RL-4). */
  presupuestoRestanteMinuto: number;

  /** Dispara un refresco inmediato manual respetando prevención de solapamiento y RL-4. */
  refrescarAhora: () => Promise<void>;

  /** Estado de visibilidad de la pestaña (document.hidden === false). */
  estaVisible: boolean;

  /** Estado de foco de la ventana (document.hasFocus()). */
  tieneFoco: boolean;

  /** True si el hook está configurado como activo pero pausado por pestaña oculta o sin foco. */
  enPausaPorVisibilidad: boolean;

  /** Alias explícito de enPausaPorVisibilidad conforme a contrato B5-09. */
  pausadoPorVisibilidad: boolean;
}

export function useLiveRefresh({
  intervaloMs: intervaloInicial = 15_000,
  activo: activoInicial = true,
  alRefrescar,
  pausarEnSegundoPlano = true,
  pausarEnPerdidaFoco = true,
  presupuestoMaximoPorMinuto = 60,
  ejecutarAlInicio = false,
  estaConsultando = false,
  refrescarAlVolverVisible = false,
  peticionesPorCiclo = 1,
}: UseLiveRefreshOpciones): UseLiveRefreshResultado {
  const [activoUsuario, setActivoUsuario] = useState<boolean>(activoInicial);
  const [intervaloMs, setIntervaloMsState] = useState<number>(Math.max(0, intervaloInicial));
  const [refrescandoInterno, setRefrescandoInterno] = useState<boolean>(false);
  const [ultimaActualizacion, setUltimaActualizacion] = useState<Date | null>(null);
  const [segundosDesdeUltima, setSegundosDesdeUltima] = useState<number>(0);
  const [tiempoRestanteSegundos, setTiempoRestanteSegundos] = useState<number>(() =>
    activoInicial && intervaloInicial > 0 ? Math.ceil(intervaloInicial / 1000) : 0
  );
  const [presupuestoRestanteMinuto, setPresupuestoRestanteMinuto] = useState<number>(
    presupuestoMaximoPorMinuto
  );

  // Estados de entorno de navegador
  const [estaVisible, setEstaVisible] = useState<boolean>(() => {
    if (typeof document !== "undefined") {
      return !document.hidden;
    }
    return true;
  });

  const [tieneFoco, setTieneFoco] = useState<boolean>(true);

  const activo = activoUsuario && intervaloMs > 0;
  const refrescando = refrescandoInterno || estaConsultando;
  const costeCiclo = Math.max(1, Math.floor(peticionesPorCiclo));

  // Referencias para evitar capturas obsoletas en callbacks asíncronos y temporizadores
  const alRefrescarRef = useRef(alRefrescar);
  alRefrescarRef.current = alRefrescar;

  const estaConsultandoRef = useRef<boolean>(estaConsultando);
  estaConsultandoRef.current = estaConsultando;

  const refrescarAlVolverVisibleRef = useRef<boolean>(refrescarAlVolverVisible);
  refrescarAlVolverVisibleRef.current = refrescarAlVolverVisible;

  const ultimoIntervaloActivoRef = useRef<number>(
    intervaloInicial > 0 ? intervaloInicial : 15_000
  );
  if (intervaloMs > 0) {
    ultimoIntervaloActivoRef.current = intervaloMs;
  }

  const estaVisibleRef = useRef<boolean>(estaVisible);
  estaVisibleRef.current = estaVisible;

  const tieneFocoRef = useRef<boolean>(tieneFoco);
  tieneFocoRef.current = tieneFoco;

  const activoRef = useRef<boolean>(activo);
  activoRef.current = activo;

  const proximaEjecucionMsRef = useRef<number | null>(null);
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
    (!pausarEnSegundoPlano || estaVisible) &&
    (!pausarEnPerdidaFoco || tieneFoco);

  // Limpiar temporizador programado
  const limpiarTemporizador = useCallback(() => {
    if (temporizadorRef.current !== null) {
      clearTimeout(temporizadorRef.current);
      temporizadorRef.current = null;
    }
    proximaEjecucionMsRef.current = null;
  }, []);

  // Verificar si la petición cumple la cuota de presupuesto RL-4
  const cumplePresupuestoRL4 = useCallback((): boolean => {
    const ahora = Date.now();
    const unMinutoAtras = ahora - 60_000;

    // Filtrar llamadas de los últimos 60 segundos
    registroLlamadasRef.current = registroLlamadasRef.current.filter((ts) => ts > unMinutoAtras);

    const disponibles = presupuestoMaximoPorMinuto - registroLlamadasRef.current.length;
    if (disponibles < costeCiclo) {
      setPresupuestoRestanteMinuto(Math.max(0, disponibles));
      return false;
    }

    for (let i = 0; i < costeCiclo; i++) {
      registroLlamadasRef.current.push(ahora);
    }
    setPresupuestoRestanteMinuto(
      Math.max(0, presupuestoMaximoPorMinuto - registroLlamadasRef.current.length)
    );
    return true;
  }, [presupuestoMaximoPorMinuto, costeCiclo]);

  // Ejecución segura de refresco con prevención de solapamiento (interna y TanStack isFetching)
  const ejecutarRefresco = useCallback(async (): Promise<void> => {
    if (ejecutandoRef.current || estaConsultandoRef.current || desmontadoRef.current) {
      return;
    }

    if (!cumplePresupuestoRL4()) {
      return;
    }

    ejecutandoRef.current = true;
    setRefrescandoInterno(true);

    try {
      await alRefrescarRef.current();
      if (!desmontadoRef.current) {
        const ahora = new Date();
        setUltimaActualizacion(ahora);
        setSegundosDesdeUltima(0);
      }
    } catch {
      // El llamador (TanStack Query / UI) gestiona el error sin detener ciclos futuros
    } finally {
      if (!desmontadoRef.current) {
        ejecutandoRef.current = false;
        setRefrescandoInterno(false);
      }
    }
  }, [cumplePresupuestoRL4]);

  // Planificador del siguiente ciclo (setTimeout recursivo post-ejecución)
  const programarSiguienteCiclo = useCallback(() => {
    limpiarTemporizador();

    if (!puedeEjecutar || desmontadoRef.current) {
      setTiempoRestanteSegundos(0);
      return;
    }

    proximaEjecucionMsRef.current = Date.now() + intervaloMs;
    setTiempoRestanteSegundos(Math.ceil(intervaloMs / 1000));

    temporizadorRef.current = setTimeout(async () => {
      await ejecutarRefresco();
      if (!desmontadoRef.current) {
        programarSiguienteCiclo();
      }
    }, intervaloMs);
  }, [puedeEjecutar, intervaloMs, limpiarTemporizador, ejecutarRefresco]);

  // Disparo manual público
  const refrescarAhora = useCallback(async (): Promise<void> => {
    limpiarTemporizador();
    await ejecutarRefresco();
    if (puedeEjecutar && !desmontadoRef.current) {
      programarSiguienteCiclo();
    }
  }, [limpiarTemporizador, ejecutarRefresco, puedeEjecutar, programarSiguienteCiclo]);

  const refrescarAhoraRef = useRef(refrescarAhora);
  refrescarAhoraRef.current = refrescarAhora;

  const setIntervaloMs = useCallback((nuevoMs: number) => {
    const msLimpio = Math.max(0, nuevoMs);
    if (msLimpio > 0) {
      ultimoIntervaloActivoRef.current = msLimpio;
    }
    setIntervaloMsState(msLimpio);
  }, []);

  const setIntervaloSegundos = useCallback(
    (segundos: number) => {
      setIntervaloMs(Math.max(0, Math.round(segundos)) * 1000);
    },
    [setIntervaloMs]
  );

  const setPausado = useCallback(
    (pausado: boolean) => {
      if (pausado) {
        setActivoUsuario(false);
      } else {
        if (intervaloMs <= 0) {
          setIntervaloMsState(ultimoIntervaloActivoRef.current);
        }
        setActivoUsuario(true);
      }
    },
    [intervaloMs]
  );

  // Alternador Play / Pausa (restaura cadencia previa si estaba en 0 / Manual)
  const alternarActivo = useCallback(() => {
    setPausado(activo);
  }, [setPausado, activo]);

  // 1. Escuchar Page Visibility API
  useEffect(() => {
    if (typeof document === "undefined") return;

    const manejarVisibilidad = () => {
      const estabaOculta = !estaVisibleRef.current;
      const visible = !document.hidden;
      estaVisibleRef.current = visible;
      setEstaVisible(visible);

      if (!visible) {
        // Detener inmediatamente el temporizador al perder visibilidad
        limpiarTemporizador();
        setTiempoRestanteSegundos(0);
      } else if (
        estabaOculta &&
        refrescarAlVolverVisibleRef.current &&
        activoRef.current &&
        (!pausarEnPerdidaFoco || tieneFocoRef.current)
      ) {
        // Opcionalmente (Decisión A1) refrescar inmediatamente al volver a la pestaña activa
        void refrescarAhoraRef.current();
      }
    };

    document.addEventListener("visibilitychange", manejarVisibilidad);
    return () => {
      document.removeEventListener("visibilitychange", manejarVisibilidad);
    };
  }, [limpiarTemporizador, pausarEnPerdidaFoco]);

  // 2. Escuchar Foco de Ventana (Window Focus / Blur)
  useEffect(() => {
    if (typeof window === "undefined") return;

    const manejarFocus = () => {
      tieneFocoRef.current = true;
      setTieneFoco(true);
    };

    const manejarBlur = () => {
      tieneFocoRef.current = false;
      setTieneFoco(false);
      if (pausarEnPerdidaFoco) {
        limpiarTemporizador();
        setTiempoRestanteSegundos(0);
      }
    };

    window.addEventListener("focus", manejarFocus);
    window.addEventListener("blur", manejarBlur);

    return () => {
      window.removeEventListener("focus", manejarFocus);
      window.removeEventListener("blur", manejarBlur);
    };
  }, [pausarEnPerdidaFoco, limpiarTemporizador]);

  // Ciclo de vida real de montaje/desmontaje (nunca falsamente desmontado al cambiar deps)
  useEffect(() => {
    desmontadoRef.current = false;
    return () => {
      desmontadoRef.current = true;
    };
  }, []);

  // 3. Orquestador del ciclo de vida del polling
  useEffect(() => {
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
      setTiempoRestanteSegundos(0);
    }

    return () => {
      limpiarTemporizador();
    };
  }, [puedeEjecutar, programarSiguienteCiclo, limpiarTemporizador, ejecutarAlInicio, ejecutarRefresco]);

  // 4. Contador unificado de frescura, cuenta regresiva y presupuesto disponible
  useEffect(() => {
    contadorIntervaloRef.current = setInterval(() => {
      const ahoraMs = Date.now();
      if (ultimaActualizacion) {
        const segs = Math.max(0, Math.floor((ahoraMs - ultimaActualizacion.getTime()) / 1000));
        setSegundosDesdeUltima(segs);
      }
      if (puedeEjecutar && proximaEjecucionMsRef.current !== null) {
        const restante = Math.max(0, Math.ceil((proximaEjecucionMsRef.current - ahoraMs) / 1000));
        setTiempoRestanteSegundos(restante);
      } else {
        setTiempoRestanteSegundos(0);
      }
      const unMinutoAtras = ahoraMs - 60_000;
      const recientes = registroLlamadasRef.current.filter((ts) => ts > unMinutoAtras);
      registroLlamadasRef.current = recientes;
      setPresupuestoRestanteMinuto(Math.max(0, presupuestoMaximoPorMinuto - recientes.length));
    }, 1000);

    return () => {
      if (contadorIntervaloRef.current !== null) {
        clearInterval(contadorIntervaloRef.current);
        contadorIntervaloRef.current = null;
      }
    };
  }, [ultimaActualizacion, puedeEjecutar, presupuestoMaximoPorMinuto]);

  const intervaloSegundos = Math.floor(intervaloMs / 1000);
  const porcentajeRestante =
    puedeEjecutar && intervaloSegundos > 0
      ? Math.min(100, Math.max(0, Math.round((tiempoRestanteSegundos / intervaloSegundos) * 100)))
      : 0;

  return {
    activo,
    setActivo: setActivoUsuario,
    setPausado,
    alternarActivo,
    intervaloMs,
    intervaloSegundos,
    setIntervaloMs,
    setIntervaloSegundos,
    refrescando,
    ultimaActualizacion,
    segundosDesdeUltimaActualizacion: segundosDesdeUltima,
    tiempoRestanteSegundos,
    porcentajeRestante,
    presupuestoRestanteMinuto,
    refrescarAhora,
    estaVisible,
    tieneFoco,
    enPausaPorVisibilidad,
    pausadoPorVisibilidad: enPausaPorVisibilidad,
  };
}
