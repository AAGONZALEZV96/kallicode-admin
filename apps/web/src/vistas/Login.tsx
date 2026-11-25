/**
 * Login.tsx — Vista de inicio de sesión de personal (Paso 1: Email + Contraseña)
 */

import React, { useState } from "react";
import { useNavigate, useLocation } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { useAuth } from "../estado/auth";
import { Input } from "../componentes/Input";
import { Boton } from "../componentes/Boton";
import { LogoKalliCode } from "../componentes/LogoKalliCode";

export const Login: React.FC = () => {
  const { t } = useTranslation();
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
      setErrorLocal(t("auth.login.errors.missingFields"));
      return;
    }

    try {
      await login({ email, password });
      // Redirigir al segundo factor preservando el estado de redirección
      navigate("/mfa", { state: location.state });
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : t("auth.login.errors.invalidCredentials");
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
        padding: "1rem",
      }}
    >
      <div
        style={{
          maxWidth: "420px",
          width: "100%",
          backgroundColor: "var(--card, #1e293b)",
          border: "1px solid var(--border, #334155)",
          borderRadius: "0.5rem",
          padding: "clamp(1.5rem, 5vw, 2.5rem) clamp(1rem, 5vw, 2rem)",
          boxShadow: "var(--shadow-lg, 0 10px 15px -3px rgba(0,0,0,0.4))",
        }}
      >
        <div style={{ textAlign: "center", marginBottom: "2rem" }}>
          <div style={{ marginBottom: "0.75rem" }}>
            <LogoKalliCode variante="completo" altura={108} />
          </div>
          <h1
            style={{
              fontSize: "0.9375rem",
              fontWeight: 500,
              color: "var(--muted, #94a3b8)",
              margin: 0,
            }}
          >
            {t("auth.login.subtitle")}
          </h1>
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
              {t("auth.login.emailLabel")}
            </label>
            <Input
              id="email"
              name="email"
              type="email"
              placeholder={t("auth.login.emailPlaceholder")}
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
              {t("auth.login.passwordLabel")}
            </label>
            <Input
              id="password"
              name="password"
              type="password"
              placeholder={t("auth.login.passwordPlaceholder")}
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
              {t("auth.login.submit")}
            </Boton>
          </div>
        </form>
      </div>
    </div>
  );
};
