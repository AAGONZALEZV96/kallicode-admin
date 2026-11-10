/**
 * EstadoVacio.tsx — Componente Reutilizable de Estado Vacío (Empty State)
 *
 * Implementa el ticket [KC-ADM-B3-06] (Épica EAD6 / ADM-G08 / §18.18):
 * 1. Representa de forma amigable consultas con cero resultados o filtros sin coincidencias ({ items: [] }).
 * 2. Previene la ambigüedad visual en la que una tabla vacía parece un error o pantalla rota.
 * 3. Proporciona iconografía clara y llamada a la acción sugerida (ej. "Limpiar filtros").
 * 4. Utiliza exclusivamente tokens oficiales de diseño (tokens.css).
 */

import React from "react";
import { Boton } from "./Boton";

export interface EstadoVacioProps extends React.HTMLAttributes<HTMLDivElement> {
  titulo?: string;
  descripcion?: string;
  icono?: React.ReactNode;
  alAccionar?: () => void;
  textoAccion?: string;
  accion?: React.ReactNode;
  compacto?: boolean;
  "data-testid"?: string;
}

export const EstadoVacio: React.FC<EstadoVacioProps> = ({
  titulo = "Sin datos disponibles",
  descripcion = "No se encontraron registros que coincidan con la consulta o los filtros aplicados.",
  icono,
  alAccionar,
  textoAccion = "Limpiar filtros",
  accion,
  compacto = false,
  className = "",
  style,
  "data-testid": dataTestId = "estado-vacio",
  ...props
}) => {
  return (
    <div
      role="region"
      aria-label={titulo}
      data-testid={dataTestId}
      className={`kc-estado-vacio card ${className}`.trim()}
      style={{
        backgroundColor: "var(--surface, #1e293b)",
        border: "var(--border-width, 1px) dashed var(--border, #334155)",
        borderRadius: "var(--radius-lg, 12px)",
        padding: compacto ? "var(--space-4, 16px)" : "var(--space-8, 32px) var(--space-6, 24px)",
        textAlign: "center",
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        gap: "var(--space-3, 12px)",
        width: "100%",
        boxSizing: "border-box",
        margin: compacto ? 0 : "var(--space-4, 16px) auto",
        maxWidth: compacto ? "100%" : "540px",
        ...style,
      }}
      {...props}
    >
      {/* Icono representativo */}
      <div
        aria-hidden="true"
        style={{
          fontSize: compacto ? "1.75rem" : "2.5rem",
          lineHeight: 1,
          color: "var(--muted, #94a3b8)",
          marginBottom: "var(--space-1, 4px)",
        }}
      >
        {icono ?? "📂"}
      </div>

      {/* Título claro */}
      <h3
        style={{
          fontSize: compacto ? "var(--text-base, 14px)" : "var(--text-lg, 16px)",
          fontWeight: "var(--font-semibold, 600)",
          color: "var(--text, #f8fafc)",
          margin: 0,
        }}
      >
        {titulo}
      </h3>

      {/* Descripción amigable */}
      <p
        style={{
          fontSize: "var(--text-sm, 13px)",
          color: "var(--muted, #94a3b8)",
          maxWidth: "420px",
          margin: 0,
          lineHeight: "var(--leading-normal, 1.5)",
        }}
      >
        {descripcion}
      </p>

      {/* Acción sugerida */}
      {(alAccionar || accion) && (
        <div style={{ marginTop: "var(--space-2, 8px)" }}>
          {accion ?? (
            alAccionar && (
              <Boton
                variante="secondary"
                onClick={alAccionar}
                data-testid="btn-accion-vacio"
              >
                {textoAccion}
              </Boton>
            )
          )}
        </div>
      )}
    </div>
  );
};
