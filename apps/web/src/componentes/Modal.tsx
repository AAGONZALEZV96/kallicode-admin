import React, { useEffect, useRef } from "react";
import { useTranslation } from "react-i18next";

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
  const { t } = useTranslation();
  const modalRef = useRef<HTMLDivElement>(null);
  const previousActiveRef = useRef<HTMLElement | null>(null);
  const alCerrarRef = useRef(alCerrar);
  alCerrarRef.current = alCerrar;

  // Mover foco al diálogo al abrir y restaurar al elemento origen al cerrar
  useEffect(() => {
    if (!abierto) return;
    previousActiveRef.current =
      document.activeElement instanceof HTMLElement ? document.activeElement : null;

    const focusables = modalRef.current?.querySelectorAll<HTMLElement>(
      'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'
    );
    if (focusables && focusables.length > 0) {
      focusables[0].focus();
    } else {
      modalRef.current?.focus();
    }

    return () => {
      const prev = previousActiveRef.current;
      if (prev && prev.isConnected) {
        prev.focus();
      }
      previousActiveRef.current = null;
    };
  }, [abierto]);

  useEffect(() => {
    if (!abierto) return;

    const manejarKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape" && cerrarConEscape) {
        alCerrarRef.current();
        return;
      }

      if (e.key === "Tab" && modalRef.current) {
        const focusables = Array.from(
          modalRef.current.querySelectorAll<HTMLElement>(
            'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'
          )
        ).filter((el) => el.getAttribute("aria-hidden") !== "true");

        if (focusables.length === 0) {
          e.preventDefault();
          modalRef.current.focus();
          return;
        }

        const first = focusables[0];
        const last = focusables[focusables.length - 1];
        const active = document.activeElement;

        if (e.shiftKey) {
          if (active === first || active === modalRef.current || !modalRef.current.contains(active)) {
            e.preventDefault();
            last.focus();
          }
        } else if (active === last || !modalRef.current.contains(active)) {
          e.preventDefault();
          first.focus();
        }
      }
    };

    const cuerpoOverflowOriginal = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    window.addEventListener("keydown", manejarKeyDown);

    return () => {
      document.body.style.overflow = cuerpoOverflowOriginal;
      window.removeEventListener("keydown", manejarKeyDown);
    };
  }, [abierto, cerrarConEscape]);

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
        style={{
          maxWidth: anchoMaximo,
          "--modal-max-width": anchoMaximo,
        } as React.CSSProperties}
      >
        {titulo && (
          <div className="modal-head">
            <h2 id={idTitulo}>{titulo}</h2>
            <button
              type="button"
              className="modal-close"
              onClick={alCerrar}
              aria-label={t("common.actions.closeModal")}
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
