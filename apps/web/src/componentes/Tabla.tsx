import React from "react";

export type DensidadTabla = "normal" | "alta";

export interface TablaProps extends React.TableHTMLAttributes<HTMLTableElement> {
  cabeceraFija?: boolean;
  filasAlternadas?: boolean;
  densidad?: DensidadTabla;
  envoltura?: boolean;
  envolturaClassName?: string;
  cargando?: boolean;
  textoCarga?: string;
  estadoVacio?: React.ReactNode;
}

export const Tabla: React.FC<TablaProps> = ({
  cabeceraFija = true,
  filasAlternadas = true,
  densidad = "normal",
  envoltura = true,
  envolturaClassName = "",
  cargando = false,
  textoCarga = "Cargando datos...",
  estadoVacio,
  className = "",
  children,
  ...props
}) => {
  const clasesTabla = [
    "kc-table",
    cabeceraFija && "sticky-header",
    filasAlternadas && "striped",
    densidad === "alta" && "tabla-densa",
    className,
  ]
    .filter(Boolean)
    .join(" ");

  const tablaNode = (
    <table className={clasesTabla} {...props}>
      {children}
    </table>
  );

  const contenido = (
    <>
      {cargando && (
        <div
          style={{
            padding: "24px",
            textAlign: "center",
            color: "var(--muted)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            gap: "8px",
          }}
          aria-live="polite"
        >
          <span className="btn-spinner" aria-hidden="true" />
          <span>{textoCarga}</span>
        </div>
      )}
      {!cargando && estadoVacio && (
        <div
          style={{
            padding: "32px 16px",
            textAlign: "center",
            color: "var(--muted)",
          }}
        >
          {estadoVacio}
        </div>
      )}
      {!cargando && !estadoVacio && tablaNode}
    </>
  );

  if (envoltura) {
    return (
      <div className={`table-container ${envolturaClassName}`.trim()}>
        {contenido}
      </div>
    );
  }

  return contenido;
};

export const TablaEncabezado: React.FC<React.HTMLAttributes<HTMLTableSectionElement>> = (props) => (
  <thead {...props} />
);

export const TablaCuerpo: React.FC<React.HTMLAttributes<HTMLTableSectionElement>> = (props) => (
  <tbody {...props} />
);

export const TablaFila: React.FC<React.HTMLAttributes<HTMLTableRowElement>> = (props) => (
  <tr {...props} />
);

export interface TablaCeldaEncabezadoProps extends React.ThHTMLAttributes<HTMLTableCellElement> {
  numerico?: boolean;
}

export const TablaCeldaEncabezado: React.FC<TablaCeldaEncabezadoProps> = ({
  numerico = false,
  className = "",
  ...props
}) => (
  <th className={`${numerico ? "num" : ""} ${className}`.trim()} {...props} />
);

export interface TablaCeldaProps extends React.TdHTMLAttributes<HTMLTableCellElement> {
  numerico?: boolean;
}

export const TablaCelda: React.FC<TablaCeldaProps> = ({
  numerico = false,
  className = "",
  ...props
}) => (
  <td className={`${numerico ? "num" : ""} ${className}`.trim()} {...props} />
);
