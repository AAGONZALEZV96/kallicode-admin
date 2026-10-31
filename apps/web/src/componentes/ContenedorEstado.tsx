/**
 * ContenedorEstado.tsx — Orquestador Declarativo de Estados de Interfaz
 *
 * Implementa el ticket [KC-ADM-B3-06] (Épica EAD6 / ADM-G08 / §18.18):
 * Encapsula de forma declarativa la transición entre Carga (Skeleton), Error (con traza)
 * y Estado Vacío (con acción sugerida), simplificando la lógica en todas las pantallas.
 */

import React from "react";
import { EstadoCarga, TipoEstadoCarga } from "./EstadoCarga";
import { EstadoError } from "./EstadoError";
import { EstadoVacio } from "./EstadoVacio";

export interface ContenedorEstadoProps {
  cargando: boolean;
  error?: Error | unknown | string | null;
  vacio?: boolean;
  tipoCarga?: TipoEstadoCarga;
  filasCarga?: number;
  columnasCarga?: number;
  tarjetasCarga?: number;
  mensajeCarga?: string;
  tiempoLimiteMs?: number;
  alExpirarTiempoLimite?: () => void;
  alReintentar?: () => void;
  textoBotonReintento?: string;
  reintentando?: boolean;
  tituloError?: string;
  mensajeError?: string;
  accionSecundariaError?: React.ReactNode;
  tituloVacio?: string;
  descripcionVacio?: string;
  iconoVacio?: React.ReactNode;
  alAccionarVacio?: () => void;
  textoAccionVacio?: string;
  accionVacio?: React.ReactNode;
  compacto?: boolean;
  children: React.ReactNode;
}

export const ContenedorEstado: React.FC<ContenedorEstadoProps> = ({
  cargando,
  error,
  vacio = false,
  tipoCarga = "generico",
  filasCarga,
  columnasCarga,
  tarjetasCarga,
  mensajeCarga,
  tiempoLimiteMs,
  alExpirarTiempoLimite,
  alReintentar,
  textoBotonReintento,
  reintentando,
  tituloError,
  mensajeError,
  accionSecundariaError,
  tituloVacio,
  descripcionVacio,
  iconoVacio,
  alAccionarVacio,
  textoAccionVacio,
  accionVacio,
  compacto = false,
  children,
}) => {
  // 1. Estado de Carga
  if (cargando) {
    return (
      <EstadoCarga
        tipo={tipoCarga}
        filas={filasCarga}
        columnas={columnasCarga}
        tarjetas={tarjetasCarga}
        mensaje={mensajeCarga}
        tiempoLimiteMs={tiempoLimiteMs}
        alExpirarTiempoLimite={alExpirarTiempoLimite}
      />
    );
  }

  // 2. Estado de Error
  if (error) {
    return (
      <EstadoError
        error={error}
        titulo={tituloError}
        mensaje={mensajeError}
        alReintentar={alReintentar}
        textoBotonReintento={textoBotonReintento}
        reintentando={reintentando}
        accionSecundaria={accionSecundariaError}
        compacto={compacto}
      />
    );
  }

  // 3. Estado Vacío
  if (vacio) {
    return (
      <EstadoVacio
        titulo={tituloVacio}
        descripcion={descripcionVacio}
        icono={iconoVacio}
        alAccionar={alAccionarVacio}
        textoAccion={textoAccionVacio}
        accion={accionVacio}
        compacto={compacto}
      />
    );
  }

  // 4. Contenido Real
  return <>{children}</>;
};
