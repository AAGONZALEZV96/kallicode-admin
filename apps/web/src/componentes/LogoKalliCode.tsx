import React, { useId } from "react";

export interface LogoKalliCodeProps {
  /** 'isotipo' muestra solo el símbolo; 'completo' incluye marca y subtítulo adaptándose al tema CSS. */
  variante?: "isotipo" | "completo";
  /** Altura del SVG en píxeles. */
  altura?: number;
  className?: string;
}

/**
 * Logo vectorial de KalliCode sin etiquetas auxiliares, adaptable a modo claro y oscuro
 * mediante tokens CSS (`--text` y `--muted`).
 */
export const LogoKalliCode: React.FC<LogoKalliCodeProps> = ({
  variante = "completo",
  altura = 32,
  className,
}) => {
  const uid = useId().replace(/:/g, "");
  const gradVortexId = `kc-grad-vortex-${uid}`;
  const gradPinkId = `kc-grad-pink-${uid}`;

  const definiciones = (
    <defs>
      <linearGradient id={gradVortexId} x1="0%" y1="0%" x2="100%" y2="100%">
        <stop offset="0%" stopColor="#00F2FE" />
        <stop offset="100%" stopColor="#4FACFE" />
      </linearGradient>
      <linearGradient id={gradPinkId} x1="0%" y1="0%" x2="100%" y2="100%">
        <stop offset="0%" stopColor="#FF0844" />
        <stop offset="100%" stopColor="#FFB199" />
      </linearGradient>
    </defs>
  );

  const simbolos = (
    <>
      <path
        d="M -40,-60 L -90,0 L -40,60"
        fill="none"
        stroke={`url(#${gradVortexId})`}
        strokeWidth="18"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <path
        d="M 40,-60 L 90,0 L 40,60"
        fill="none"
        stroke={`url(#${gradPinkId})`}
        strokeWidth="18"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <path
        d="M -20,-20 C 10,-20 10,20 -20,20"
        fill="none"
        stroke={`url(#${gradVortexId})`}
        strokeWidth="8"
        strokeLinecap="round"
        opacity="0.8"
      />
      <path
        d="M 20,20 C -10,20 -10,-20 20,-20"
        fill="none"
        stroke={`url(#${gradPinkId})`}
        strokeWidth="8"
        strokeLinecap="round"
        opacity="0.8"
      />
    </>
  );

  if (variante === "isotipo") {
    return (
      <svg
        xmlns="http://www.w3.org/2000/svg"
        viewBox="-105 -75 210 150"
        height={altura}
        className={className}
        role="img"
        aria-label="KalliCode"
        style={{ display: "block", width: "auto", flexShrink: 0 }}
      >
        {definiciones}
        {simbolos}
      </svg>
    );
  }

  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      viewBox="0 0 300 265"
      height={altura}
      className={className}
      role="img"
      aria-label="KalliCode Automated Software"
      style={{ display: "block", width: "auto", margin: "0 auto" }}
    >
      {definiciones}
      <g transform="translate(150, 82)">{simbolos}</g>
      <text
        x="150"
        y="217"
        fontFamily="var(--font-sans, system-ui, sans-serif)"
        fontWeight="bold"
        fontSize="32"
        fill="var(--text, #FFFFFF)"
        textAnchor="middle"
      >
        kallicode
      </text>
      <text
        x="150"
        y="242"
        fontFamily="var(--font-sans, system-ui, sans-serif)"
        fontSize="11"
        fill="var(--muted, #94A3B8)"
        letterSpacing="4"
        textAnchor="middle"
      >
        AUTOMATED SOFTWARE
      </text>
    </svg>
  );
};
