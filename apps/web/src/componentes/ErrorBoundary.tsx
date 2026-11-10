/**
 * ErrorBoundary.tsx — Captura global de excepciones de renderizado en la SPA
 * 
 * Previene pantallas en blanco ante fallos inesperados de componentes y renderiza
 * una interfaz de contingencia accionable manteniendo la estabilidad visual.
 */

import { Component, ErrorInfo, ReactNode } from "react";
import { Boton } from "./Boton";

interface ErrorBoundaryProps {
  children: ReactNode;
  fallback?: (error: Error, resetError: () => void) => ReactNode;
}

interface ErrorBoundaryState {
  hasError: boolean;
  error: Error | null;
}

export class ErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  constructor(props: ErrorBoundaryProps) {
    super(props);
    this.state = {
      hasError: false,
      error: null,
    };
  }

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return {
      hasError: true,
      error,
    };
  }

  componentDidCatch(error: Error, errorInfo: ErrorInfo): void {
    // Registro para telemetría interna o depuración en consola
    console.error("ErrorBoundary ha capturado una excepción no controlada:", error, errorInfo);
  }

  resetError = (): void => {
    this.setState({
      hasError: false,
      error: null,
    });
  };

  render(): ReactNode {
    if (this.state.hasError && this.state.error) {
      if (this.props.fallback) {
        return this.props.fallback(this.state.error, this.resetError);
      }

      return (
        <div
          role="alert"
          style={{
            minHeight: "100vh",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            backgroundColor: "var(--bg, #0f172a)",
            color: "var(--text, #f8fafc)",
            padding: "1.5rem",
            fontFamily: "system-ui, -apple-system, sans-serif",
          }}
        >
          <div
            style={{
              maxWidth: "520px",
              width: "100%",
              backgroundColor: "var(--card, #1e293b)",
              border: "1px solid var(--border, #334155)",
              borderRadius: "0.5rem",
              padding: "2rem",
              boxShadow: "var(--shadow-lg, 0 10px 15px -3px rgba(0,0,0,0.4))",
              textAlign: "center",
            }}
          >
            <div
              style={{
                display: "inline-flex",
                alignItems: "center",
                justifyContent: "center",
                width: "48px",
                height: "48px",
                borderRadius: "50%",
                backgroundColor: "var(--bad-bg, rgba(239, 68, 68, 0.15))",
                color: "var(--error, #ef4444)",
                marginBottom: "1rem",
                fontSize: "1.5rem",
                fontWeight: "bold",
              }}
            >
              ⚠
            </div>
            <h1
              style={{
                fontSize: "1.25rem",
                fontWeight: 600,
                marginBottom: "0.5rem",
                color: "var(--text, #f8fafc)",
              }}
            >
              Ha ocurrido un error inesperado
            </h1>
            <p
              style={{
                fontSize: "0.875rem",
                color: "var(--muted, #94a3b8)",
                marginBottom: "1.5rem",
                lineHeight: "1.4",
              }}
            >
              La consola ha detectado un fallo al renderizar la vista. Los datos de sesión y
              auditoría se mantienen a salvo.
            </p>

            <div
              style={{
                backgroundColor: "rgba(0, 0, 0, 0.25)",
                padding: "0.75rem",
                borderRadius: "0.375rem",
                fontSize: "0.8125rem",
                color: "var(--error, #ef4444)",
                textAlign: "left",
                marginBottom: "1.5rem",
                fontFamily: "monospace",
                overflowX: "auto",
                wordBreak: "break-all",
              }}
            >
              {this.state.error.message || "Error desconocido"}
            </div>

            <div style={{ display: "flex", gap: "0.75rem", justifyContent: "center" }}>
              <Boton
                variante="primary"
                onClick={this.resetError}
              >
                Reintentar
              </Boton>
              <Boton
                variante="secondary"
                onClick={() => {
                  window.location.href = "/";
                }}
              >
                Ir al inicio
              </Boton>
            </div>
          </div>
        </div>
      );
    }

    return this.props.children;
  }
}
