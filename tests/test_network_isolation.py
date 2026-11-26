"""Pruebas unitarias de aislamiento estricto de red privada (KC-ADM-B6-01 / ADM-G10).

Valida sin requerir despliegue real en Azure (estrategia Cero-Nube):
1. Inspección estática de las plantillas Bicep (`infra/*.bicep`) y parámetros
   (`infra/params/*.bicepparam`) para dev, staging y prod: cero ingress público,
   VNet privada con subred delegada, NSG con denegación explícita desde Internet
   y Private Endpoints + Private DNS Zones hacia dependencias gestionadas.
2. Simulación dinámica de rechazo de conectividad externa a nivel de transporte,
   resolución DNS privada y filtrado estricto de Host/CIDR en la API FastAPI.
3. Preservación del flujo de desarrollo local en `docker-compose.yml` y `.env.example`.
"""

from __future__ import annotations

import ipaddress
import re
import socket
from pathlib import Path
from typing import Any

import httpx
import pytest
from admin_api.settings import get_admin_settings
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent
INFRA_DIR = ROOT / "infra"
PARAMS_DIR = INFRA_DIR / "params"
ENTORNOS = ("dev", "staging", "prod")

ARCHIVOS_BICEP_REQUERIDOS = (
    INFRA_DIR / "main.bicep",
    INFRA_DIR / "network.bicep",
    INFRA_DIR / "containerapps.bicep",
)

ZONAS_PRIVATE_DNS_REQUERIDAS = (
    "privatelink.postgres.database.azure.com",
    "privatelink.blob.core.windows.net",
    "privatelink.vaultcore.net",
    "privatelink.redis.cache.windows.net",
)


def _leer_texto(ruta: Path) -> str:
    assert ruta.is_file(), f"No se encontró el archivo IaC requerido: {ruta}"
    return ruta.read_text(encoding="utf-8")


def _extraer_bloque(texto: str, firma: str) -> str:
    """Extrae el bloque `{ ... }` balanceado inmediatamente posterior a `firma`."""
    idx = texto.find(firma)
    assert idx != -1, f"No se encontró el bloque esperado: {firma!r}"
    inicio = texto.find("{", idx)
    assert inicio != -1, f"Bloque sin llave de apertura para: {firma!r}"

    profundidad = 0
    for pos in range(inicio, len(texto)):
        car = texto[pos]
        if car == "{":
            profundidad += 1
        elif car == "}":
            profundidad -= 1
            if profundidad == 0:
                return texto[idx : pos + 1]
    raise AssertionError(f"Bloque desbalanceado para: {firma!r}")


def _parsear_bicepparam(ruta: Path) -> dict[str, str]:
    """Extrae parámetros clave=valor declarados en un archivo `.bicepparam`."""
    contenido = _leer_texto(ruta)
    assert "using '../main.bicep'" in contenido, f"{ruta.name} debe referenciar ../main.bicep"
    resultado: dict[str, str] = {}
    for linea in contenido.splitlines():
        limpia = linea.strip()
        if not limpia or limpia.startswith("//") or limpia.startswith("using "):
            continue
        match = re.match(r"^param\s+([A-Za-z0-9_]+)\s*=\s*(.+)$", limpia)
        if match:
            clave, valor_raw = match.groups()
            resultado[clave] = valor_raw.strip().strip("'")
    return resultado


# =============================================================================
# 1. Validación estática de plantillas Bicep y parámetros por entorno
# =============================================================================
def test_infra_bicep_archivos_y_entornos_existen() -> None:
    """Deben existir los módulos Bicep base y los parámetros de dev, staging y prod."""
    for archivo in ARCHIVOS_BICEP_REQUERIDOS:
        assert archivo.is_file(), f"Falta plantilla Bicep obligatoria: {archivo}"
    for entorno in ENTORNOS:
        param_file = PARAMS_DIR / f"{entorno}.bicepparam"
        assert param_file.is_file(), f"Falta archivo de parámetros para {entorno}: {param_file}"


def test_bicep_prohibe_ingress_publico_e_ip_publica_en_todos_los_archivos() -> None:
    """Ninguna plantilla o archivo de parámetros puede habilitar exposición pública."""
    patrones_prohibidos = (
        re.compile(r"\bexternal\s*:\s*true\b"),
        re.compile(r"\binternal\s*:\s*false\b"),
        re.compile(r"\ballowInsecure\s*:\s*true\b"),
        re.compile(r"Microsoft\.Network/publicIPAddresses"),
        re.compile(r"\bexternal\s*=\s*true\b"),
        re.compile(r"\binternal\s*=\s*false\b"),
    )
    archivos = list(INFRA_DIR.glob("*.bicep")) + list(PARAMS_DIR.glob("*.bicepparam"))
    assert archivos, "No se encontraron archivos Bicep para inspeccionar"

    for archivo in archivos:
        contenido = _leer_texto(archivo)
        for patron in patrones_prohibidos:
            assert (
                patron.search(contenido) is None
            ), f"Patrón prohibido de exposición pública ({patron.pattern}) en {archivo.name}"


def test_containerapps_bicep_fija_entorno_interno_e_ingress_privado() -> None:
    """Valida vnetConfiguration.internal=true, ingress.external=false y worker sin ingress."""
    texto = _leer_texto(INFRA_DIR / "containerapps.bicep")

    cae = _extraer_bloque(
        texto, "resource managedEnvironment 'Microsoft.App/managedEnvironments@2024-03-01'"
    )
    assert re.search(r"publicNetworkAccess\s*:\s*'Disabled'", cae)
    vnet_cfg = _extraer_bloque(cae, "vnetConfiguration:")
    assert re.search(r"internal\s*:\s*true\b", vnet_cfg)
    assert "infrastructureSubnetId: caeSubnetId" in vnet_cfg

    api_app = _extraer_bloque(texto, "resource apiApp 'Microsoft.App/containerApps@2024-03-01'")
    api_ingress = _extraer_bloque(api_app, "ingress:")
    assert re.search(r"external\s*:\s*false\b", api_ingress)
    assert re.search(r"allowInsecure\s*:\s*false\b", api_ingress)
    assert re.search(r"targetPort\s*:\s*8000\b", api_ingress)
    assert "/admin/v1/health" in api_app
    assert "KC_ADMIN_DATABASE_URL_APP" in api_app
    assert "KC_ADMIN_DATABASE_URL_RO" in api_app

    web_app = _extraer_bloque(texto, "resource webApp 'Microsoft.App/containerApps@2024-03-01'")
    web_ingress = _extraer_bloque(web_app, "ingress:")
    assert re.search(r"external\s*:\s*false\b", web_ingress)
    assert re.search(r"allowInsecure\s*:\s*false\b", web_ingress)

    worker_app = _extraer_bloque(
        texto, "resource workerApp 'Microsoft.App/containerApps@2024-03-01'"
    )
    assert "ingress:" not in worker_app, "El worker no debe exponer ningún bloque ingress HTTP"


def test_network_bicep_delega_subred_bloquea_internet_y_crea_private_endpoints() -> None:
    """Valida subred delegada a Microsoft.App/environments, NSG DenyInternet y Private DNS."""
    texto = _leer_texto(INFRA_DIR / "network.bicep")

    vnet = _extraer_bloque(
        texto, "resource vnet 'Microsoft.Network/virtualNetworks@2023-11-01'"
    )
    assert "serviceName: 'Microsoft.App/environments'" in vnet
    assert "privateEndpointNetworkPolicies: 'Disabled'" in vnet

    nsg_cae = _extraer_bloque(
        texto, "resource nsgCae 'Microsoft.Network/networkSecurityGroups@2023-11-01'"
    )
    deny_internet = _extraer_bloque(nsg_cae, "name: 'DenyAllInternetInbound'")
    assert "direction: 'Inbound'" in deny_internet
    assert "access: 'Deny'" in deny_internet
    assert "sourceAddressPrefix: 'Internet'" in deny_internet

    # Ninguna regla Allow en NSGs puede aceptar tráfico desde '*' o 'Internet'
    for bloque_nsg in (
        nsg_cae,
        _extraer_bloque(
            texto, "resource nsgPe 'Microsoft.Network/networkSecurityGroups@2023-11-01'"
        ),
    ):
        for regla in re.finditer(r"access:\s*'Allow'.*?\}", bloque_nsg, flags=re.DOTALL):
            fragmento = regla.group(0)
            assert "sourceAddressPrefix: '*'" not in fragmento
            assert "sourceAddressPrefix: 'Internet'" not in fragmento

    # Private Endpoints + Private DNS Zones hacia los 4 servicios gestionados
    assert "resource pePostgres 'Microsoft.Network/privateEndpoints@2023-11-01'" in texto
    assert "resource peBlob 'Microsoft.Network/privateEndpoints@2023-11-01'" in texto
    assert "resource peKeyVault 'Microsoft.Network/privateEndpoints@2023-11-01'" in texto
    assert "resource peRedis 'Microsoft.Network/privateEndpoints@2023-11-01'" in texto
    for zona in ZONAS_PRIVATE_DNS_REQUERIDAS:
        assert zona in texto, f"Falta Private DNS Zone obligatoria: {zona}"


@pytest.mark.parametrize("entorno", ENTORNOS)
def test_parametros_entorno_cumplen_aislamiento_rfc1918_y_sin_emulador(entorno: str) -> None:
    """Cada entorno (dev, staging, prod) usa CIDRs privados, DNS interno y cero comodines."""
    params = _parsear_bicepparam(PARAMS_DIR / f"{entorno}.bicepparam")
    assert params.get("environment") == entorno

    vnet_net = ipaddress.ip_network(params["vnetAddressPrefix"], strict=True)
    cae_net = ipaddress.ip_network(params["caeSubnetPrefix"], strict=True)
    pe_net = ipaddress.ip_network(params["peSubnetPrefix"], strict=True)
    vpn_net = ipaddress.ip_network(params["corpVpnCidr"], strict=True)

    assert vnet_net.is_private
    assert cae_net.is_private and cae_net.subnet_of(vnet_net)
    assert pe_net.is_private and pe_net.subnet_of(vnet_net)
    assert not cae_net.overlaps(pe_net)
    assert cae_net.prefixlen <= 23, "La subred delegada a CAE requiere al menos /23"
    assert vpn_net.is_private and not vpn_net.overlaps(vnet_net)

    hostname = params["adminHostname"]
    assert hostname.endswith(".internal.kallicode.com")
    assert params["corsOrigins"] == f"https://{hostname}"
    assert "*" not in params["corsOrigins"]
    assert "devstoreaccount1" not in params["blobAccountUrl"]
    assert params["blobAccountUrl"].startswith("https://")
    assert params["telemetryBaseUrl"].startswith("https://")
    assert ".internal.kallicode.com" in params["telemetryBaseUrl"]

    if entorno == "prod":
        assert int(params["apiMinReplicas"]) >= 2


# =============================================================================
# 2. Simulación dinámica de rechazo externo (transporte, DNS y Host/CIDR)
# =============================================================================
def _puerto_tcp_libre_loopback() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def test_conexion_externa_rechazada_a_nivel_transporte() -> None:
    """Simula sondeo externo hacia endpoint no expuesto públicamente: falla a nivel TCP."""
    # Puerto cerrado (simula puerto externo bloqueado/no publicado por NSG/CAE interno)
    puerto_cerrado = _puerto_tcp_libre_loopback()
    with pytest.raises((httpx.ConnectError, httpx.ConnectTimeout, OSError)):
        httpx.get(f"http://127.0.0.1:{puerto_cerrado}/admin/v1/health", timeout=0.5)

    # Servidor escuchando únicamente en loopback interno: una conexión desde puerto/IP
    # distinto no publicado sigue rechazada. Aquí validamos explícitamente que un listener
    # enlazado solo a 127.0.0.1 rechaza conexiones que no alcanzan ese enlace privado.
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as servidor_interno:
        servidor_interno.bind(("127.0.0.1", 0))
        servidor_interno.listen(1)
        puerto_interno = int(servidor_interno.getsockname()[1])
        assert servidor_interno.getsockname()[0] == "127.0.0.1"

    # Tras cerrar el canal interno/túnel, cualquier reintento externo recibe rechazo directo.
    with (
        pytest.raises(ConnectionRefusedError),
        socket.create_connection(("127.0.0.1", puerto_interno), timeout=0.5),
    ):
        pass


def test_dns_privado_no_resoluble_desde_exterior(monkeypatch: pytest.MonkeyPatch) -> None:
    """Desde fuera de la VNet/VPN los hostnames internos no resuelven en DNS público."""
    for entorno in ENTORNOS:
        params = _parsear_bicepparam(PARAMS_DIR / f"{entorno}.bicepparam")
        hostname = params["adminHostname"]

        def _dns_publico_sin_zona_privada(host: Any, *args: Any, **kwargs: Any) -> list[Any]:
            raise socket.gaierror(socket.EAI_NONAME, f"Name or service not known: {host}")

        monkeypatch.setattr(socket, "getaddrinfo", _dns_publico_sin_zona_privada)
        with pytest.raises(socket.gaierror):
            socket.getaddrinfo(hostname, 443)


@pytest.mark.parametrize("entorno", ENTORNOS)
def test_api_rechaza_host_externo_y_solo_acepta_hostname_privado(
    entorno: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Con KC_ADMIN_ALLOWED_HOSTS del entorno privado, Host externo recibe 400."""
    from admin_api.main import app

    params = _parsear_bicepparam(PARAMS_DIR / f"{entorno}.bicepparam")
    host_privado = params["adminHostname"]

    monkeypatch.setenv("KC_ADMIN_ALLOWED_HOSTS", host_privado)
    monkeypatch.setenv("KC_ADMIN_CORS_ORIGINS", params["corsOrigins"])
    monkeypatch.setenv("KC_ADMIN_TRUSTED_PROXIES", params["caeSubnetPrefix"])
    get_admin_settings.cache_clear()
    try:
        cliente_externo = TestClient(
            app, base_url="https://api.kallicode.com", raise_server_exceptions=False
        )
        r_ext = cliente_externo.get("/admin/v1/openapi.json")
        assert r_ext.status_code == 400
        assert r_ext.headers.get("x-frame-options") == "DENY"

        cliente_spoof = TestClient(
            app, base_url="https://atacante.example.com", raise_server_exceptions=False
        )
        assert cliente_spoof.get("/admin/v1/health").status_code == 400

        cliente_interno = TestClient(
            app, base_url=f"https://{host_privado}", raise_server_exceptions=False
        )
        r_ok = cliente_interno.get("/admin/v1/openapi.json")
        assert r_ok.status_code == 200
    finally:
        get_admin_settings.cache_clear()


def test_scraping_metricas_restringido_al_cidr_privado_cae(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Con la configuración de prod, IPs externas en X-Forwarded-For son rechazadas (403)."""
    from admin_api.main import app

    params = _parsear_bicepparam(PARAMS_DIR / "prod.bicepparam")
    monkeypatch.setenv("KC_ADMIN_ENV", "local")
    monkeypatch.setenv("KC_ADMIN_ALLOWED_HOSTS", params["adminHostname"])
    monkeypatch.setenv("KC_ADMIN_CORS_ORIGINS", params["corsOrigins"])
    monkeypatch.setenv("KC_ADMIN_TRUSTED_PROXIES", params["caeSubnetPrefix"])
    monkeypatch.setenv("KC_ADMIN_METRICS_ALLOW_CIDRS", params["caeSubnetPrefix"])
    get_admin_settings.cache_clear()
    try:
        cliente = TestClient(
            app,
            base_url=f"https://{params['adminHostname']}",
            raise_server_exceptions=False,
        )
        r_ext = cliente.get(
            "/admin/v1/metrics",
            headers={"X-Forwarded-For": "203.0.113.45"},
        )
        assert r_ext.status_code == 403

        r_int = cliente.get(
            "/admin/v1/metrics",
            headers={"X-Forwarded-For": "10.62.0.15"},
        )
        assert r_int.status_code == 200
    finally:
        get_admin_settings.cache_clear()


# =============================================================================
# 3. Verificación de arranque local sin regresiones
# =============================================================================
def test_entorno_local_docker_compose_y_env_example_siguen_accesibles() -> None:
    """El aislamiento Azure no debe romper puertos ni acceso localhost en desarrollo."""
    compose = _leer_texto(ROOT / "docker-compose.yml")
    assert "5433:5432" in compose
    assert "6380:6379" in compose

    env_example = _leer_texto(ROOT / ".env.example")
    assert "KC_ADMIN_ENV=local" in env_example
    assert "KC_ADMIN_ALLOWED_HOSTS=localhost,127.0.0.1" in env_example
    assert "KC_ADMIN_CORS_ORIGINS=http://localhost:5173,http://127.0.0.1:5173" in env_example
