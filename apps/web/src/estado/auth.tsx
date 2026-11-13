/**
 * auth.tsx — Contexto y proveedor de autenticación para personal (§18)
 * 
 * Gestiona la identidad de personal staff, el desafío 2FA/TOTP obligatorio,
 * la persistencia segura sincronizada entre pestañas y el temporizador
 * automático de inactividad de 15 minutos (mínimo privilegio y no-fuga E6).
 */

import React, { createContext, useContext, useState, useEffect, useCallback, useMemo, useRef } from "react";
import { clienteApi, setTokenGetter, setUnauthorizedHandler } from "../api/clienteApi";
import { limpiarQueryCache } from "../api/queryClient";

export type RolStaff = "staff_soporte" | "staff_operaciones" | "staff_negocio" | "staff_admin";

export interface UsuarioStaff {
  staff_id: string;
  email: string;
  nombre: string;
  role: RolStaff;
  mfa_validado: boolean;
}

export interface CredencialesLogin {
  email: string;
  password: string;
}

export interface RespuestaLogin {
  mfa_token: string;
  mfa_inscrito: boolean;
  expira_en: number;
}

export interface SesionGuardada {
  token: string;
  refreshToken: string;
  usuario: UsuarioStaff;
  ultimoAcceso: number;
}

export const CLAVE_SESION_STORAGE = "kc_staff_session";
export const TIEMPO_INACTIVIDAD_MS = 15 * 60 * 1000; // 15 minutos en milisegundos

function leerSesionAlmacenada(): SesionGuardada | null {
  try {
    if (typeof window === "undefined" || !window.localStorage) return null;
    const raw = window.localStorage.getItem(CLAVE_SESION_STORAGE);
    if (!raw) return null;
    const parsed: SesionGuardada = JSON.parse(raw);
    if (!parsed || !parsed.token || !parsed.usuario) {
      window.localStorage.removeItem(CLAVE_SESION_STORAGE);
      return null;
    }
    const ahora = Date.now();
    if (ahora - (parsed.ultimoAcceso || 0) > TIEMPO_INACTIVIDAD_MS) {
      window.localStorage.removeItem(CLAVE_SESION_STORAGE);
      return null;
    }
    // Refrescar timestamp al reanudar sesión en pestaña/ventana nueva
    parsed.ultimoAcceso = ahora;
    window.localStorage.setItem(CLAVE_SESION_STORAGE, JSON.stringify(parsed));
    return parsed;
  } catch {
    return null;
  }
}

function guardarSesionEnStorage(token: string, refreshToken: string, usuario: UsuarioStaff): void {
  try {
    if (typeof window !== "undefined" && window.localStorage) {
      const data: SesionGuardada = {
        token,
        refreshToken,
        usuario,
        ultimoAcceso: Date.now(),
      };
      window.localStorage.setItem(CLAVE_SESION_STORAGE, JSON.stringify(data));
    }
  } catch {
    // Evitar fallos si el almacenamiento está restringido
  }
}

function eliminarSesionDeStorage(): void {
  try {
    if (typeof window !== "undefined" && window.localStorage) {
      window.localStorage.removeItem(CLAVE_SESION_STORAGE);
      window.localStorage.removeItem("kc_mock_concesiones_tenants");
    }
  } catch {
    // ignorar
  }
}

export interface AuthContextType {
  usuario: UsuarioStaff | null;
  token: string | null;
  estaAutenticado: boolean;
  mfaPendiente: boolean;
  mfaToken: string | null;
  cargando: boolean;
  error: string | null;
  login: (credenciales: CredencialesLogin) => Promise<RespuestaLogin>;
  verificarMfa: (codigo: string) => Promise<UsuarioStaff>;
  logout: () => Promise<void>;
  refrescarSesion: () => Promise<void>;
  limpiarError: () => void;
}

const AuthContext = createContext<AuthContextType | null>(null);

export interface AuthProviderProps {
  children: React.ReactNode;
  /** Permite inyectar una sesión inicial (utilizado para pruebas automatizadas). */
  sesionInicial?: {
    usuario: UsuarioStaff;
    token: string;
    refreshToken?: string;
  } | null;
}

export const AuthProvider: React.FC<AuthProviderProps> = ({ children, sesionInicial = null }) => {
  const sesionRecuperada = useMemo(() => {
    if (sesionInicial) return sesionInicial;
    return leerSesionAlmacenada();
  }, [sesionInicial]);

  const [token, setToken] = useState<string | null>(sesionRecuperada?.token ?? null);
  const [refreshToken, setRefreshToken] = useState<string | null>(sesionRecuperada?.refreshToken ?? null);
  const [usuario, setUsuario] = useState<UsuarioStaff | null>(sesionRecuperada?.usuario ?? null);
  const [mfaToken, setMfaToken] = useState<string | null>(null);
  const [emailTemporal, setEmailTemporal] = useState<string>("");
  const [cargando, setCargando] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);

  const ultimaEscrituraRef = useRef<number>(Date.now());

  // Sincroniza el getter del token con clienteApi
  useEffect(() => {
    setTokenGetter(() => token);
  }, [token]);

  const estaAutenticado = useMemo(
    () => Boolean(token && usuario && usuario.mfa_validado),
    [token, usuario]
  );

  const mfaPendiente = useMemo(
    () => Boolean(mfaToken && !estaAutenticado),
    [mfaToken, estaAutenticado]
  );

  const limpiarEstadoLocal = useCallback(() => {
    setToken(null);
    setRefreshToken(null);
    setUsuario(null);
    setMfaToken(null);
    setEmailTemporal("");
    setError(null);
    eliminarSesionDeStorage();
    limpiarQueryCache();
  }, []);

  const logout = useCallback(async () => {
    setCargando(true);
    try {
      if (token && refreshToken) {
        await clienteApi.post(
          "/admin/v1/auth/logout",
          { refresh_token: refreshToken, todas: false },
          { skipAuth: false }
        ).catch(() => {
          // El logout en servidor es best-effort; si falla por red, limpiamos localmente
        });
      }
    } finally {
      limpiarEstadoLocal();
      setCargando(false);
    }
  }, [token, refreshToken, limpiarEstadoLocal]);

  // Registra el manejador para cuando una petición devuelva 401
  useEffect(() => {
    setUnauthorizedHandler(() => {
      limpiarEstadoLocal();
    });
  }, [limpiarEstadoLocal]);

  const refrescarSesion = useCallback(async () => {
    if (!refreshToken) {
      limpiarEstadoLocal();
      return;
    }
    try {
      const data = await clienteApi.post<{
        access_token: string;
        refresh_token: string;
        expira_en: number;
      }>("/admin/v1/auth/refresh", { refresh_token: refreshToken }, { skipAuth: true });

      setToken(data.access_token);
      setRefreshToken(data.refresh_token);
      if (usuario) {
        guardarSesionEnStorage(data.access_token, data.refresh_token, usuario);
      }
    } catch {
      limpiarEstadoLocal();
      throw new Error("No fue posible renovar la sesión de personal.");
    }
  }, [refreshToken, usuario, limpiarEstadoLocal]);

  const login = useCallback(async (credenciales: CredencialesLogin): Promise<RespuestaLogin> => {
    setCargando(true);
    setError(null);
    try {
      const resp = await clienteApi.post<RespuestaLogin>(
        "/admin/v1/auth/login",
        credenciales,
        { skipAuth: true }
      );
      setMfaToken(resp.mfa_token);
      setEmailTemporal(credenciales.email);
      return resp;
    } catch (err: unknown) {
      const mensaje = err instanceof Error ? err.message : "Error durante el inicio de sesión";
      setError(mensaje);
      throw err;
    } finally {
      setCargando(false);
    }
  }, []);

  const verificarMfa = useCallback(async (codigo: string): Promise<UsuarioStaff> => {
    if (!mfaToken) {
      const msg = "No hay un desafío de segundo factor activo.";
      setError(msg);
      throw new Error(msg);
    }
    setCargando(true);
    setError(null);
    try {
      const resp = await clienteApi.post<{
        access_token: string;
        refresh_token: string;
        staff: {
          id: string;
          nombre: string;
          rol: string;
        };
        expira_en: number;
      }>(
        "/admin/v1/auth/mfa/verify",
        { mfa_token: mfaToken, codigo },
        { skipAuth: true }
      );

      const nuevoUsuario: UsuarioStaff = {
        staff_id: resp.staff.id,
        email: emailTemporal,
        nombre: resp.staff.nombre,
        role: resp.staff.rol as RolStaff,
        mfa_validado: true,
      };

      setToken(resp.access_token);
      setRefreshToken(resp.refresh_token);
      setUsuario(nuevoUsuario);
      setMfaToken(null);
      guardarSesionEnStorage(resp.access_token, resp.refresh_token, nuevoUsuario);
      return nuevoUsuario;
    } catch (err: unknown) {
      const mensaje = err instanceof Error ? err.message : "Código de verificación incorrecto.";
      setError(mensaje);
      throw err;
    } finally {
      setCargando(false);
    }
  }, [mfaToken, emailTemporal]);

  const limpiarError = useCallback(() => {
    setError(null);
  }, []);

  // Registro de actividad del usuario para reiniciar el reloj de inactividad
  const registrarActividad = useCallback(() => {
    if (!token || !usuario) return;
    const ahora = Date.now();
    // Throttle escrituras a localStorage a máximo una cada 15 segundos
    if (ahora - ultimaEscrituraRef.current < 15000) return;
    ultimaEscrituraRef.current = ahora;
    try {
      if (typeof window !== "undefined" && window.localStorage) {
        const raw = window.localStorage.getItem(CLAVE_SESION_STORAGE);
        if (raw) {
          const sesion = JSON.parse(raw);
          sesion.ultimoAcceso = ahora;
          window.localStorage.setItem(CLAVE_SESION_STORAGE, JSON.stringify(sesion));
        }
      }
    } catch {
      // ignorar
    }
  }, [token, usuario]);

  // Escuchar eventos de interacción del usuario (teclado, ratón, scroll, click)
  useEffect(() => {
    if (!estaAutenticado) return;

    const manejarActividad = () => {
      registrarActividad();
    };

    const eventos = ["mousedown", "keydown", "scroll", "touchstart", "click"];
    eventos.forEach((evt) => window.addEventListener(evt, manejarActividad, { passive: true }));

    return () => {
      eventos.forEach((evt) => window.removeEventListener(evt, manejarActividad));
    };
  }, [estaAutenticado, registrarActividad]);

  // Verificación periódica del temporizador de inactividad de 15 minutos
  useEffect(() => {
    if (!estaAutenticado) return;

    const intervalo = setInterval(() => {
      try {
        if (typeof window === "undefined" || !window.localStorage) return;
        const raw = window.localStorage.getItem(CLAVE_SESION_STORAGE);
        if (!raw) {
          // La sesión fue cerrada en otra pestaña
          limpiarEstadoLocal();
          return;
        }
        const sesion = JSON.parse(raw);
        const inactivoMs = Date.now() - (sesion.ultimoAcceso || 0);
        if (inactivoMs >= TIEMPO_INACTIVIDAD_MS) {
          // Excedidos 15 minutos sin actividad de usuario: cerrar sesión
          void logout();
        }
      } catch {
        // ignorar
      }
    }, 10000);

    return () => clearInterval(intervalo);
  }, [estaAutenticado, logout, limpiarEstadoLocal]);

  // Sincronización entre pestañas mediante el evento 'storage'
  useEffect(() => {
    if (typeof window === "undefined") return;

    const manejarStorage = (e: StorageEvent) => {
      if (e.key === CLAVE_SESION_STORAGE) {
        if (!e.newValue) {
          // Otra pestaña cerró la sesión o expiró por inactividad
          limpiarEstadoLocal();
        } else {
          try {
            const sesion: SesionGuardada = JSON.parse(e.newValue);
            const ahora = Date.now();
            if (ahora - (sesion.ultimoAcceso || 0) < TIEMPO_INACTIVIDAD_MS) {
              setToken(sesion.token);
              setRefreshToken(sesion.refreshToken);
              setUsuario(sesion.usuario);
            } else {
              limpiarEstadoLocal();
            }
          } catch {
            limpiarEstadoLocal();
          }
        }
      }
    };

    window.addEventListener("storage", manejarStorage);
    return () => window.removeEventListener("storage", manejarStorage);
  }, [limpiarEstadoLocal]);

  const valor = useMemo<AuthContextType>(
    () => ({
      usuario,
      token,
      estaAutenticado,
      mfaPendiente,
      mfaToken,
      cargando,
      error,
      login,
      verificarMfa,
      logout,
      refrescarSesion,
      limpiarError,
    }),
    [
      usuario,
      token,
      estaAutenticado,
      mfaPendiente,
      mfaToken,
      cargando,
      error,
      login,
      verificarMfa,
      logout,
      refrescarSesion,
      limpiarError,
    ]
  );

  return <AuthContext.Provider value={valor}>{children}</AuthContext.Provider>;
};

export function useAuth(): AuthContextType {
  const contexto = useContext(AuthContext);
  if (!contexto) {
    throw new Error("useAuth debe ser utilizado dentro de un AuthProvider");
  }
  return contexto;
}

/** Variante tolerante cuando el componente se renderiza de forma aislada en pruebas unitarias. */
export function useOptionalAuth(): AuthContextType | null {
  return useContext(AuthContext);
}
