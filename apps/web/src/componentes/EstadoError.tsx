/**
 * EstadoError.tsx — Tarjeta de Error Accionable con Traza e Integración HTTP
 *
 * Implementa el ticket [KC-ADM-B3-06] (Épica EAD6 / ADM-G08 / §18.18):
 * 1. Captura y mapeo visual consistente de errores HTTP (503, 403, 404) y errores de red.
 * 2. Visualización obligatoria del identificador de traza X-Trace-Id para auditoría.
 * 3. Botón de acción interactivo de reintento (refetch).
 * 4. Accesibilidad WCAG 2.1 AA: role="alert", foco visible y contraste adecuado.
 * 5. Uso estricto de tokens de diseño KalliCode (tokens.css).
 */

import React from "react";
import { useTranslation } from "react-i18next";
import { ApiError } from "../api/clienteApi";
import { Boton } from "./Boton";

export interface EstadoErrorProps extends React.HTMLAttributes<HTMLDivElement> {
  error?: Error | ApiError | unknown | string | null;
  titulo?: string;
  mensaje?: string;
  codigo?: string;
  status?: number;
  traceId?: string;
  alReintentar?: () => void;
  textoBotonReintento?: string;
  reintentando?: boolean;
  accionSecundaria?: React.ReactNode;
  compacto?: boolean;
  dataTestIdTrace?: string;
  "data-testid"?: string;
}

export const EstadoError: React.FC<EstadoErrorProps> = ({
  error,
  titulo: tituloProp,
  mensaje: mensajeProp,
  codigo: codigoProp,
  status: statusProp,
  traceId: traceIdProp,
  alReintentar,
  textoBotonReintento,
  reintentando = false,
  accionSecundaria,
  compacto = false,
  className = "",
  style,
  dataTestIdTrace,
  "data-testid": dataTestId = "estado-error",
  ...props
}) => {
  const { t } = useTranslation();
  const textoBotonReintentoEfectivo = textoBotonReintento ?? t("common.actions.retry");
  // 1. Extracción de metadatos del error
  let errorStatus = statusProp;
  let errorCodigo = codigoProp;
  let errorMensaje = mensajeProp;
  let errorTraceId = traceIdProp;

  if (error instanceof ApiError) {
    errorStatus = errorStatus ?? error.status;
    errorCodigo = errorCodigo ?? error.codigo;
    errorMensaje = errorMensaje ?? error.message;
    errorTraceId =
      errorTraceId ??
      error.traceId ??
      ((error.detalle as Record<string, unknown>)?.trace_id as string) ??
      ((error.detalle as Record<string, unknown>)?.traceId as string);
  } else if (error && typeof error === "object") {
    const errObj = error as Record<string, unknown>;
    errorStatus = errorStatus ?? (typeof errObj.status === "number" ? errObj.status : undefined);
    errorCodigo =
      errorCodigo ??
      (typeof errObj.codigo === "string"
        ? errObj.codigo
        : typeof errObj.code === "string"
        ? errObj.code
        : undefined);
    errorMensaje =
      errorMensaje ??
      (typeof errObj.message === "string"
        ? errObj.message
        : typeof errObj.mensaje === "string"
        ? errObj.mensaje
        : undefined);
    errorTraceId =
      errorTraceId ??
      (typeof errObj.traceId === "string"
        ? errObj.traceId
        : typeof errObj.trace_id === "string"
        ? errObj.trace_id
        : undefined);
  } else if (typeof error === "string") {
    errorMensaje = errorMensaje ?? error;
  }

  // 2. Mapeo semántico de errores conocidos
  let tituloFinal = tituloProp;
  let mensajeFinal = errorMensaje;
  let icono = "⚠️";

  const codigoMayus = (errorCodigo || "").toUpperCase();

  if (errorStatus === 503 || codigoMayus === "AGREGADO_NO_DISPONIBLE") {
    tituloFinal = tituloFinal ?? t("common.errors.http503.title");
    mensajeFinal = errorMensaje ?? t("common.errors.http503.message");
    icono = "⏳";
  } else if (errorStatus === 403 || codigoMayus === "ROL_STAFF_INSUFICIENTE") {
    tituloFinal = tituloFinal ?? t("common.errors.http403.title");
    mensajeFinal = errorMensaje ?? t("common.errors.http403.message");
    icono = "🚫";
  } else if (errorStatus === 404 || codigoMayus === "NO_ENCONTRADO") {
    tituloFinal = tituloFinal ?? t("common.errors.http404.title");
    mensajeFinal = errorMensaje ?? t("common.errors.http404.message");
    icono = "🔍";
  } else if (
    errorStatus === 0 ||
    codigoMayus === "ERROR_RED" ||
    (errorMensaje && errorMensaje.toLowerCase().includes("network"))
  ) {
    tituloFinal = tituloFinal ?? t("common.errors.network.title");
    mensajeFinal = errorMensaje ?? t("common.errors.network.message");
    icono = "📡";
  } else {
    tituloFinal = tituloFinal ?? t("common.errors.generic.title");
    mensajeFinal = mensajeFinal ?? t("common.errors.generic.message");
  }

  return (
    <div
      role="alert"
      data-testid={dataTestId}
      className={`kc-estado-error card ${className}`.trim()}
      style={{
        backgroundColor: "var(--surface, #1e293b)",
        border: "var(--border-width, 1px) solid var(--border, #334155)",
        borderLeft: "4px solid var(--error, #ef4444)",
        borderRadius: "var(--radius-lg, 12px)",
        padding: compacto ? "var(--space-3, 12px) var(--space-4, 16px)" : "var(--space-6, 24px)",
        maxWidth: compacto ? "100%" : "640px",
        margin: compacto ? 0 : "var(--space-4, 16px) auto",
        display: "flex",
        flexDirection: "column",
        gap: "var(--space-3, 12px)",
        boxSizing: "border-box",
        ...style,
      }}
      {...props}
    >
      <div style={{ display: "flex", alignItems: "center", gap: "var(--space-3, 12px)" }}>
        <span style={{ fontSize: compacto ? "1.25rem" : "1.75rem", lineHeight: 1 }} aria-hidden="true">
          {icono}
        </span>
        <h2
          style={{
            fontSize: compacto ? "var(--text-base, 14px)" : "var(--text-lg, 16px)",
            fontWeight: "var(--font-semibold, 600)",
            color: "var(--error, #ef4444)",
            margin: 0,
          }}
        >
          {tituloFinal}
        </h2>
      </div>

      <p
        style={{
          fontSize: "var(--text-sm, 13px)",
          color: "var(--text, #f8fafc)",
          margin: 0,
          lineHeight: "var(--leading-normal, 1.5)",
        }}
      >
        {mensajeFinal}
      </p>

      {/* Identificador de traza visible para auditoría y observabilidad */}
      {errorTraceId && (
        <div
          data-testid={dataTestIdTrace}
          style={{
            display: "inline-flex",
            alignItems: "center",
            gap: "var(--space-2, 8px)",
            fontFamily: "var(--font-mono, monospace)",
            fontSize: "var(--text-xs, 11px)",
            color: "var(--muted, #94a3b8)",
            backgroundColor: "var(--surface2, #334155)",
            padding: "var(--space-1, 4px) var(--space-2, 8px)",
            borderRadius: "var(--radius-sm, 4px)",
            width: "fit-content",
          }}
        >
          <span>{t("common.errors.traceId")}</span>
          <strong data-testid="error-trace-id" style={{ color: "var(--text, #f8fafc)" }}>
            {errorTraceId}
          </strong>
        </div>
      )}

      {/* Acciones de recuperación: Reintento y secundaria */}
      {(alReintentar || accionSecundaria) && (
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: "var(--space-3, 12px)",
            marginTop: "var(--space-2, 8px)",
            flexWrap: "wrap",
          }}
        >
          {alReintentar && (
            <Boton
              variante="primary"
              onClick={alReintentar}
              disabled={reintentando}
              data-testid="btn-reintentar"
            >
              {reintentando ? t("common.actions.retrying") : textoBotonReintentoEfectivo}
            </Boton>
          )}
          {accionSecundaria}
        </div>
      )}
    </div>
  );
};
