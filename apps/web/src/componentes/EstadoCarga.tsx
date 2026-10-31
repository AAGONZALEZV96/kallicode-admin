/**
 * EstadoCarga.tsx — Componente Reutilizable de Carga Estructurada (Skeleton Loading)
 *
 * Implementa el ticket [KC-ADM-B3-06] (Épica EAD6 / ADM-G08 / §18.18):
 * 1. Emula la estructura visual del contenido real (KPIs, tablas densas, fichas de detalle, formularios).
 * 2. Accesibilidad WCAG 2.1 AA obligatoria: role="status", aria-busy="true", aria-live="polite"
 *    y mensaje accesible para tecnologías de asistencia.
 * 3. Garantía de tiempo límite para prevenir estados de carga indefinidos.
 * 4. Integrado exclusivamente con tokens oficiales de diseño (tokens.css).
 */

import React, { useEffect, useRef } from "react";
import { Skeleton } from "./Skeleton";

export type TipoEstadoCarga = "kpis" | "tabla" | "detalle" | "formulario" | "lista" | "generico";

export interface EstadoCargaProps extends React.HTMLAttributes<HTMLDivElement> {
  tipo?: TipoEstadoCarga;
  filas?: number;
  columnas?: number;
  tarjetas?: number;
  mensaje?: string;
  tiempoLimiteMs?: number;
  alExpirarTiempoLimite?: () => void;
  "data-testid"?: string;
}

const srOnlyStyle: React.CSSProperties = {
  position: "absolute",
  width: "1px",
  height: "1px",
  padding: 0,
  margin: "-1px",
  overflow: "hidden",
  clip: "rect(0, 0, 0, 0)",
  whiteSpace: "nowrap",
  border: 0,
};

export const EstadoCarga: React.FC<EstadoCargaProps> = ({
  tipo = "generico",
  filas = 5,
  columnas = 4,
  tarjetas = 4,
  mensaje = "Cargando datos...",
  tiempoLimiteMs,
  alExpirarTiempoLimite,
  className = "",
  style,
  "data-testid": dataTestId = "estado-carga",
  ...props
}) => {
  const alExpirarRef = useRef(alExpirarTiempoLimite);
  alExpirarRef.current = alExpirarTiempoLimite;

  // Garantía de tiempo límite: previene cargas bloqueadas permanentemente
  useEffect(() => {
    if (!tiempoLimiteMs || tiempoLimiteMs <= 0) return;

    const timer = setTimeout(() => {
      alExpirarRef.current?.();
    }, tiempoLimiteMs);

    return () => clearTimeout(timer);
  }, [tiempoLimiteMs]);

  // Layout 1: KPIs Ejecutivos (BizOverview, etc.)
  const renderKpis = () => (
    <div
      style={{
        display: "grid",
        gridTemplateColumns: `repeat(auto-fit, minmax(240px, 1fr))`,
        gap: "var(--space-4, 16px)",
        width: "100%",
      }}
    >
      {Array.from({ length: tarjetas }).map((_, idx) => (
        <div
          key={idx}
          className="card"
          style={{
            padding: "var(--space-4, 16px)",
            backgroundColor: "var(--surface, #1e293b)",
            border: "var(--border-width, 1px) solid var(--border, #334155)",
            borderRadius: "var(--radius-lg, 12px)",
            display: "flex",
            flexDirection: "column",
            gap: "var(--space-3, 12px)",
          }}
        >
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <Skeleton ancho="55%" alto="14px" redondeado="sm" />
            <Skeleton ancho="28px" alto="28px" redondeado="full" />
          </div>
          <Skeleton ancho="70%" alto="32px" redondeado="md" />
          <div style={{ display: "flex", gap: "var(--space-2, 8px)", alignItems: "center" }}>
            <Skeleton ancho="20%" alto="16px" redondeado="sm" />
            <Skeleton ancho="40%" alto="12px" redondeado="sm" />
          </div>
        </div>
      ))}
    </div>
  );

  // Layout 2: Tabla Densa (BizCustomers, suscripciones, etc.)
  const renderTabla = () => {
    const anchosCeldas = ["40%", "75%", "50%", "65%", "80%", "30%"];
    return (
      <div
        className="card"
        style={{
          padding: "var(--space-4, 16px)",
          backgroundColor: "var(--surface, #1e293b)",
          border: "var(--border-width, 1px) solid var(--border, #334155)",
          borderRadius: "var(--radius-lg, 12px)",
          width: "100%",
          display: "flex",
          flexDirection: "column",
          gap: "var(--space-4, 16px)",
        }}
      >
        {/* Barra superior / controles simulados */}
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: "var(--space-4, 16px)" }}>
          <Skeleton ancho="240px" alto="36px" redondeado="md" />
          <div style={{ display: "flex", gap: "var(--space-2, 8px)" }}>
            <Skeleton ancho="110px" alto="36px" redondeado="md" />
            <Skeleton ancho="110px" alto="36px" redondeado="md" />
          </div>
        </div>

        {/* Cabecera de la tabla */}
        <div
          style={{
            display: "grid",
            gridTemplateColumns: `repeat(${columnas}, 1fr)`,
            gap: "var(--space-3, 12px)",
            paddingBottom: "var(--space-3, 12px)",
            borderBottom: "1px solid var(--border, #334155)",
          }}
        >
          {Array.from({ length: columnas }).map((_, colIdx) => (
            <Skeleton key={colIdx} ancho="60%" alto="16px" redondeado="sm" />
          ))}
        </div>

        {/* Filas de la tabla */}
        <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-3, 12px)" }}>
          {Array.from({ length: filas }).map((_, filaIdx) => (
            <div
              key={filaIdx}
              style={{
                display: "grid",
                gridTemplateColumns: `repeat(${columnas}, 1fr)`,
                gap: "var(--space-3, 12px)",
                paddingTop: filaIdx > 0 ? "var(--space-2, 8px)" : 0,
                borderTop: filaIdx > 0 ? "1px solid rgba(255,255,255,0.05)" : "none",
                alignItems: "center",
              }}
            >
              {Array.from({ length: columnas }).map((_, colIdx) => {
                const anchoIndex = (filaIdx + colIdx) % anchosCeldas.length;
                return (
                  <Skeleton
                    key={colIdx}
                    ancho={anchosCeldas[anchoIndex]}
                    alto="18px"
                    redondeado="sm"
                  />
                );
              })}
            </div>
          ))}
        </div>

        {/* Paginador inferior simulado */}
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", paddingTop: "var(--space-3, 12px)" }}>
          <Skeleton ancho="140px" alto="16px" redondeado="sm" />
          <Skeleton ancho="200px" alto="32px" redondeado="md" />
        </div>
      </div>
    );
  };

  // Layout 3: Ficha 360 / Detalle (CustomerDetail)
  const renderDetalle = () => (
    <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-5, 20px)", width: "100%" }}>
      {/* Cabecera y acciones */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", flexWrap: "wrap", gap: "var(--space-4, 16px)" }}>
        <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-2, 8px)" }}>
          <Skeleton ancho="180px" alto="28px" redondeado="md" />
          <Skeleton ancho="280px" alto="16px" redondeado="sm" />
        </div>
        <Skeleton ancho="160px" alto="38px" redondeado="md" />
      </div>

      {/* Grid de 4 a 6 tarjetas */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(320px, 1fr))",
          gap: "var(--space-4, 16px)",
        }}
      >
        {Array.from({ length: 6 }).map((_, idx) => (
          <div
            key={idx}
            className="card"
            style={{
              padding: "var(--space-4, 16px)",
              backgroundColor: "var(--surface, #1e293b)",
              border: "1px solid var(--border, #334155)",
              borderRadius: "var(--radius-lg, 12px)",
              display: "flex",
              flexDirection: "column",
              gap: "var(--space-3, 12px)",
              minHeight: "160px",
            }}
          >
            <Skeleton ancho="45%" alto="18px" redondeado="sm" />
            <Skeleton ancho="80%" alto="14px" redondeado="sm" />
            <Skeleton ancho="65%" alto="14px" redondeado="sm" />
            <Skeleton ancho="90%" alto="14px" redondeado="sm" />
          </div>
        ))}
      </div>
    </div>
  );

  // Layout 4: Formulario
  const renderFormulario = () => (
    <div
      className="card"
      style={{
        padding: "var(--space-5, 20px)",
        backgroundColor: "var(--surface, #1e293b)",
        border: "1px solid var(--border, #334155)",
        borderRadius: "var(--radius-lg, 12px)",
        display: "flex",
        flexDirection: "column",
        gap: "var(--space-4, 16px)",
        maxWidth: "600px",
        width: "100%",
      }}
    >
      <Skeleton ancho="40%" alto="22px" redondeado="md" />
      {Array.from({ length: 3 }).map((_, idx) => (
        <div key={idx} style={{ display: "flex", flexDirection: "column", gap: "var(--space-1, 4px)" }}>
          <Skeleton ancho="30%" alto="14px" redondeado="sm" />
          <Skeleton ancho="100%" alto="38px" redondeado="md" />
        </div>
      ))}
      <div style={{ display: "flex", justifyContent: "flex-end", gap: "var(--space-3, 12px)", marginTop: "var(--space-2, 8px)" }}>
        <Skeleton ancho="90px" alto="36px" redondeado="md" />
        <Skeleton ancho="120px" alto="36px" redondeado="md" />
      </div>
    </div>
  );

  // Layout 5: Lista o Genérico
  const renderGenerico = () => (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        gap: "var(--space-3, 12px)",
        width: "100%",
      }}
    >
      <div
        className="card"
        style={{
          padding: "var(--space-4, 16px)",
          backgroundColor: "var(--surface, #1e293b)",
          border: "1px solid var(--border, #334155)",
          borderRadius: "var(--radius-lg, 12px)",
          display: "flex",
          flexDirection: "column",
          gap: "var(--space-3, 12px)",
        }}
      >
        <Skeleton ancho="50%" alto="24px" redondeado="md" />
        <Skeleton ancho="85%" alto="16px" redondeado="sm" />
        <Skeleton ancho="70%" alto="16px" redondeado="sm" />
        <Skeleton ancho="90%" alto="16px" redondeado="sm" />
      </div>
    </div>
  );

  const renderContenido = () => {
    switch (tipo) {
      case "kpis":
        return renderKpis();
      case "tabla":
        return renderTabla();
      case "detalle":
        return renderDetalle();
      case "formulario":
        return renderFormulario();
      case "lista":
      case "generico":
      default:
        return renderGenerico();
    }
  };

  return (
    <div
      role="status"
      aria-busy="true"
      aria-live="polite"
      data-testid={dataTestId}
      className={`kc-estado-carga ${className}`.trim()}
      style={{ width: "100%", boxSizing: "border-box", ...style }}
      {...props}
    >
      <span className="sr-only" style={srOnlyStyle}>
        {mensaje}
      </span>
      {renderContenido()}
    </div>
  );
};
