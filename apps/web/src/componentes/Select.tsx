import React, { useId } from "react";

export interface OpcionSelect {
  valor: string | number;
  etiqueta: string;
  disabled?: boolean;
}

export interface SelectProps extends React.SelectHTMLAttributes<HTMLSelectElement> {
  etiqueta?: React.ReactNode;
  mensajeError?: string;
  textoAyuda?: string;
  requerido?: boolean;
  opciones?: OpcionSelect[];
}

export const Select = React.forwardRef<HTMLSelectElement, SelectProps>(
  (
    {
      etiqueta,
      mensajeError,
      textoAyuda,
      requerido = false,
      opciones,
      id: idProp,
      className = "",
      disabled,
      children,
      ...props
    },
    ref
  ) => {
    const idGenerado = useId();
    const selectId = idProp || idGenerado;
    const errorId = `${selectId}-error`;
    const ayudaId = `${selectId}-ayuda`;

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
          <label htmlFor={selectId} className="form-label">
            {etiqueta}
            {requerido && <span className="required" aria-hidden="true">*</span>}
          </label>
        )}
        <select
          ref={ref}
          id={selectId}
          disabled={disabled}
          required={requerido}
          aria-invalid={tieneError ? "true" : undefined}
          aria-describedby={descripciones || undefined}
          className={`kc-select ${tieneError ? "is-error" : ""} ${className}`.trim()}
          {...props}
        >
          {opciones
            ? opciones.map((op) => (
                <option key={op.valor} value={op.valor} disabled={op.disabled}>
                  {op.etiqueta}
                </option>
              ))
            : children}
        </select>
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

Select.displayName = "Select";
