/**
 * Tipos canónicos del Contrato de Telemetría del Pipeline de Producción (§17.13 – §17.16).
 *
 * Coincidencia estricta 100% con docs/contrato-telemetria-e2.md y OpenAPI /admin/v1/ops.
 *
 * Principio: E6 consume telemetría del Equipo 2 y nunca interpreta ni duplica lógica del pipeline.
 */

export type EtapaPipeline =
  | "triage"
  | "design"
  | "build"
  | "qa"
  | "security"
  | "deploy";

export type VentanaAgentes = "5m" | "1h" | "24h";

export type VentanaModelos = "1h" | "24h" | "7d" | "30d";

export type EstadoCola = "normal" | "atencion" | "critico";

export type TierModelo = "flash" | "pro" | "fable";

// -----------------------------------------------------------------------------
// §17.13 Latido de Agente (Heartbeat)
// -----------------------------------------------------------------------------

export interface HeartbeatPayload {
  agente_id: string;
  linea: string;
  etapa: EtapaPipeline | string;
  job_id: string | null;
  ventana_s: number;
  timestamp: string;
}

export interface HeartbeatResponse {
  recibido: boolean;
  agente_id: string;
  registrado_en: string;
}

// -----------------------------------------------------------------------------
// §17.14 Estado Agregado de Agentes y Líneas
// -----------------------------------------------------------------------------

export interface EtapaMetrica {
  etapa: string;
  agentes_total: number;
  agentes_ocupados: number;
  agentes_caidos: number;
  en_cola?: number;
  latencia_p95_ms?: number;
  errores?: number;
}

export interface LineasMetrica {
  activas: number;
  mantenimiento: number;
  libres: number;
}

export interface AlertaOperativa {
  tipo: string;
  etapa?: string;
  valor: number;
}

export interface EstadoTelemetria {
  disponible: boolean;
  antiguedad_s: number | null;
  desde: string | null;
}

export interface AgentsTelemetryResponse {
  ventana: VentanaAgentes | string;
  telemetria: EstadoTelemetria;
  etapas: EtapaMetrica[] | null;
  lineas: LineasMetrica | null;
  alertas: AlertaOperativa[];
}

// -----------------------------------------------------------------------------
// §17.15 Estado y Salud de Colas de Mensajería
// -----------------------------------------------------------------------------

export interface ColaMetrica {
  nombre: string;
  profundidad: number;
  antiguedad_max_s: number;
  no_confirmados?: number;
  dlq?: number;
  umbral_atencion_s?: number;
  estado: EstadoCola;
}

export interface ResumenColas {
  criticas: number;
  atencion: number;
  pendientes_total: number;
  fallidos_total: number;
}

export interface QueuesTelemetryResponse {
  colas: ColaMetrica[];
  resumen: ResumenColas;
}

// -----------------------------------------------------------------------------
// §17.16 Proveedores LLM, Modelos y Escalados
// -----------------------------------------------------------------------------

export interface ProveedorMetrica {
  proveedor: string;
  modelo: string;
  tier: TierModelo;
  disponibilidad_pct: number;
  latencia_p50_ms?: number;
  latencia_p95_ms: number;
  tasa_error_pct: number;
}

export interface EscaladosMetrica {
  flash_a_pro: number;
  pro_a_fable: number;
  a_humano: number;
}

export interface ProvidersTelemetryResponse {
  ventana: VentanaModelos | string;
  proveedores: ProveedorMetrica[];
  modelos: ProveedorMetrica[];
  escalados: EscaladosMetrica;
  tokens_por_tier?: Record<string, number>;
  coste_por_tier?: Record<string, number>;
  degradados: string[] | null;
  comparacion: { escalados: EscaladosMetrica } | null;
}
