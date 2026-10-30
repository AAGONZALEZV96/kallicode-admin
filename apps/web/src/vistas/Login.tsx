/**
 * Login.tsx — Vista de inicio de sesión de personal (Paso 1: Email + Contraseña)
 */

import React, { useState } from "react";
import { useNavigate, useLocation } from "react-router-dom";
import { useAuth } from "../estado/auth";
import { Input } from "../componentes/Input";
import { Boton } from "../componentes/Boton";

export const Login: React.FC = () => {
  const { login, estaAutenticado, cargando } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [errorLocal, setErrorLocal] = useState<string | null>(null);

  // Si ya está autenticado, redirigir
  React.useEffect(() => {
    if (estaAutenticado) {
      navigate("/", { replace: true });
    }
  }, [estaAutenticado, navigate]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setErrorLocal(null);

    if (!email || !password) {
      setErrorLocal("Por favor ingresa tu correo electrónico y contraseña.");
      return;
    }

    try {
      await login({ email, password });
      // Redirigir al segundo factor preservando el estado de redirección
      navigate("/mfa", { state: location.state });
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Credenciales no válidas.";
      setErrorLocal(msg);
    }
  };

  return (
    <div
      style={{
        minHeight: "100vh",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        backgroundColor: "var(--bg, #0f172a)",
        padding: "1.5rem",
      }}
    >
      <div
        style={{
          maxWidth: "420px",
          width: "100%",
          backgroundColor: "var(--card, #1e293b)",
          border: "1px solid var(--border, #334155)",
          borderRadius: "0.5rem",
          padding: "2.5rem 2rem",
          boxShadow: "var(--shadow-lg, 0 10px 15px -3px rgba(0,0,0,0.4))",
        }}
      >
        <div style={{ textAlign: "center", marginBottom: "2rem" }}>
          <h1
            style={{
              fontSize: "1.5rem",
              fontWeight: 700,
              color: "var(--text, #f8fafc)",
              marginBottom: "0.5rem",
            }}
          >
            KalliCode Admin
          </h1>
          <p style={{ fontSize: "0.875rem", color: "var(--muted, #94a3b8)" }}>
            Consola de Administración de Personal
          </p>
        </div>

        {errorLocal && (
          <div
            role="alert"
            style={{
              backgroundColor: "var(--bad-bg, rgba(239, 68, 68, 0.15))",
              border: "1px solid var(--error, #ef4444)",
              color: "var(--error, #ef4444)",
              padding: "0.75rem 1rem",
              borderRadius: "0.375rem",
              fontSize: "0.8125rem",
              marginBottom: "1.5rem",
            }}
          >
            {errorLocal}
          </div>
        )}

        <form onSubmit={handleSubmit} style={{ display: "flex", flexDirection: "column", gap: "1.25rem" }}>
          <div>
            <label
              htmlFor="email"
              style={{
                display: "block",
                fontSize: "0.8125rem",
                fontWeight: 500,
                color: "var(--text, #f8fafc)",
                marginBottom: "0.375rem",
              }}
            >
              Correo Electrónico (@kallicode.com)
            </label>
            <Input
              id="email"
              name="email"
              type="email"
              placeholder="nombre@kallicode.com"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              autoComplete="username"
              required
            />
          </div>

          <div>
            <label
              htmlFor="password"
              style={{
                display: "block",
                fontSize: "0.8125rem",
                fontWeight: 500,
                color: "var(--text, #f8fafc)",
                marginBottom: "0.375rem",
              }}
            >
              Contraseña
            </label>
            <Input
              id="password"
              name="password"
              type="password"
              placeholder="••••••••••••"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete="current-password"
              required
            />
          </div>

          <div style={{ marginTop: "0.5rem" }}>
            <Boton
              type="submit"
              variante="primary"
              cargando={cargando}
              style={{ width: "100%", justifyContent: "center" }}
            >
              Continuar al Segundo Factor
            </Boton>
          </div>
        </form>
      </div>
    </div>
  );
};
