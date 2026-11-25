/**
 * Error404.tsx — Vista de Recurso No Encontrado
 */

import React from "react";
import { useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { Boton } from "../componentes/Boton";

export const Error404: React.FC = () => {
  const { t } = useTranslation();
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
          maxWidth: "460px",
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
            backgroundColor: "var(--surface2, #334155)",
            color: "var(--accent, #38bdf8)",
            marginBottom: "1.25rem",
            fontSize: "1.5rem",
            fontWeight: "bold",
          }}
        >
          404
        </div>
        <h1
          style={{
            fontSize: "1.375rem",
            fontWeight: 600,
            color: "var(--text, #f8fafc)",
            marginBottom: "0.75rem",
          }}
        >
          {t("auth.error404.title")}
        </h1>
        <p
          style={{
            fontSize: "0.875rem",
            color: "var(--muted, #94a3b8)",
            marginBottom: "1.75rem",
            lineHeight: "1.5",
          }}
        >
          {t("auth.error404.description")}
        </p>

        <div style={{ display: "flex", justifyContent: "center" }}>
          <Boton
            variante="primary"
            onClick={() => navigate("/")}
          >
            {t("auth.error404.backPanel")}
          </Boton>
        </div>
      </div>
    </div>
  );
};
