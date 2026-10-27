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
    refrescarAhora,
    enPausaPorVisibilidad,
  } = hook;

  // Formatear texto de frescura
  const textoFrescura = (() => {
    if (!ultimaActualizacion) {
      return "Pendiente de actualización";
    }
    if (segundosDesdeUltimaActualizacion < 3) {
      return "Actualizado ahora";
    }
    return `Última actualización: hace ${segundosDesdeUltimaActualizacion}s`;
  })();

  // Opciones de selector de frecuencia
  const opcionesFrecuencia = [
    { valor: 10_000, etiqueta: "Cada 10 segundos" },
    { valor: 15_000, etiqueta: "Cada 15 segundos (Recomendado)" },
    { valor: 30_000, etiqueta: "Cada 30 segundos" },
    { valor: 60_000, etiqueta: "Cada 60 segundos" },
    { valor: 0, etiqueta: "Desactivado (Manual)" },
  ];

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
        {activo && !enPausaPorVisibilidad && intervaloMs > 0 ? (
          <Badge variante="good" punto data-testid="live-badge-activo">
            <span style={{ fontWeight: 600 }}>EN VIVO</span>
          </Badge>
        ) : enPausaPorVisibilidad ? (
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
        variante={activo ? "secondary" : "primary"}
        onClick={alternarActivo}
        aria-label={activo ? "Pausar refresco automático" : "Reanudar refresco automático"}
        data-testid="live-btn-toggle"
      >
        {activo ? "⏸ Pausar" : "▶ Reanudar"}
      </Boton>

      {/* Selector de frecuencia */}
      {mostrarSelector && (
        <div style={{ display: "flex", alignItems: "center", minWidth: "180px" }}>
          <Select
            tamano-sm="true"
            value={intervaloMs}
            onChange={(e) => setIntervaloMs(Number(e.target.value))}
            opciones={opcionesFrecuencia}
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
          ↻ Refrescar ahora
        </Boton>
      )}

      {/* Indicador de frescura */}
      <span
        style={{
          marginLeft: "auto",
          fontSize: "12px",
          color: "var(--muted)",
          fontVariantNumeric: "tabular-nums",
        }}
        data-testid="live-indicador-frescura"
      >
        {textoFrescura}
      </span>
    </div>
  );
};
