import React, { useRef, useState, useEffect, useCallback } from "react";
import { useTranslation } from "react-i18next";

export type DensidadTabla = "normal" | "alta";
export type PrioridadColumna = "alta" | "media" | "baja";

export interface TablaProps extends React.TableHTMLAttributes<HTMLTableElement> {
  cabeceraFija?: boolean;
  filasAlternadas?: boolean;
  densidad?: DensidadTabla;
  envoltura?: boolean;
  envolturaClassName?: string;
  mostrarTodasColumnas?: boolean;
  ariaLabelRegion?: string;
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
  mostrarTodasColumnas = false,
  ariaLabelRegion,
  cargando = false,
  textoCarga,
  estadoVacio,
  className = "",
  children,
  ...props
}) => {
  const { t } = useTranslation();
  const wrapperRef = useRef<HTMLDivElement>(null);
  const [scrollState, setScrollState] = useState<{ left: boolean; right: boolean }>({
    left: false,
    right: false,
  });

  const actualizarIndicadoresScroll = useCallback(() => {
    const el = wrapperRef.current;
    if (!el) return;
    const maxScroll = Math.max(0, el.scrollWidth - el.clientWidth);
    const hasLeft = el.scrollLeft > 2;
    const hasRight = maxScroll > 2 && el.scrollLeft < maxScroll - 2;
    setScrollState((prev) =>
      prev.left === hasLeft && prev.right === hasRight ? prev : { left: hasLeft, right: hasRight }
    );
  }, []);

  useEffect(() => {
    if (!envoltura) return;
    actualizarIndicadoresScroll();

    const el = wrapperRef.current;
    if (!el) return;

    let observer: ResizeObserver | null = null;
    if (typeof ResizeObserver !== "undefined") {
      observer = new ResizeObserver(() => actualizarIndicadoresScroll());
      observer.observe(el);
    }

    window.addEventListener("resize", actualizarIndicadoresScroll);
    return () => {
      observer?.disconnect();
      window.removeEventListener("resize", actualizarIndicadoresScroll);
    };
  }, [envoltura, actualizarIndicadoresScroll, children, mostrarTodasColumnas]);

  const textoCargaEfectivo = textoCarga ?? t("common.states.loading");
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
          <span>{textoCargaEfectivo}</span>
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
    const clasesEnvoltura = [
      "table-container",
      mostrarTodasColumnas && "tabla-mostrar-todas",
      envolturaClassName,
    ]
      .filter(Boolean)
      .join(" ");

    return (
      <div
        ref={wrapperRef}
        className={clasesEnvoltura}
        role="region"
        tabIndex={0}
        aria-label={ariaLabelRegion ?? props["aria-label"] ?? t("components.table.regionLabel")}
        data-scroll-left={String(scrollState.left)}
        data-scroll-right={String(scrollState.right)}
        onScroll={actualizarIndicadoresScroll}
      >
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
  fija?: boolean;
  prioridad?: PrioridadColumna;
}

export const TablaCeldaEncabezado: React.FC<TablaCeldaEncabezadoProps> = ({
  numerico = false,
  fija = false,
  prioridad = "alta",
  className = "",
  ...props
}) => {
  const clases = [
    numerico && "num",
    fija && "kc-col-sticky",
    prioridad !== "alta" && `kc-col-priority-${prioridad}`,
    className,
  ]
    .filter(Boolean)
    .join(" ");
  return <th className={clases || undefined} {...props} />;
};

export interface TablaCeldaProps extends React.TdHTMLAttributes<HTMLTableCellElement> {
  numerico?: boolean;
  fija?: boolean;
  prioridad?: PrioridadColumna;
}

export const TablaCelda: React.FC<TablaCeldaProps> = ({
  numerico = false,
  fija = false,
  prioridad = "alta",
  className = "",
  ...props
}) => {
  const clases = [
    numerico && "num",
    fija && "kc-col-sticky",
    prioridad !== "alta" && `kc-col-priority-${prioridad}`,
    className,
  ]
    .filter(Boolean)
    .join(" ");
  return <td className={clases || undefined} {...props} />;
};
