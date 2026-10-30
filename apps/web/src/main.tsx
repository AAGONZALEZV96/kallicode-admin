/**
 * main.tsx — Punto de entrada de la aplicación React SPA
 */

import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import "./estilos/tokens.css";
import "./estilos/globales.css";

async function iniciarAplicacion(): Promise<void> {
  if (import.meta.env.VITE_MOCK === "true") {
    const { worker } = await import("./pruebas/browser");
    await worker.start({ onUnhandledRequest: "bypass" });
  }

  const rootElement = document.getElementById("root");
  if (!rootElement) {
    throw new Error("Elemento raíz #root no encontrado en el DOM.");
  }

  ReactDOM.createRoot(rootElement).render(
    <React.StrictMode>
      <App />
    </React.StrictMode>
  );
}

void iniciarAplicacion();
