"""Configuración de la API de administración.

Extiende la configuración de plataforma (`kallicode_core.config`) en lugar de
duplicarla: de ahí salen la URL de base de datos del portal, Redis, el blob y
las claves RSA. Aquí solo vive lo que es propio de la consola.

Dos cadenas de conexión distintas y separadas a propósito (§18 y §3.7.1):

  · `database_url_app`  rol kallicode_admin_app  — escribe en el esquema admin
  · `database_url_ro`   rol kallicode_admin_ro   — lectura analítica cross-tenant

Mezclarlas anularía el modelo de acceso: el rol de escritura no debe poder leer
datos de cliente y el de lectura no debe poder escribir nada. El arranque falla
si alguna de las dos apunta a un superusuario (véase `verificar_arranque`).
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class AdminSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="KC_ADMIN_", env_file=".env", extra="ignore")

    # --- entorno ---
    env: str = "local"  # local | dev | staging | prod
    app_version: str = "0.1.0"

    # --- base de datos: dos roles, dos pools (§18) ---
    database_url_app: str = (
        "postgresql+asyncpg://kallicode_admin_app:dev@localhost:5432/kallicode"
    )
    database_url_ro: str = (
        "postgresql+asyncpg://kallicode_admin_ro:dev@localhost:5432/kallicode"
    )
    pool_size_app: int = 5
    pool_size_ro: int = 10  # pool analítico: consultas de agregación
    statement_timeout_ms_app: int = 5_000
    statement_timeout_ms_ro: int = 30_000  # los agregados tardan más y no bloquean al portal

    # --- identidad del personal (§18.1 – §18.8) ---
    staff_email_domains: str = "kallicode.com"  # lista separada por comas
    staff_access_token_ttl_min: int = 15  # más corto que el de cliente (30)
    staff_refresh_token_ttl_h: int = 8  # más corto que el de cliente (30 días)
    staff_idle_timeout_min: int = 30  # inactividad: obliga a repetir el 2FA
    mfa_challenge_ttl_s: int = 300
    mfa_max_attempts: int = 3
    mfa_totp_window: int = 1  # un intervalo antes y después, no más
    mfa_recovery_codes: int = 8
    login_max_attempts: int = 5
    login_lock_window_s: int = 900
    password_reset_ttl_min: int = 30
    password_reset_max_per_hour: int = 3
    invitation_ttl_days: int = 7
    password_history_size: int = 3

    # --- emisor y audiencia propios: un token de personal no sirve en /api/v1 ---
    jwt_issuer: str = "kallicode-admin"
    jwt_audience: str = "admin-v1"

    # --- concesiones de acceso (§18.13) ---
    grant_default_minutes: int = 240
    grant_min_minutes: int = 15
    grant_max_minutes: int = 480
    grant_code_max_minutes: int = 60  # alcance contenido_codigo
    grant_max_concurrent: int = 3
    grant_reason_min_len: int = 20
    grant_reason_max_len: int = 500

    # --- límite RL-4 propio (§3.7.1) ---
    rate_limit_staff: int = 300  # req/min por empleado
    rate_limit_global: int = 3_000  # req/min para todo el personal
    rate_limit_live: int = 60  # refresco en vivo de operaciones

    # --- agregados de negocio (§18.16) ---
    aggregate_max_age_s: int = 21_600  # 6 h: por encima se avisa
    aggregate_stale_s: int = 86_400  # 24 h: se considera no disponible
    refresh_interval_s: int = 900

    # --- contrato de telemetría del pipeline (§17.14 – §17.16) ---
    telemetry_base_url: str = "http://localhost:8001/internal/v1"
    telemetry_timeout_s: int = 5
    telemetry_max_age_s: int = 900  # 15 min: por encima, no disponible

    # --- informes (§18.22, §18.23) ---
    report_container: str = "informes-admin"
    report_url_ttl_min: int = 15
    report_retention_days: int = 30
    report_max_months: int = 24
    export_chunk_events: int = 500_000

    # --- niveles de servicio (§18.27) ---
    sla_min_cases: int = 5  # por debajo no se publica porcentaje

    # --- red: la consola no se publica nunca (§18.31, ADM-G10) ---
    allowed_hosts: str = "localhost,admin.internal.kallicode.com"
    trusted_proxies: str = "10.0.0.0/8"

    @field_validator("database_url_app", "database_url_ro")
    @classmethod
    def _sin_superusuario(cls, v: str) -> str:
        # Barrera temprana: el defecto BE-F01 del backend fue que la cadena por
        # defecto apuntaba a `postgres`, superusuario que ignora RLS siempre.
        if "://postgres:" in v or "://postgres@" in v:
            raise ValueError(
                "la consola no puede conectarse como superusuario: usa "
                "kallicode_admin_app o kallicode_admin_ro"
            )
        return v

    @property
    def dominios_permitidos(self) -> tuple[str, ...]:
        return tuple(
            d.strip().lower() for d in self.staff_email_domains.split(",") if d.strip()
        )

    @property
    def hosts_permitidos(self) -> list[str]:
        return [h.strip() for h in self.allowed_hosts.split(",") if h.strip()]


@lru_cache
def get_admin_settings() -> AdminSettings:
    return AdminSettings()
