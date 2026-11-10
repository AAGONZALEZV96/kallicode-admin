import React, { useEffect, useRef } from "react";

export interface ModalProps {
  abierto: boolean;
  alCerrar: () => void;
  titulo?: React.ReactNode;
  pie?: React.ReactNode;
  children: React.ReactNode;
  anchoMaximo?: string;
  cerrarConEscape?: boolean;
  cerrarConOverlay?: boolean;
  idTitulo?: string;
}

export const Modal: React.FC<ModalProps> = ({
  abierto,
  alCerrar,
  titulo,
  pie,
  children,
  anchoMaximo = "640px",
  cerrarConEscape = true,
  cerrarConOverlay = true,
  idTitulo = "modal-titulo",
}) => {
  const modalRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!abierto) return;

    const manejarKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape" && cerrarConEscape) {
        alCerrar();
      }
    };

    const cuerpoOverflowOriginal = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    window.addEventListener("keydown", manejarKeyDown);

    // Mover foco al modal al abrir
    modalRef.current?.focus();

    return () => {
      document.body.style.overflow = cuerpoOverflowOriginal;
      window.removeEventListener("keydown", manejarKeyDown);
    };
  }, [abierto, alCerrar, cerrarConEscape]);

  if (!abierto) return null;

  return (
    <div
      className="modal-overlay"
      onClick={(e) => {
        if (cerrarConOverlay && e.target === e.currentTarget) {
          alCerrar();
        }
      }}
      role="presentation"
    >
      <div
        className="modal"
        ref={modalRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titulo ? idTitulo : undefined}
        tabIndex={-1}
        style={{ maxWidth: anchoMaximo }}
      >
        {titulo && (
          <div className="modal-head">
            <h2 id={idTitulo}>{titulo}</h2>
            <button
              type="button"
              className="modal-close"
              onClick={alCerrar}
              aria-label="Cerrar modal"
            >
              ✕
            </button>
          </div>
        )}
        <div className="modal-body">{children}</div>
        {pie && <div className="modal-foot">{pie}</div>}
      </div>
    </div>
  );
};

export const Dialogo = Modal;
