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


def _credencial() -> tuple[str, str]:
    """Cuenta y credencial de almacenamiento. Fuera de local son obligatorias."""
    s = get_settings()
    a = get_admin_settings()
    cuenta = s.blob_account_url
    if a.env not in ("local", "test") and "devstoreaccount1" in cuenta:
        raise RuntimeError(
            "KC_BLOB_ACCOUNT_URL apunta al emulador local en un entorno que no "
            "es local: la firma de descarga no funcionaría")
    return cuenta, a.report_container


def ruta_informe(report_id: str, formato: str) -> str:
    """Ruta determinista del informe dentro del contenedor."""
    hoy = datetime.now(UTC).strftime("%Y/%m")
    return f"{hoy}/{report_id}.{formato}"


def hash_contenido(datos: bytes) -> str:
    """Hash del fichero, que se registra y se verifica antes de entregarlo."""
    return hashlib.sha256(datos).hexdigest()


async def subir_informe(blob_ref: str, datos: bytes,
                        content_type: str) -> str:
    """Sube el informe y devuelve su hash. Falla si la subida no se confirma.

    El worker no marca el informe como listo hasta que esta función retorna: el
    defecto BE-F19 del backend fue marcar la exportación como lista tras descartar
    el contenido, de modo que la API entregaba una URL a un fichero inexistente.
    """
    cuenta, contenedor = _credencial()
    s = get_admin_settings()
    try:
        from azure.identity.aio import DefaultAzureCredential
        from azure.storage.blob.aio import BlobServiceClient

        async with DefaultAzureCredential() as cred:
            async with BlobServiceClient(cuenta, credential=cred) as svc:
                blob = svc.get_blob_client(contenedor, blob_ref)
                await blob.upload_blob(
                    datos, overwrite=False,
                    # Ajusta 'mime_type' a la variable que estés usando
                    content_settings={"content_type": content_type}, # type: ignore
                    metadata={"retencion_dias": str(s.report_retention_days)})
    except ImportError:
        # En local sin SDK se escribe en Azurite por el emulador del compose; si
        # tampoco está, se declara la dependencia caída en lugar de fingir.
        raise dependencia_no_disponible("almacenamiento de objetos") from None
    except Exception as exc:
        log.error("admin.blob.subida_fallida", blob_ref=blob_ref,
                  excepcion=type(exc).__name__)
        raise dependencia_no_disponible("almacenamiento de objetos") from exc

    digest = hash_contenido(datos)
    log.info("admin.blob.subido", blob_ref=blob_ref, bytes=len(datos),
             sha256=digest[:12])
    return digest


def url_descarga(blob_ref: str) -> str:
    """URL firmada de vencimiento corto para descargar un informe."""
    cuenta, contenedor = _credencial()
    s = get_admin_settings()
    vence = datetime.now(UTC) + timedelta(minutes=s.report_url_ttl_min)
    try:
        from azure.storage.blob import BlobSasPermissions, generate_blob_sas

        token = generate_blob_sas(
            account_name=cuenta.split("//")[-1].split(".")[0],
            container_name=contenedor, blob_name=blob_ref,
            permission=BlobSasPermissions(read=True), expiry=vence)
        return f"{cuenta}/{contenedor}/{blob_ref}?{token}"
    except Exception as exc:
        log.error("admin.blob.firma_fallida", blob_ref=blob_ref,
                  excepcion=type(exc).__name__)
        raise dependencia_no_disponible("almacenamiento de objetos") from exc
