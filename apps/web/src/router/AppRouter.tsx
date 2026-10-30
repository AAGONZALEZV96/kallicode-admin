/**
 * AppRouter.tsx — Árbol de Rutas y Navegación de la Consola Admin
 * 
 * Conecta rutas públicas de autenticación y rutas privadas protegidas por
 * sesión de personal y roles RBAC.
 */

import React from "react";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { useAuth } from "../estado/auth";
import { RutaAutenticada, RutaProtegidaPorRol } from "./Guardas";
import { AdminLayout } from "../componentes/AdminLayout";
import { Login } from "../vistas/Login";
import { MfaVerify } from "../vistas/MfaVerify";
import { Error403 } from "../vistas/Error403";
import { Error404 } from "../vistas/Error404";
import { OpsAgents } from "../vistas/OpsAgents";
import { OpsModels } from "../vistas/OpsModels";
import { OpsSLA } from "../vistas/OpsSLA";

const InicioRedireccion: React.FC = () => {
  const { usuario } = useAuth();
  if (!usuario) return <Navigate to="/login" replace />;

  if (usuario.role === "staff_operaciones") {
    return <Navigate to="/ops/agents" replace />;
  }
  return <Navigate to="/overview" replace />;
};

const VistaOverviewPlaceholder: React.FC = () => (
  <div style={{ padding: "1.5rem", backgroundColor: "var(--card, #1e293b)", borderRadius: "0.5rem", border: "1px solid var(--border, #334155)" }}>
    <h1 style={{ fontSize: "1.25rem", fontWeight: 600, color: "var(--text, #f8fafc)", marginBottom: "0.5rem" }}>
      Panel General de Negocio (Overview)
    </h1>
    <p style={{ color: "var(--muted, #94a3b8)", fontSize: "0.875rem" }}>
      Consola administrativa conectada a la capa agregada de PostgreSQL.
    </p>
  </div>
);

export const AppRouter: React.FC = () => {
  return (
    <BrowserRouter>
      <Routes>
        {/* Rutas Públicas */}
        <Route path="/login" element={<Login />} />
        <Route path="/mfa" element={<MfaVerify />} />
        <Route path="/403" element={<Error403 />} />

        {/* Rutas Protegidas por Autenticación de Personal */}
        <Route element={<RutaAutenticada />}>
          <Route element={<AdminLayout />}>
            <Route path="/" element={<InicioRedireccion />} />

            {/* Rutas de Negocio: Exclusivo staff_negocio y staff_admin */}
            <Route
              path="/overview"
              element={
                <RutaProtegidaPorRol rolesPermitidos={["staff_negocio", "staff_admin"]}>
                  <VistaOverviewPlaceholder />
                </RutaProtegidaPorRol>
              }
            />

            {/* Rutas de Operaciones: Exclusivo staff_operaciones y staff_admin */}
            <Route
              path="/ops/agents"
              element={
                <RutaProtegidaPorRol rolesPermitidos={["staff_operaciones", "staff_admin"]}>
                  <OpsAgents />
                </RutaProtegidaPorRol>
              }
            />
            <Route
              path="/ops/models"
              element={
                <RutaProtegidaPorRol rolesPermitidos={["staff_operaciones", "staff_admin"]}>
                  <OpsModels />
                </RutaProtegidaPorRol>
              }
            />
            <Route
              path="/ops/sla"
              element={
                <RutaProtegidaPorRol rolesPermitidos={["staff_operaciones", "staff_admin"]}>
                  <OpsSLA />
                </RutaProtegidaPorRol>
              }
            />
          </Route>
        </Route>

        {/* Ruta para capturar cualquier ruta inexistente */}
        <Route path="*" element={<Error404 />} />
      </Routes>
    </BrowserRouter>
  );
};
