import React from "react";
import { useTranslation } from "react-i18next";
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
  const { t } = useTranslation();
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

  const opcionesFrecuencia = [
    { valor: 15_000, etiqueta: t("components.liveRefresh.frequencies.s15") },
    { valor: 30_000, etiqueta: t("components.liveRefresh.frequencies.s30") },
    { valor: 60_000, etiqueta: t("components.liveRefresh.frequencies.s60") },
    { valor: 0, etiqueta: t("components.liveRefresh.frequencies.manual") },
  ];

  const enVivo = activo && !pausadoPorVisibilidad && intervaloMs > 0;

  const textoFrescura = (() => {
    if (!ultimaActualizacion) {
      return t("components.liveRefresh.pending");
    }
    if (segundosDesdeUltimaActualizacion < 3) {
      return t("components.liveRefresh.updatedNow");
    }
    return t("components.liveRefresh.lastAgo", { seconds: segundosDesdeUltimaActualizacion });
  })();

  const textoEstado = (() => {
    if (refrescando) {
      return t("components.liveRefresh.updating");
    }
    if (pausadoPorVisibilidad) {
      return t("components.liveRefresh.pausedByVisibility");
    }
    if (enVivo && tiempoRestanteSegundos > 0) {
      return t("components.liveRefresh.nextIn", {
        seconds: tiempoRestanteSegundos,
        freshness: textoFrescura,
      });
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
      aria-label={t("components.liveRefresh.regionLabel")}
    >
      {/* Indicador visual de actividad */}
      <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
        {enVivo ? (
          <Badge variante="good" punto data-testid="live-badge-activo">
            <span style={{ fontWeight: 600 }}>{t("components.liveRefresh.live")}</span>
          </Badge>
        ) : pausadoPorVisibilidad ? (
          <Badge variante="warn" punto data-testid="live-badge-segundo-plano">
            <span style={{ fontWeight: 600 }}>{t("components.liveRefresh.pausedHidden")}</span>
          </Badge>
        ) : (
          <Badge variante="mut" data-testid="live-badge-pausado">
            <span>{t("components.liveRefresh.paused")}</span>
          </Badge>
        )}
      </div>

      {/* Botón Play / Pausa */}
      <Boton
        tamano="sm"
        variante={enVivo ? "secondary" : "primary"}
        onClick={alternarActivo}
        aria-label={
          enVivo ? t("components.liveRefresh.pauseAria") : t("components.liveRefresh.resumeAria")
        }
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
          <span>{enVivo ? t("components.liveRefresh.pause") : t("components.liveRefresh.resume")}</span>
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
            opciones={opcionesFrecuencia}
            aria-label={t("components.liveRefresh.frequencyAria")}
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
          aria-label={t("components.liveRefresh.refreshNowAria")}
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
            <span>{t("components.liveRefresh.refreshNow")}</span>
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
