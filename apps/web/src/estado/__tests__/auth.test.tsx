/**
 * auth.test.tsx — Pruebas de integración del contexto AuthProvider y useAuth
 */

import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, act, waitFor } from "@testing-library/react";
import { AuthProvider, useAuth } from "../auth";
import { clienteApi } from "../../api/clienteApi";

// Componente de prueba para consumir el hook useAuth
const ComponenteConsumidor: React.FC = () => {
  const {
    usuario,
    token,
    estaAutenticado,
    mfaPendiente,
    mfaToken,
    login,
    verificarMfa,
    logout,
    refrescarSesion,
    error,
  } = useAuth();

  return (
    <div>
      <div data-testid="autenticado">{estaAutenticado ? "si" : "no"}</div>
      <div data-testid="mfa-pendiente">{mfaPendiente ? "si" : "no"}</div>
      <div data-testid="mfa-token">{mfaToken || "ninguno"}</div>
      <div data-testid="token">{token || "ninguno"}</div>
      <div data-testid="rol">{usuario?.role || "ninguno"}</div>
      <div data-testid="email">{usuario?.email || "ninguno"}</div>
      <div data-testid="error">{error || "ninguno"}</div>

      <button
        onClick={() => login({ email: "operador@kallicode.com", password: "Password12345!" })}
      >
        Ejecutar Login
      </button>

      <button onClick={() => verificarMfa("123456")}>Verificar MFA</button>
      <button onClick={() => logout()}>Cerrar Sesion</button>
      <button onClick={() => refrescarSesion()}>Refrescar Sesion</button>
    </div>
  );
};

describe("AuthProvider y useAuth", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("1. inicializa con estado no autenticado por defecto", () => {
    render(
      <AuthProvider>
        <ComponenteConsumidor />
      </AuthProvider>
    );

    expect(screen.getByTestId("autenticado").textContent).toBe("no");
    expect(screen.getByTestId("mfa-pendiente").textContent).toBe("no");
    expect(screen.getByTestId("token").textContent).toBe("ninguno");
    expect(screen.getByTestId("rol").textContent).toBe("ninguno");
  });

  it("2. ejecuta login en paso 1 y activa el estado de desafío MFA pendiente", async () => {
    vi.spyOn(clienteApi, "post").mockResolvedValueOnce({
      mfa_token: "mfa_challenge_abc123",
      mfa_inscrito: true,
      expira_en: 300,
    });

    render(
      <AuthProvider>
        <ComponenteConsumidor />
      </AuthProvider>
    );

    await act(async () => {
      screen.getByText("Ejecutar Login").click();
    });

    await waitFor(() => {
      expect(screen.getByTestId("mfa-pendiente").textContent).toBe("si");
      expect(screen.getByTestId("mfa-token").textContent).toBe("mfa_challenge_abc123");
      expect(screen.getByTestId("autenticado").textContent).toBe("no");
    });
  });

  it("3. completa el segundo factor (MFA) emitiendo el token de acceso y perfil del staff", async () => {
    // 1. Simular login
    vi.spyOn(clienteApi, "post")
      .mockResolvedValueOnce({
        mfa_token: "mfa_challenge_abc123",
        mfa_inscrito: true,
        expira_en: 300,
      })
      // 2. Simular verify
      .mockResolvedValueOnce({
        access_token: "jwt_access_staff_xyz",
        refresh_token: "jwt_refresh_staff_xyz",
        staff: {
          id: "st_01J98K",
          nombre: "Laura Prieto",
          rol: "staff_operaciones",
        },
        expira_en: 900,
      });

    render(
      <AuthProvider>
        <ComponenteConsumidor />
      </AuthProvider>
    );

    // Login
    await act(async () => {
      screen.getByText("Ejecutar Login").click();
    });

    // Verify
    await act(async () => {
      screen.getByText("Verificar MFA").click();
    });

    await waitFor(() => {
      expect(screen.getByTestId("autenticado").textContent).toBe("si");
      expect(screen.getByTestId("mfa-pendiente").textContent).toBe("no");
      expect(screen.getByTestId("token").textContent).toBe("jwt_access_staff_xyz");
      expect(screen.getByTestId("rol").textContent).toBe("staff_operaciones");
      expect(screen.getByTestId("email").textContent).toBe("operador@kallicode.com");
    });
  });

  it("4. el método logout limpia completamente el estado en memoria", async () => {
    const postSpy = vi.spyOn(clienteApi, "post").mockResolvedValueOnce({});

    render(
      <AuthProvider
        sesionInicial={{
          usuario: {
            staff_id: "st_prueba",
            email: "admin@kallicode.com",
            nombre: "Admin KalliCode",
            role: "staff_admin",
            mfa_validado: true,
          },
          token: "jwt_activo",
          refreshToken: "rt_activo",
        }}
      >
        <ComponenteConsumidor />
      </AuthProvider>
    );

    expect(screen.getByTestId("autenticado").textContent).toBe("si");

    await act(async () => {
      screen.getByText("Cerrar Sesion").click();
    });

    await waitFor(() => {
      expect(screen.getByTestId("autenticado").textContent).toBe("no");
      expect(screen.getByTestId("token").textContent).toBe("ninguno");
      expect(screen.getByTestId("rol").textContent).toBe("ninguno");
    });

    expect(postSpy).toHaveBeenCalledWith(
      "/admin/v1/auth/logout",
      { refresh_token: "rt_activo", todas: false },
      { skipAuth: false }
    );
  });

  it("5. refrescarSesion actualiza el token de acceso", async () => {
    vi.spyOn(clienteApi, "post").mockResolvedValueOnce({
      access_token: "jwt_nuevo_renovado",
      refresh_token: "rt_nuevo_renovado",
      expira_en: 900,
    });

    render(
      <AuthProvider
        sesionInicial={{
          usuario: {
            staff_id: "st_prueba",
            email: "admin@kallicode.com",
            nombre: "Admin KalliCode",
            role: "staff_admin",
            mfa_validado: true,
          },
          token: "jwt_viejo",
          refreshToken: "rt_viejo",
        }}
      >
        <ComponenteConsumidor />
      </AuthProvider>
    );

    expect(screen.getByTestId("token").textContent).toBe("jwt_viejo");

    await act(async () => {
      screen.getByText("Refrescar Sesion").click();
    });

    await waitFor(() => {
      expect(screen.getByTestId("token").textContent).toBe("jwt_nuevo_renovado");
    });
  });

  it("6. lanza error descriptivo si useAuth se usa fuera de AuthProvider", () => {
    const consoleSpy = vi.spyOn(console, "error").mockImplementation(() => {});

    expect(() => render(<ComponenteConsumidor />)).toThrow(
      "useAuth debe ser utilizado dentro de un AuthProvider"
    );

    consoleSpy.mockRestore();
  });

  it("7. reanuda automáticamente la sesión compartida desde localStorage en una pestaña nueva si es reciente", () => {
    const sesionValida = {
      token: "jwt_pestaña_compartida",
      refreshToken: "rt_pestaña_compartida",
      usuario: {
        staff_id: "st_compartido",
        email: "staff@kallicode.com",
        nombre: "Personal Compartido",
        role: "staff_negocio",
        mfa_validado: true,
      },
      ultimoAcceso: Date.now() - 5 * 60 * 1000, // Hace 5 minutos (válida dentro del margen de 15 min)
    };

    window.localStorage.setItem("kc_staff_session", JSON.stringify(sesionValida));

    render(
      <AuthProvider>
        <ComponenteConsumidor />
      </AuthProvider>
    );

    expect(screen.getByTestId("autenticado").textContent).toBe("si");
    expect(screen.getByTestId("token").textContent).toBe("jwt_pestaña_compartida");
    expect(screen.getByTestId("rol").textContent).toBe("staff_negocio");
    expect(screen.getByTestId("email").textContent).toBe("staff@kallicode.com");
  });

  it("8. descarta la sesión en localStorage y permanece desautenticado si transcurrieron más de 15 minutos de inactividad", () => {
    const sesionExpirada = {
      token: "jwt_expirado",
      refreshToken: "rt_expirado",
      usuario: {
        staff_id: "st_expirado",
        email: "staff@kallicode.com",
        nombre: "Personal Expirado",
        role: "staff_negocio",
        mfa_validado: true,
      },
      ultimoAcceso: Date.now() - 16 * 60 * 1000, // Hace 16 minutos (excede los 15 min de inactividad)
    };

    window.localStorage.setItem("kc_staff_session", JSON.stringify(sesionExpirada));

    render(
      <AuthProvider>
        <ComponenteConsumidor />
      </AuthProvider>
    );

    expect(screen.getByTestId("autenticado").textContent).toBe("no");
    expect(screen.getByTestId("token").textContent).toBe("ninguno");
    expect(window.localStorage.getItem("kc_staff_session")).toBeNull();
  });

  it("9. sincroniza el cierre de sesión entre pestañas ante un evento storage externo", async () => {
    render(
      <AuthProvider
        sesionInicial={{
          usuario: {
            staff_id: "st_tab",
            email: "staff@kallicode.com",
            nombre: "Staff",
            role: "staff_admin",
            mfa_validado: true,
          },
          token: "jwt_tab",
          refreshToken: "rt_tab",
        }}
      >
        <ComponenteConsumidor />
      </AuthProvider>
    );

    expect(screen.getByTestId("autenticado").textContent).toBe("si");

    // Simular que otra pestaña eliminó la sesión
    await act(async () => {
      window.dispatchEvent(
        new StorageEvent("storage", {
          key: "kc_staff_session",
          newValue: null,
        })
      );
    });

    await waitFor(() => {
      expect(screen.getByTestId("autenticado").textContent).toBe("no");
      expect(screen.getByTestId("token").textContent).toBe("ninguno");
    });
  });
});
