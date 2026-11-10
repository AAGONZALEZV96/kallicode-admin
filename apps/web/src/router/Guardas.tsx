/**
 * Guardas.tsx — Guardas de Enrutado para Autenticación y Control de Acceso RBAC
 * 
 * - RutaAutenticada: Restringe el acceso exclusivamente a personal autenticado con 2FA completado.
 * - RutaProtegidaPorRol: Restringe vistas a combinaciones específicas de roles de staff.
 */

import React from "react";
import { Navigate, useLocation, Outlet } from "react-router-dom";
import { useAuth, RolStaff } from "../estado/auth";
import { Error403 } from "../vistas/Error403";

export interface RutaAutenticadaProps {
  children?: React.ReactNode;
}

export const RutaAutenticada: React.FC<RutaAutenticadaProps> = ({ children }) => {
  const { estaAutenticado, mfaPendiente } = useAuth();
  const location = useLocation();

  if (!estaAutenticado) {
    if (mfaPendiente) {
      return <Navigate to="/mfa" state={{ from: location }} replace />;
    }
    return <Navigate to="/login" state={{ from: location }} replace />;
  }

  return children ? <>{children}</> : <Outlet />;
};

export interface RutaProtegidaPorRolProps {
  rolesPermitidos: RolStaff[];
  children?: React.ReactNode;
  redireccionar?: boolean;
}

export const RutaProtegidaPorRol: React.FC<RutaProtegidaPorRolProps> = ({
  rolesPermitidos,
  children,
  redireccionar = false,
}) => {
  const { usuario } = useAuth();

  if (!usuario || !rolesPermitidos.includes(usuario.role)) {
    if (redireccionar) {
      return <Navigate to="/403" replace />;
    }
    return <Error403 />;
  }

  return children ? <>{children}</> : <Outlet />;
};
