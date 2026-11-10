import React, { useId } from "react";

export interface InputProps extends React.InputHTMLAttributes<HTMLInputElement> {
  etiqueta?: React.ReactNode;
  mensajeError?: string;
  textoAyuda?: string;
  requerido?: boolean;
}

export const Input = React.forwardRef<HTMLInputElement, InputProps>(
  (
    {
      etiqueta,
      mensajeError,
      textoAyuda,
      requerido = false,
      id: idProp,
      className = "",
      disabled,
      ...props
    },
    ref
  ) => {
    const idGenerado = useId();
    const inputId = idProp || idGenerado;
    const errorId = `${inputId}-error`;
    const ayudaId = `${inputId}-ayuda`;

    const tieneError = Boolean(mensajeError);

    const descripciones = [
      tieneError && errorId,
      textoAyuda && ayudaId,
    ]
      .filter(Boolean)
      .join(" ");

    return (
      <div className="form-group">
        {etiqueta && (
          <label htmlFor={inputId} className="form-label">
            {etiqueta}
            {requerido && <span className="required" aria-hidden="true">*</span>}
          </label>
        )}
        <input
          ref={ref}
          id={inputId}
          disabled={disabled}
          required={requerido}
          aria-invalid={tieneError ? "true" : undefined}
          aria-describedby={descripciones || undefined}
          className={`kc-input ${tieneError ? "is-error" : ""} ${className}`.trim()}
          {...props}
        />
        {tieneError && (
          <span id={errorId} className="form-error" role="alert">
            {mensajeError}
          </span>
        )}
        {!tieneError && textoAyuda && (
          <span id={ayudaId} className="form-helper">
            {textoAyuda}
          </span>
        )}
      </div>
    );
  }
);

Input.displayName = "Input";
