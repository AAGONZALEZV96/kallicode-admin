import React from "react";
import { Boton } from "./Boton";
import { Badge } from "./Badge";
import { Select } from "./Select";
import type { UseLiveRefreshResultado } from "../hooks/useLiveRefresh";

export interface ControlesLiveRefreshProps {
  hook: UseLiveRefreshResultado;
  mostrarSelector?: boolean;
  mostrarManual?: boolean;
  className?: string;
}

const OPCIONES_FRECUENCIA = [
  { valor: 15_000, etiqueta: "Cada 15 segundos (Recomendado)" },
  { valor: 30_000, etiqueta: "Cada 30 segundos" },
  { valor: 60_000, etiqueta: "Cada 60 segundos" },
  { valor: 0, etiqueta: "Pausado / Manual" },
];

export const ControlesLiveRefresh: React.FC<ControlesLiveRefreshProps> = ({
  hook,
  mostrarSelector = true,
  mostrarManual = true,
  className = "",
}) => {
  const {
    activo,
    alternarActivo,
    intervaloMs,
    setIntervaloMs,
    refrescando,
    ultimaActualizacion,
    segundosDesdeUltimaActualizacion,
    tiempoRestanteSegundos,
    refrescarAhora,
    pausadoPorVisibilidad,
  } = hook;

  const enVivo = activo && !pausadoPorVisibilidad && intervaloMs > 0;

  const textoFrescura = (() => {
    if (!ultimaActualizacion) {
      return "Pendiente de actualización";
    }
    if (segundosDesdeUltimaActualizacion < 3) {
      return "Actualizado ahora";
    }
    return `Última: hace ${segundosDesdeUltimaActualizacion}s`;
  })();

  const textoEstado = (() => {
    if (refrescando) {
      return "Actualizando...";
    }
    if (pausadoPorVisibilidad) {
      return "En pausa por pestaña oculta";
    }
    if (enVivo && tiempoRestanteSegundos > 0) {
      return `Próximo en ${tiempoRestanteSegundos}s · ${textoFrescura}`;
    }
    return textoFrescura;
  })();

  return (
    <div
      className={`controles-live-refresh ${className}`.trim()}
      style={{
        display: "flex",
        alignItems: "center",
        flexWrap: "wrap",
        gap: "12px",
        padding: "8px 12px",
        backgroundColor: "var(--surface)",
        border: "1px solid var(--border)",
        borderRadius: "var(--radius-md)",
      }}
      role="region"
      aria-label="Controles de refresco en vivo"
    >
      {/* Indicador visual de actividad */}
      <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
        {enVivo ? (
          <Badge variante="good" punto data-testid="live-badge-activo">
            <span style={{ fontWeight: 600 }}>EN VIVO</span>
          </Badge>
        ) : pausadoPorVisibilidad ? (
          <Badge variante="warn" punto data-testid="live-badge-segundo-plano">
            <span style={{ fontWeight: 600 }}>PAUSADO (Pestaña oculta)</span>
          </Badge>
        ) : (
          <Badge variante="mut" data-testid="live-badge-pausado">
            <span>PAUSADO</span>
          </Badge>
        )}
      </div>

      {/* Botón Play / Pausa */}
      <Boton
        tamano="sm"
        variante={enVivo ? "secondary" : "primary"}
        onClick={alternarActivo}
        aria-label={enVivo ? "Pausar refresco automático" : "Reanudar refresco automático"}
        data-testid="live-btn-toggle"
      >
        <span style={{ display: "inline-flex", alignItems: "center", gap: "6px" }}>
          {enVivo ? (
            <svg width="12" height="12" viewBox="0 0 12 12" fill="currentColor" aria-hidden="true">
              <rect x="2" y="2" width="3" height="8" rx="0.5" />
              <rect x="7" y="2" width="3" height="8" rx="0.5" />
            </svg>
          ) : (
            <svg width="12" height="12" viewBox="0 0 12 12" fill="currentColor" aria-hidden="true">
              <polygon points="3,2 10,6 3,10" />
            </svg>
          )}
          <span>{enVivo ? "Pausar" : "Reanudar"}</span>
        </span>
      </Boton>

      {/* Selector de frecuencia */}
      {mostrarSelector && (
        <div style={{ display: "flex", alignItems: "center", minWidth: "200px" }}>
          <Select
            value={activo ? intervaloMs : 0}
            onChange={(e) => {
              const nuevoMs = Number(e.target.value);
              if (nuevoMs === 0) {
                setIntervaloMs(0);
              } else {
                hook.setPausado(false);
                setIntervaloMs(nuevoMs);
              }
            }}
            opciones={OPCIONES_FRECUENCIA}
            aria-label="Frecuencia de auto-refresco"
            data-testid="live-select-intervalo"
            style={{ padding: "4px 8px", fontSize: "12px" }}
          />
        </div>
      )}

      {/* Botón de Refresco Manual */}
      {mostrarManual && (
        <Boton
          tamano="sm"
          variante="ghost"
          cargando={refrescando}
          onClick={() => void refrescarAhora()}
          aria-label="Refrescar datos manualmente ahora"
          data-testid="live-btn-manual"
        >
          <span style={{ display: "inline-flex", alignItems: "center", gap: "6px" }}>
            <svg
              width="13"
              height="13"
              viewBox="0 0 16 16"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.6"
              strokeLinecap="round"
              strokeLinejoin="round"
              aria-hidden="true"
            >
              <path d="M13.5 8a5.5 5.5 0 1 1-1.35-3.6" />
              <polyline points="13.5 2.5 13.5 5.5 10.5 5.5" />
            </svg>
            <span>Refrescar ahora</span>
          </span>
        </Boton>
      )}

      {/* Indicador de próximo refresco, carga y frescura */}
      <span
        style={{
          marginLeft: "auto",
          fontSize: "12px",
          color: "var(--muted)",
          fontVariantNumeric: "tabular-nums",
        }}
        role="status"
        aria-live="polite"
        data-testid="live-indicador-frescura"
      >
        {textoEstado}
      </span>
    </div>
  );
};
