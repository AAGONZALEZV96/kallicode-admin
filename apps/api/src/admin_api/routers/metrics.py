"""Endpoint de métricas Prometheus protegido para red privada (KC-ADM-B6-08)."""

from __future__ import annotations

import hmac
import ipaddress

from fastapi import APIRouter, Request, Response, status

from ..errors import rol_staff_insuficiente
from ..metrics import renderizar_metricas_prometheus
from ..settings import AdminSettings, get_admin_settings

router = APIRouter(tags=["Observabilidad"])


def _resolver_ip_cliente(request: Request, settings: AdminSettings) -> str:
    peer = request.client.host if request.client else ""
    xff = request.headers.get("x-forwarded-for", "").strip()

    if peer == "testclient" and settings.env in ("local", "test"):
        if xff:
            return xff.split(",")[0].strip()
        return "127.0.0.1"

    try:
        peer_ip = ipaddress.ip_address(peer)
    except ValueError:
        return ""

    if xff and any(peer_ip in net for net in settings.redes_proxies_confiables):
        return xff.split(",")[0].strip()
    return str(peer_ip)


def _validar_acceso_red_privada(request: Request, settings: AdminSettings) -> None:
    if not settings.metrics_enabled:
        raise rol_staff_insuficiente("El endpoint de métricas está deshabilitado.")

    ip_str = _resolver_ip_cliente(request, settings)
    try:
        ip_obj = ipaddress.ip_address(ip_str)
    except ValueError as exc:
        raise rol_staff_insuficiente(
            "El scraping de métricas solo se permite desde red privada."
        ) from exc

    if not any(ip_obj in red for red in settings.redes_metricas_permitidas):
        raise rol_staff_insuficiente(
            "El scraping de métricas solo se permite desde red privada."
        )

    token_config = (settings.metrics_bearer_token or "").strip()
    if token_config:
        auth = request.headers.get("authorization", "")
        prefijo, _, token_recibido = auth.partition(" ")
        if prefijo.lower() != "bearer" or not hmac.compare_digest(
            token_recibido.strip(), token_config
        ):
            raise rol_staff_insuficiente("Credencial de scraping interno inválida.")


@router.get(
    "/admin/v1/metrics",
    include_in_schema=False,
    summary="Métricas Prometheus de observabilidad (/admin/v1)",
)
@router.get(
    "/metrics",
    include_in_schema=False,
    summary="Métricas Prometheus de observabilidad",
)
async def metrics(request: Request) -> Response:
    """Expone métricas Prometheus exclusivamente dentro de la red privada."""
    s = get_admin_settings()
    _validar_acceso_red_privada(request, s)
    cuerpo, content_type = renderizar_metricas_prometheus()
    return Response(
        content=cuerpo,
        status_code=status.HTTP_200_OK,
        media_type=content_type,
    )


__all__ = ["router"]
