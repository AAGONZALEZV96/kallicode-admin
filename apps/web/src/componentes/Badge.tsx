import React from "react";

export type BadgeVariante =
  | "good"
  | "exito"
  | "warn"
  | "advertencia"
  | "bad"
  | "error"
  | "mut"
  | "neutro"
  | "accent"
  | "masked"
  | "enmascarado";

export interface BadgeProps extends React.HTMLAttributes<HTMLSpanElement> {
  variante?: BadgeVariante;
  punto?: boolean;
}

export const Badge: React.FC<BadgeProps> = ({
  variante = "neutro",
  punto = false,
  children,
  className = "",
  ...props
}) => {
  const claseVariante = `b-${variante}`;
  const clasePunto = `d-${variante}`;

  const clases = ["badge", claseVariante, className].filter(Boolean).join(" ");

  return (
    <span className={clases} {...props}>
      {punto && <span className={`dot ${clasePunto}`} aria-hidden="true" />}
      {children}
    </span>
  );
};
