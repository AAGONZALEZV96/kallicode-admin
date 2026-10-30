/**
 * main.tsx — Punto de entrada de la aplicación React SPA
 */

import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import "./estilos/tokens.css";
import "./estilos/globales.css";

const rootElement = document.getElementById("root");
if (!rootElement) {
  throw new Error("Elemento raíz #root no encontrado en el DOM.");
}

ReactDOM.createRoot(rootElement).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
