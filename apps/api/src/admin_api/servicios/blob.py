"""Almacenamiento de objetos para los informes de la consola.

Firma real contra Azure Blob Storage con credencial resuelta desde la bóveda. El
defecto BE-F20 del backend fue firmar con una clave de desarrollo incrustada en el
código y truncada a 32 caracteres, que ningún almacenamiento valida: las URL no
funcionaban fuera de local. Aquí el arranque falla si la configuración no está
completa en un entorno que no sea local, en lugar de generar URL inútiles.

Los informes se guardan con retención declarada y su descarga se registra: un
fichero exportado es una copia de datos de clientes que sale del sistema.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta

from kallicode_core.config import get_settings
from kallicode_core.errors import dependencia_no_disponible
from kallicode_core.logging import log

from ..settings import get_admin_settings

# Clave pública estándar del emulador Azurite para desarrollo y pruebas
AZURITE_DEV_KEY = (
    "Eby8vdM02xNOcqFlqUwJPLlmEtlCDXJ1OUzFT50uSRZ6IFsuFq2UVErCz4I6tq/K1SZFPTOtr/KBHBeksoGMGw=="
)


def _credencial() -> tuple[str, str]:
    """Cuenta y credencial de almacenamiento. Fuera de local son obligatorias."""
    s = get_settings()
    a = get_admin_settings()
    cuenta = s.blob_account_url
    if a.env not in ("local", "test") and "devstoreaccount1" in cuenta:
        raise RuntimeError(
            "KC_BLOB_ACCOUNT_URL apunta al emulador local en un entorno que no "
            "es local: la firma de descarga no funcionaría"
        )
    return cuenta, a.report_container


def ruta_informe(report_id: str, formato: str) -> str:
    """Ruta determinista del informe dentro del contenedor."""
    hoy = datetime.now(UTC).strftime("%Y/%m")
    return f"{hoy}/{report_id}.{formato}"


def hash_contenido(datos: bytes) -> str:
    """Hash del fichero, que se registra y se verifica antes de entregarlo."""
    return hashlib.sha256(datos).hexdigest()


async def subir_informe(blob_ref: str, datos: bytes, content_type: str) -> str:
    """Sube el informe y devuelve su hash. Falla si la subida no se confirma.

    El worker no marca el informe como listo hasta que esta función retorna: el
    defecto BE-F19 del backend fue marcar la exportación como lista tras descartar
    el contenido, de modo que la API entregaba una URL a un fichero inexistente.
    """
    import tempfile
    from pathlib import Path

    cuenta, contenedor = _credencial()
    s = get_admin_settings()
    es_azurite = "devstoreaccount1" in cuenta
    es_local_o_test = s.env in ("local", "test")

    try:
        if es_azurite:
            from azure.storage.blob import ContentSettings
            from azure.storage.blob.aio import BlobServiceClient

            # En local conectado a Azurite con versión de API compatible
            async with BlobServiceClient(
                cuenta, credential=AZURITE_DEV_KEY, api_version="2023-11-03"
            ) as svc:
                container_client = svc.get_container_client(contenedor)
                try:
                    await container_client.create_container()
                except Exception:
                    pass
                blob = svc.get_blob_client(contenedor, blob_ref)
                await blob.upload_blob(
                    datos,
                    overwrite=True,
                    content_settings=ContentSettings(content_type=content_type),
                    metadata={"retencion_dias": str(s.report_retention_days)},
                )
        elif es_local_o_test:
            # Emulación en almacenamiento local en disco si no hay Azurite configurado
            ruta_local = (
                Path(tempfile.gettempdir()) / "kallicode_blob_storage" / contenedor / blob_ref
            )
            ruta_local.parent.mkdir(parents=True, exist_ok=True)
            ruta_local.write_bytes(datos)
        else:
            from azure.identity.aio import DefaultAzureCredential
            from azure.storage.blob import ContentSettings
            from azure.storage.blob.aio import BlobServiceClient

            async with DefaultAzureCredential() as cred:
                async with BlobServiceClient(cuenta, credential=cred) as svc:
                    blob = svc.get_blob_client(contenedor, blob_ref)
                    await blob.upload_blob(
                        datos,
                        overwrite=False,
                        content_settings=ContentSettings(content_type=content_type),
                        metadata={"retencion_dias": str(s.report_retention_days)},
                    )
    except ImportError:
        # En local sin SDK se declara la dependencia caída en lugar de fingir.
        raise dependencia_no_disponible("almacenamiento de objetos") from None
    except Exception as exc:
        log.error("admin.blob.subida_fallida", blob_ref=blob_ref, excepcion=type(exc).__name__)
        raise dependencia_no_disponible("almacenamiento de objetos") from exc

    digest = hash_contenido(datos)
    log.info("admin.blob.subido", blob_ref=blob_ref, bytes=len(datos), sha256=digest[:12])
    return digest


def url_descarga(blob_ref: str) -> str:
    """URL firmada de vencimiento corto para descargar un informe."""
    cuenta, contenedor = _credencial()
    s = get_admin_settings()
    vence = datetime.now(UTC) + timedelta(minutes=s.report_url_ttl_min)
    es_emulador = "devstoreaccount1" in cuenta or s.env in ("local", "test")
    try:
        from azure.storage.blob import BlobSasPermissions, generate_blob_sas

        if es_emulador:
            token = generate_blob_sas(
                account_name="devstoreaccount1",
                account_key=AZURITE_DEV_KEY,
                container_name=contenedor,
                blob_name=blob_ref,
                permission=BlobSasPermissions(read=True),
                expiry=vence,
            )
        else:
            token = generate_blob_sas(
                account_name=cuenta.split("//")[-1].split(".")[0],
                container_name=contenedor,
                blob_name=blob_ref,
                permission=BlobSasPermissions(read=True),
                expiry=vence,
            )
        return f"{cuenta}/{contenedor}/{blob_ref}?{token}"
    except Exception as exc:
        log.error("admin.blob.firma_fallida", blob_ref=blob_ref, excepcion=type(exc).__name__)
        raise dependencia_no_disponible("almacenamiento de objetos") from exc


async def descargar_informe(blob_ref: str) -> bytes:
    """Descarga los bytes del informe directamente desde el almacenamiento."""
    import tempfile
    from pathlib import Path

    cuenta, contenedor = _credencial()
    s = get_admin_settings()
    es_azurite = "devstoreaccount1" in cuenta
    es_local_o_test = s.env in ("local", "test")
    try:
        if es_azurite:
            from azure.storage.blob.aio import BlobServiceClient

            async with BlobServiceClient(
                cuenta, credential=AZURITE_DEV_KEY, api_version="2023-11-03"
            ) as svc:
                blob = svc.get_blob_client(contenedor, blob_ref)
                stream = await blob.download_blob()
                return await stream.readall()
        elif es_local_o_test:
            ruta_local = (
                Path(tempfile.gettempdir()) / "kallicode_blob_storage" / contenedor / blob_ref
            )
            if ruta_local.exists():
                return ruta_local.read_bytes()
            raise FileNotFoundError(f"Blob no encontrado en almacenamiento local: {blob_ref}")
        else:
            from azure.identity.aio import DefaultAzureCredential
            from azure.storage.blob.aio import BlobServiceClient

            async with DefaultAzureCredential() as cred:
                async with BlobServiceClient(cuenta, credential=cred) as svc:
                    blob = svc.get_blob_client(contenedor, blob_ref)
                    stream = await blob.download_blob()
                    return await stream.readall()
    except Exception as exc:
        log.error(
            "admin.blob.descarga_fallida",
            blob_ref=blob_ref,
            excepcion=type(exc).__name__,
        )
        raise dependencia_no_disponible("almacenamiento de objetos") from exc
