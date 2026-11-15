"""Esquemas Pydantic para la consola de operaciones (§18.24 - §18.28)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class _BaseOps(BaseModel):
    """Base estricta sin propiedades extra indocumentadas."""

    model_config = ConfigDict(extra="forbid")


class TelemetriaEstadoOut(_BaseOps):
    """Metadatos de disponibilidad y frescura de la señal de telemetría (§18.24)."""

    disponible: bool
    antiguedad_s: int | None = Field(default=None, ge=0)
    desde: str | None = None


class EtapaAgentesOut(_BaseOps):
    """Métricas agregadas de agentes y ejecución para una etapa del pipeline (§18.24)."""

    etapa: str
    agentes_total: int | None = Field(default=None, ge=0)
    agentes_ocupados: int | None = Field(default=None, ge=0)
    agentes_caidos: int | None = Field(default=None, ge=0)
    jobs_completados: int | None = Field(default=None, ge=0)
    duracion_p95_s: float | None = Field(default=None, ge=0.0)
    # Campos complementarios emitidos por §17.14 y consumidores legados
    activos: int | None = Field(default=None, ge=0)
    en_cola: int | None = Field(default=None, ge=0)
    latencia_p95_ms: float | None = Field(default=None, ge=0.0)
    errores: int | None = Field(default=None, ge=0)


class LineasProduccionOut(_BaseOps):
    """Ocupación de líneas de producción en plataforma."""

    activas: int = Field(ge=0)
    mantenimiento: int = Field(ge=0)
    libres: int = Field(ge=0)


class AlertaOpsOut(_BaseOps):
    """Alerta operativa derivada de umbrales de etapa o líneas."""

    tipo: str
    etapa: str | None = None
    linea: str | None = None
    mensaje: str | None = None
    valor: int | float
    umbral: int | float | None = None


class OpsAgentsResponse(_BaseOps):
    """Respuesta canónica de GET /admin/v1/ops/agents (§18.24)."""

    ventana: str
    telemetria: TelemetriaEstadoOut
    etapas: list[EtapaAgentesOut] | None = None
    lineas: LineasProduccionOut | None = None
    alertas: list[AlertaOpsOut]


class ColaPipelineOut(_BaseOps):
    """Estado de profundidad, antigüedad y errores de una cola del pipeline (§18.25)."""

    nombre: str
    pendientes: int = Field(ge=0)
    reclamados: int = Field(ge=0)
    fallidos: int = Field(ge=0)
    profundidad: int = Field(ge=0)
    no_confirmados: int = Field(ge=0)
    dlq: int = Field(ge=0)
    antiguedad_max_s: int = Field(ge=0)
    umbral_atencion_s: int = Field(ge=0)
    estado: Literal["normal", "atencion", "critico"]


class ColasResumenOut(_BaseOps):
    """Resumen consolidado de salud de las colas monitorizadas."""

    criticas: int = Field(ge=0)
    atencion: int = Field(ge=0)
    pendientes_total: int = Field(ge=0)
    fallidos_total: int = Field(ge=0)


class OpsQueuesResponse(_BaseOps):
    """Respuesta canónica de GET /admin/v1/ops/queues (§18.25)."""

    telemetria_desde: str | None = None
    colas: list[ColaPipelineOut]
    resumen: ColasResumenOut


class ProveedorModeloOut(_BaseOps):
    """Indicadores operativos por proveedor, modelo y tier LLM (§18.26)."""

    proveedor: str
    modelo: str
    tier: Literal["flash", "pro", "fable"]
    llamadas: int = Field(default=0, ge=0)
    disponibilidad_pct: float = Field(ge=0.0, le=100.0)
    latencia_p50_ms: float | None = Field(default=None, ge=0.0)
    latencia_p95_ms: float = Field(ge=0.0)
    tasa_error_pct: float = Field(ge=0.0, le=100.0)


class EscaladosLlmOut(_BaseOps):
    """Conteo de saltos de fallback entre tiers y escalado humano."""

    flash_a_pro: int = Field(default=0, ge=0)
    pro_a_fable: int = Field(default=0, ge=0)
    a_humano: int = Field(default=0, ge=0)


class ComparacionModelosOut(_BaseOps):
    """Métricas de ventana previa cuando se solicita comparación (§18.26)."""

    periodo: str = "periodo_anterior"
    escalados: EscaladosLlmOut
    proveedores: list[ProveedorModeloOut] = Field(default_factory=list)


class OpsModelsResponse(_BaseOps):
    """Respuesta canónica de GET /admin/v1/ops/models (§18.26)."""

    ventana: str
    proveedores: list[ProveedorModeloOut]
    modelos: list[ProveedorModeloOut]
    escalados: EscaladosLlmOut
    tokens_por_tier: dict[str, int]
    coste_por_tier: dict[str, float]
    degradados: list[str] | None = None
    comparacion: ComparacionModelosOut | None = None


class SlaResumenOut(_BaseOps):
    """Totales agregados de cumplimiento SLA del ciclo consultado."""

    casos_totales: int = Field(ge=0)
    casos_evaluados: int = Field(ge=0)
    casos_dentro: int = Field(ge=0)
    casos_incumplidos: int = Field(ge=0)
    casos_en_riesgo: int = Field(ge=0)
    casos_en_curso: int = Field(ge=0)
    casos_sin_objetivo: int = Field(ge=0)
    cumplimiento_pct: float | None = Field(default=None, ge=0.0, le=100.0)
    tiempo_medio_h: float | None = Field(default=None, ge=0.0)
    p95_h: float | None = Field(default=None, ge=0.0)
    # Alias retrocompatibles para consumidores existentes
    evaluados: int = Field(ge=0)
    incumplidos: int = Field(ge=0)
    en_riesgo: int = Field(ge=0)
    sin_objetivo: int = Field(ge=0)


class SlaPlanBreakdownOut(_BaseOps):
    """Desglose de cumplimiento y latencia SLA por plan comercial."""

    plan: str
    objetivo_h: float | None = Field(default=None, ge=0.0)
    casos: int = Field(ge=0)
    casos_evaluados: int = Field(ge=0)
    cumplimiento_pct: float | None = Field(default=None, ge=0.0, le=100.0)
    tiempo_medio_h: float | None = Field(default=None, ge=0.0)
    p95_h: float | None = Field(default=None, ge=0.0)
    sin_definicion: bool = False


class SlaCaseRiskItemOut(_BaseOps):
    """Caso activo cuyo consumo computado supera el 75% del objetivo del plan."""

    job_id: str
    ticket_id: str | None = None
    tenant_id: str
    plan: str
    etapa_actual: str | None = None
    objetivo_h: float = Field(gt=0.0)
    transcurrido_h: float = Field(ge=0.0)
    bruto_h: float = Field(ge=0.0)
    porcentaje_objetivo: float = Field(ge=0.0)
    resultado: Literal["en_riesgo", "en_curso"]
    enmascarado: bool


class SlaTenantRowOut(_BaseOps):
    """Fila paginada por cliente y plan para retrocompatibilidad del resumen."""

    tenant_id: str
    razon_social: str | None = None
    plan: str | None = None
    objetivo_h: float | None = None
    casos: int = Field(ge=0)
    evaluados: int = Field(ge=0)
    incumplidos: int = Field(ge=0)
    en_riesgo: int = Field(ge=0)
    cumplimiento_pct: float | None = Field(default=None, ge=0.0, le=100.0)
    tiempo_medio_h: float | None = Field(default=None, ge=0.0)
    p95_h: float | None = Field(default=None, ge=0.0)


class SlaSummaryResponse(_BaseOps):
    """Respuesta canónica de GET /admin/v1/ops/sla (§18.27)."""

    ciclo: str
    resumen: SlaResumenOut
    por_plan: dict[str, SlaPlanBreakdownOut]
    casos_en_riesgo: list[SlaCaseRiskItemOut]
    frescura: datetime
    sin_definicion: list[str]
    items: list[SlaTenantRowOut]
    total: int = Field(ge=0)
    page: int = Field(ge=1)
    page_size: int = Field(ge=1)
    pages: int = Field(ge=0)


class SlaClockSegmentOut(_BaseOps):
    """Tramo cronológico del reloj de SLA de un caso (§18.28)."""

    inicio: datetime
    fin: datetime | None = None
    duracion_h: float = Field(ge=0.0)
    horas: float = Field(ge=0.0)
    computa: bool
    etapa: str | None = None
    causa_pausa: str | None = None


class SlaCaseDetailResponse(_BaseOps):
    """Respuesta canónica de GET /admin/v1/ops/sla/cases/{job_id} (§18.28)."""

    job_id: str
    ticket_id: str | None = None
    ticket_numero: str | None = None
    razon_social: str | None = None
    tenant_id: str
    plan: str | None = None
    etapa_actual: str | None = None
    objetivo_h: float | None = Field(default=None, ge=0.0)
    bruto_h: float = Field(ge=0.0)
    transcurrido_h: float = Field(ge=0.0)
    pausa_total_h: float = Field(ge=0.0)
    resultado: Literal["dentro", "incumplido", "en_curso", "en_riesgo", "sin_objetivo"]
    tramos: list[SlaClockSegmentOut]
    reglas_aplicadas: list[str]
    iniciado_en: datetime | None = None
    terminado_en: datetime | None = None
    calculado_en: datetime | None = None
    enmascarado: list[str]
