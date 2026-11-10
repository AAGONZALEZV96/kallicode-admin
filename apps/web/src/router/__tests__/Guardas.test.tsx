/**
 * Guardas.test.tsx — Pruebas unitarias de guardas de ruta y control de acceso RBAC
 */

import React from "react";
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter, Routes, Route } from "react-router-dom";
import { AuthProvider, UsuarioStaff } from "../../estado/auth";
import { RutaAutenticada, RutaProtegidaPorRol } from "../Guardas";

const ContenidoProtegido: React.FC = () => <div data-testid="protegido">Contenido Secreto Staff</div>;
const VistaLogin: React.FC = () => <div data-testid="login">Vista de Login</div>;
const VistaMfa: React.FC = () => <div data-testid="mfa">Vista de MFA</div>;
const Vista403: React.FC = () => <div data-testid="403">Vista de Acceso Denegado 403</div>;

describe("Guardas de Ruta (RutaAutenticada y RutaProtegidaPorRol)", () => {
  it("1. RutaAutenticada redirige a /login si no hay usuario autenticado", () => {
    render(
      <AuthProvider>
        <MemoryRouter initialEntries={["/dashboard"]}>
          <Routes>
            <Route path="/login" element={<VistaLogin />} />
            <Route
              path="/dashboard"
              element={
                <RutaAutenticada>
                  <ContenidoProtegido />
                </RutaAutenticada>
              }
            />
          </Routes>
        </MemoryRouter>
      </AuthProvider>
    );

    expect(screen.queryByTestId("protegido")).toBeNull();
    expect(screen.getByTestId("login")).toBeDefined();
  });

  it("2. RutaAutenticada permite el acceso y renderiza los hijos cuando el usuario está autenticado", () => {
    const usuarioValido: UsuarioStaff = {
      staff_id: "st_123",
      email: "soporte@kallicode.com",
      nombre: "Soporte KalliCode",
      role: "staff_soporte",
      mfa_validado: true,
    };

    render(
      <AuthProvider
        sesionInicial={{
          usuario: usuarioValido,
          token: "jwt_token_valido",
        }}
      >
        <MemoryRouter initialEntries={["/dashboard"]}>
          <Routes>
            <Route
              path="/dashboard"
              element={
                <RutaAutenticada>
                  <ContenidoProtegido />
                </RutaAutenticada>
              }
            />
          </Routes>
        </MemoryRouter>
      </AuthProvider>
    );

    expect(screen.getByTestId("protegido")).toBeDefined();
    expect(screen.getByText("Contenido Secreto Staff")).toBeDefined();
  });

  it("3. RutaAutenticada redirige a /login cuando no hay sesión activa", () => {
    render(
      <AuthProvider>
        <MemoryRouter initialEntries={["/dashboard"]}>
          <Routes>
            <Route path="/login" element={<VistaLogin />} />
            <Route path="/mfa" element={<VistaMfa />} />
            <Route
              path="/dashboard"
              element={
                <RutaAutenticada>
                  <ContenidoProtegido />
                </RutaAutenticada>
              }
            />
          </Routes>
        </MemoryRouter>
      </AuthProvider>
    );

    expect(screen.queryByTestId("protegido")).toBeNull();
    expect(screen.getByTestId("login")).toBeDefined();
  });

  it("3. RutaProtegidaPorRol renderiza Error403 cuando el rol del staff no está autorizado", () => {
    const usuarioSoporte: UsuarioStaff = {
      staff_id: "st_123",
      email: "soporte@kallicode.com",
      nombre: "Soporte",
      role: "staff_soporte",
      mfa_validado: true,
    };

    render(
      <AuthProvider
        sesionInicial={{
          usuario: usuarioSoporte,
          token: "jwt_token_valido",
        }}
      >
        <MemoryRouter initialEntries={["/biz/overview"]}>
          <Routes>
            <Route
              path="/biz/overview"
              element={
                <RutaProtegidaPorRol rolesPermitidos={["staff_negocio", "staff_admin"]}>
                  <ContenidoProtegido />
                </RutaProtegidaPorRol>
              }
            />
          </Routes>
        </MemoryRouter>
      </AuthProvider>
    );

    expect(screen.queryByTestId("protegido")).toBeNull();
    // Renderiza la pantalla Error403
    expect(screen.getByText("Acceso Restringido (403)")).toBeDefined();
    expect(screen.getByText("staff_soporte")).toBeDefined();
  });

  it("4. RutaProtegidaPorRol redirige a /403 cuando redireccionar={true} y rol es insuficiente", () => {
    const usuarioOps: UsuarioStaff = {
      staff_id: "st_123",
      email: "ops@kallicode.com",
      nombre: "Operaciones",
      role: "staff_operaciones",
      mfa_validado: true,
    };

    render(
      <AuthProvider
        sesionInicial={{
          usuario: usuarioOps,
          token: "jwt_token_valido",
        }}
      >
        <MemoryRouter initialEntries={["/biz/overview"]}>
          <Routes>
            <Route path="/403" element={<Vista403 />} />
            <Route
              path="/biz/overview"
              element={
                <RutaProtegidaPorRol
                  rolesPermitidos={["staff_negocio", "staff_admin"]}
                  redireccionar={true}
                >
                  <ContenidoProtegido />
                </RutaProtegidaPorRol>
              }
            />
          </Routes>
        </MemoryRouter>
      </AuthProvider>
    );

    expect(screen.queryByTestId("protegido")).toBeNull();
    expect(screen.getByTestId("403")).toBeDefined();
  });

  it("5. RutaProtegidaPorRol concede acceso cuando el rol está en la lista blanca permitida", () => {
    const usuarioAdmin: UsuarioStaff = {
      staff_id: "st_admin",
      email: "admin@kallicode.com",
      nombre: "Admin",
      role: "staff_admin",
      mfa_validado: true,
    };

    render(
      <AuthProvider
        sesionInicial={{
          usuario: usuarioAdmin,
          token: "jwt_admin",
        }}
      >
        <MemoryRouter initialEntries={["/ops/agents"]}>
          <Routes>
            <Route
              path="/ops/agents"
              element={
                <RutaProtegidaPorRol rolesPermitidos={["staff_operaciones", "staff_admin"]}>
                  <ContenidoProtegido />
                </RutaProtegidaPorRol>
              }
            />
          </Routes>
        </MemoryRouter>
      </AuthProvider>
    );

    expect(screen.getByTestId("protegido")).toBeDefined();
  });
});
