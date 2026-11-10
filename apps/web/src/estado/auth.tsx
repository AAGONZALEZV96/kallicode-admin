/**
 * auth.tsx — Contexto y proveedor de autenticación para personal (§18)
 * 
 * Mantiene la sesión exclusivamente en memoria (previene fugas de JWT en almacenamiento
 * inseguro), coordina el desafío 2FA/TOTP obligatorio y expone el estado de identidad.
 */

import React, { createContext, useContext, useState, useEffect, useCallback, useMemo } from "react";
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
  const [token, setToken] = useState<string | null>(sesionInicial?.token ?? null);
  const [refreshToken, setRefreshToken] = useState<string | null>(sesionInicial?.refreshToken ?? null);
  const [usuario, setUsuario] = useState<UsuarioStaff | null>(sesionInicial?.usuario ?? null);
  const [mfaToken, setMfaToken] = useState<string | null>(null);
  const [emailTemporal, setEmailTemporal] = useState<string>("");
  const [cargando, setCargando] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);

  // Sincroniza el getter del token con clienteApi
  useEffect(() => {
    setTokenGetter(() => token);
  }, [token]);

  const limpiarEstadoLocal = useCallback(() => {
    setToken(null);
    setRefreshToken(null);
    setUsuario(null);
    setMfaToken(null);
    setEmailTemporal("");
    setError(null);
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
    } catch {
      limpiarEstadoLocal();
      throw new Error("No fue posible renovar la sesión de personal.");
    }
  }, [refreshToken, limpiarEstadoLocal]);

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

  const estaAutenticado = useMemo(
    () => Boolean(token && usuario && usuario.mfa_validado),
    [token, usuario]
  );

  const mfaPendiente = useMemo(
    () => Boolean(mfaToken && !estaAutenticado),
    [mfaToken, estaAutenticado]
  );

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
