/**
 * MfaVerify.tsx — Vista de verificación de segundo factor (Paso 2: Código TOTP)
 */

import React, { useState } from "react";
import { useNavigate, useLocation } from "react-router-dom";
import { useAuth } from "../estado/auth";
import { Input } from "../componentes/Input";
import { Boton } from "../componentes/Boton";

export const MfaVerify: React.FC = () => {
  const { verificarMfa, mfaPendiente, estaAutenticado, cargando } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();

  const [codigo, setCodigo] = useState("");
  const [errorLocal, setErrorLocal] = useState<string | null>(null);

  React.useEffect(() => {
    if (estaAutenticado) {
      navigate("/", { replace: true });
    } else if (!mfaPendiente) {
      // Si no hay un desafío pendiente, volver al login
      navigate("/login", { replace: true });
    }
  }, [estaAutenticado, mfaPendiente, navigate]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setErrorLocal(null);

    const limpio = codigo.trim();
    if (!limpio || limpio.length < 6) {
      setErrorLocal("Ingresa el código TOTP de 6 dígitos.");
      return;
    }

    try {
      await verificarMfa(limpio);
      // Redirigir a la ruta original o al home
      const origen = (location.state as { from?: { pathname: string } })?.from?.pathname || "/";
      navigate(origen, { replace: true });
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Código de verificación no válido.";
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
          <div
            style={{
              display: "inline-flex",
              alignItems: "center",
              justifyContent: "center",
              width: "48px",
              height: "48px",
              borderRadius: "50%",
              backgroundColor: "var(--accent-soft, rgba(56, 189, 248, 0.15))",
              color: "var(--accent, #38bdf8)",
              marginBottom: "1rem",
              fontSize: "1.25rem",
            }}
          >
            🛡
          </div>
          <h1
            style={{
              fontSize: "1.375rem",
              fontWeight: 700,
              color: "var(--text, #f8fafc)",
              marginBottom: "0.5rem",
            }}
          >
            Verificación en Dos Pasos
          </h1>
          <p style={{ fontSize: "0.875rem", color: "var(--muted, #94a3b8)", lineHeight: "1.4" }}>
            Ingresa el código de 6 dígitos de tu aplicación autenticadora (TOTP)
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
              htmlFor="codigo"
              style={{
                display: "block",
                fontSize: "0.8125rem",
                fontWeight: 500,
                color: "var(--text, #f8fafc)",
                marginBottom: "0.375rem",
                textAlign: "center",
              }}
            >
              Código de Verificación
            </label>
            <Input
              id="codigo"
              name="codigo"
              type="text"
              inputMode="numeric"
              pattern="[0-9]*"
              maxLength={8}
              placeholder="123456"
              value={codigo}
              onChange={(e) => setCodigo(e.target.value)}
              autoFocus
              required
              style={{ textAlign: "center", letterSpacing: "0.25em", fontSize: "1.25rem" }}
            />
          </div>

          <div style={{ marginTop: "0.5rem", display: "flex", flexDirection: "column", gap: "0.75rem" }}>
            <Boton
              type="submit"
              variante="primary"
              cargando={cargando}
              style={{ width: "100%", justifyContent: "center" }}
            >
              Verificar e Ingresar
            </Boton>
            <Boton
              type="button"
              variante="ghost"
              onClick={() => navigate("/login")}
              style={{ width: "100%", justifyContent: "center" }}
            >
              Volver al Login
            </Boton>
          </div>
        </form>
      </div>
    </div>
  );
};
