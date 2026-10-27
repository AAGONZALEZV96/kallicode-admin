import React from "react";

export type BotonVariante = "primary" | "secondary" | "danger" | "ghost";
export type BotonTamano = "sm" | "md" | "lg";

export interface BotonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variante?: BotonVariante;
  tamano?: BotonTamano;
  cargando?: boolean;
  icono?: React.ReactNode;
  iconoDerecha?: React.ReactNode;
}

export const Boton: React.FC<BotonProps> = ({
  variante = "primary",
  tamano = "md",
  cargando = false,
  icono,
  iconoDerecha,
  disabled,
  children,
  className = "",
  type = "button",
  ...props
}) => {
  const estaDeshabilitado = disabled || cargando;

  const clases = [
    "btn",
    `btn-${variante}`,
    `btn-${tamano}`,
    className,
  ]
    .filter(Boolean)
    .join(" ");

  return (
    <button
      type={type}
      className={clases}
      disabled={estaDeshabilitado}
      aria-busy={cargando ? "true" : undefined}
      aria-disabled={estaDeshabilitado ? "true" : undefined}
      {...props}
    >
      {cargando && <span className="btn-spinner" aria-hidden="true" />}
      {!cargando && icono && <span className="btn-icon">{icono}</span>}
      {children && <span className="btn-text">{children}</span>}
      {!cargando && iconoDerecha && <span className="btn-icon-derecha">{iconoDerecha}</span>}
    </button>
  );
};
