"""Esquemas Pydantic para la consola de operaciones y observabilidad SLA (§18.27 - §18.28)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class _BaseOps(BaseModel):
    """Base estricta sin propiedades extra indocumentadas."""

    model_config = ConfigDict(extra="forbid")


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
