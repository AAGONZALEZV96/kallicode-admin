/**
 * Skeleton.tsx — Primitiva de Marcador de Posición para Carga Estructurada
 *
 * Emula visualmente la forma geométrica de bloques de texto, tarjetas, avatares
 * o elementos de datos mientras se resuelven consultas asíncronas.
 * Sincronizado con tokens.css de KalliCode.
 */

import React from "react";

export type SkeletonForma = "texto" | "rectangular" | "circular";
export type SkeletonRadio = "sm" | "md" | "lg" | "full" | "none";

export interface SkeletonProps extends React.HTMLAttributes<HTMLDivElement> {
  ancho?: string | number;
  alto?: string | number;
  variante?: SkeletonForma;
  redondeado?: SkeletonRadio;
  animar?: boolean;
}

export const Skeleton: React.FC<SkeletonProps> = ({
  ancho,
  alto,
  variante = "rectangular",
  redondeado = "md",
  animar = true,
  className = "",
  style,
  ...props
}) => {
  const getRadius = (r: SkeletonRadio): string => {
    switch (r) {
      case "sm":
        return "var(--radius-sm, 4px)";
      case "md":
        return "var(--radius-md, 8px)";
      case "lg":
        return "var(--radius-lg, 12px)";
      case "full":
        return "var(--radius-full, 9999px)";
      case "none":
        return "0px";
      default:
        return "var(--radius-md, 8px)";
    }
  };

  const getWidth = (): string | number | undefined => {
    if (ancho !== undefined) return ancho;
    if (variante === "circular") return alto || "40px";
    return "100%";
  };

  const getHeight = (): string | number | undefined => {
    if (alto !== undefined) return alto;
    if (variante === "circular") return ancho || "40px";
    if (variante === "texto") return "1em";
    return "100%";
  };

  const borderRadius = variante === "circular" ? "var(--radius-full, 9999px)" : getRadius(redondeado);

  const estilosBase: React.CSSProperties = {
    display: "inline-block",
    width: getWidth(),
    height: getHeight(),
    backgroundColor: "var(--surface2, #334155)",
    borderRadius,
    opacity: animar ? 0.75 : 1,
    animation: animar ? "kc-skeleton-pulse 1.5s ease-in-out infinite" : "none",
    boxSizing: "border-box",
    ...style,
  };

  return (
    <>
      <style>{`
        @keyframes kc-skeleton-pulse {
          0%, 100% {
            opacity: 0.85;
          }
          50% {
            opacity: 0.35;
          }
        }
      `}</style>
      <div
        className={`kc-skeleton ${className}`.trim()}
        style={estilosBase}
        aria-hidden="true"
        {...props}
      />
    </>
  );
};
