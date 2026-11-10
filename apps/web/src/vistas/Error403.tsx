/**
 * Error403.tsx — Vista amigable de Acceso Denegado por Rol (§18, RBAC)
 */

import React from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../estado/auth";
import { Boton } from "../componentes/Boton";
import { Badge } from "../componentes/Badge";

export const Error403: React.FC = () => {
  const { usuario } = useAuth();
  const navigate = useNavigate();

  return (
    <div
      style={{
        minHeight: "70vh",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        padding: "2rem",
        textAlign: "center",
      }}
    >
      <div
        style={{
          maxWidth: "480px",
          width: "100%",
          backgroundColor: "var(--card, #1e293b)",
          border: "1px solid var(--border, #334155)",
          borderRadius: "0.5rem",
          padding: "2.5rem 2rem",
          boxShadow: "var(--shadow-md, 0 4px 6px -1px rgba(0,0,0,0.3))",
        }}
      >
        <div
          style={{
            display: "inline-flex",
            alignItems: "center",
            justifyContent: "center",
            width: "56px",
            height: "56px",
            borderRadius: "50%",
            backgroundColor: "var(--warn-bg, rgba(234, 179, 8, 0.15))",
            color: "var(--warn, #eab308)",
            marginBottom: "1.25rem",
            fontSize: "1.75rem",
          }}
        >
          🔒
        </div>
        <h1
          style={{
            fontSize: "1.375rem",
            fontWeight: 600,
            color: "var(--text, #f8fafc)",
            marginBottom: "0.75rem",
          }}
        >
          Acceso Restringido (403)
        </h1>
        <p
          style={{
            fontSize: "0.875rem",
            color: "var(--muted, #94a3b8)",
            marginBottom: "1.5rem",
            lineHeight: "1.5",
          }}
        >
          Tu rol de personal actual no cuenta con las atribuciones suficientes
          en la matriz de permisos para acceder a esta sección.
        </p>

        {usuario && (
          <div
            style={{
              display: "flex",
              justifyContent: "center",
              alignItems: "center",
              gap: "0.5rem",
              marginBottom: "1.75rem",
              fontSize: "0.8125rem",
              color: "var(--muted, #94a3b8)",
            }}
          >
            <span>Rol asignado:</span>
            <Badge variante="warn">{usuario.role}</Badge>
          </div>
        )}

        <div style={{ display: "flex", justifyContent: "center", gap: "0.75rem" }}>
          <Boton
            variante="primary"
            onClick={() => navigate("/")}
          >
            Volver al Inicio
          </Boton>
        </div>
      </div>
    </div>
  );
};
