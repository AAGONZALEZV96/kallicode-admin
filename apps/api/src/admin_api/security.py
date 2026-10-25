"""Seguridad de la consola: tokens de personal, segundo factor y contraseñas.

Reutiliza de la plataforma lo que no debe divergir —hash Argon2id, política de
contraseñas, tokens opacos y el material de firma RSA— y añade lo que es propio
de esta superficie:

  · Tokens con `typ="staff"`, emisor y audiencia propios, y claim `mfa` con el
    momento en que se verificó el segundo factor. Un token de personal no sirve
    en /api/v1 ni en /internal/v1, y al contrario tampoco (§18.4).
  · Verificación endurecida: exige los claims obligatorios y valida emisor y
    audiencia. El defecto BE-F12 del backend fue no hacerlo, de modo que un
    token sin `rol` producía un 500 en lugar de un 401.
  · Segundo factor TOTP con ventana acotada y códigos de recuperación de un
    solo uso.
"""

from __future__ import annotations

import hmac
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import cast

import jwt
import pyotp
from kallicode_core.seguridad import (
    generar_token_opaco,
    hash_token,
    hashear_password,
    validar_politica_password,
    verificar_password,
)

from .errors import mfa_invalido, mfa_requerido, rol_staff_insuficiente
from .settings import get_admin_settings

# Se reexportan para que los routers no importen del núcleo directamente y la
# frontera quede en un solo módulo.
__all__ = [
    "PERMISOS_ROL",
    "STAFF_ROLES",
    "comparar_hash",
    "emitir_tokens_staff",
    "exigir_mfa_vigente",
    "exigir_rol_staff",
    "generar_codigos_recuperacion",
    "generar_token_opaco",
    "hash_token",
    "hashear_password",
    "nuevo_secreto_totp",
    "url_otpauth",
    "validar_politica_password",
    "verificar_password",
    "verificar_token_staff",
    "verificar_totp",
]

STAFF_ROLES: tuple[str, ...] = (
    "staff_soporte",
    "staff_operaciones",
    "staff_negocio",
    "staff_admin",
)

PERMISOS_ROL: dict[str, tuple[str, ...]] = {
    "staff_soporte": (
        "auditoria.propias",
        "concesiones.propias",
        "concesiones.solicitar",
        "expediente.leer",
        "informes.descargar",
        "negocio.clientes.leer",
    ),
    "staff_operaciones": (
        "auditoria.propias",
        "concesiones.propias",
        "concesiones.solicitar",
        "informes.descargar",
        "ops.colas.leer",
        "ops.modelos.leer",
        "ops.sla.leer",
        "ops.telemetria.leer",
    ),
    "staff_negocio": (
        "auditoria.propias",
        "concesiones.propias",
        "concesiones.solicitar",
        "informes.crear",
        "informes.descargar",
        "negocio.clientes.leer",
        "negocio.overview.leer",
        "negocio.suscripciones.leer",
        "negocio.tokens.leer",
        "ops.modelos.leer",
        "ops.sla.leer",
    ),
    "staff_admin": (
        "auditoria.exportar",
        "auditoria.propias",
        "auditoria.total.leer",
        "concesiones.propias",
        "concesiones.revocar_ajenas",
        "concesiones.solicitar",
        "concesiones.todas",
        "expediente.leer",
        "informes.crear",
        "informes.descargar",
        "negocio.clientes.leer",
        "negocio.overview.leer",
        "negocio.suscripciones.leer",
        "negocio.tokens.leer",
        "ops.colas.leer",
        "ops.modelos.leer",
        "ops.sla.leer",
        "ops.telemetria.leer",
        "personal.gestionar",
        "personal.leer",
    ),
}


def _claves() -> tuple[str, str]:
    """Par (privada, pública) PEM. Mismo material que el resto de la plataforma.

    Se toma de `kallicode_core.seguridad`, cuyo resolutor ya contempla las claves
    de Key Vault en producción y un par efímero en local. Es una función interna
    del núcleo; conviene que E5 la promueva a API pública, y hasta entonces esta
    es la única línea de la consola que depende de un detalle interno suyo.
    """
    from kallicode_core.seguridad import _claves as _core_claves

    return cast(tuple[str, str], _core_claves())


# --------------------------------------------------------------------- tokens
def emitir_tokens_staff(staff_id: str, rol: str, mfa_at: datetime) -> str:
    """Emite el token de acceso de personal (§18.2).

    Parámetros:
        staff_id: identificador del empleado (st_<ulid>).
        rol: uno de STAFF_ROLES.
        mfa_at: momento en que se verificó el segundo factor de esta sesión.
    """
    if rol not in STAFF_ROLES:
        raise rol_staff_insuficiente(f"Rol de personal desconocido: {rol}")
    s = get_admin_settings()
    priv, _ = _claves()
    ahora = datetime.now(UTC)
    return jwt.encode(
        {
            "sub": staff_id,
            "rol": rol,
            "typ": "staff",
            "mfa": int(mfa_at.timestamp()),
            "iss": s.jwt_issuer,
            "aud": s.jwt_audience,
            "jti": uuid.uuid4().hex,
            "iat": int(ahora.timestamp()),
            "exp": int((ahora + timedelta(minutes=s.staff_access_token_ttl_min)).timestamp()),
        },
        priv,
        algorithm="RS256",
    )


def verificar_token_staff(token: str) -> dict[str, object]:
    """Valida firma, expiración, emisor, audiencia, tipo y claims obligatorios.

    Devuelve los claims. Lanza `NO_AUTENTICADO` en cualquier otro caso; nunca
    deja que un token incompleto llegue a producir un fallo no controlado.
    """
    from kallicode_core.errors import no_autenticado

    s = get_admin_settings()
    _, pub = _claves()
    try:
        claims = jwt.decode(
            token,
            pub,
            algorithms=["RS256"],
            issuer=s.jwt_issuer,
            audience=s.jwt_audience,
            options={
                "require": ["sub", "rol", "typ", "mfa", "iss", "aud", "exp", "iat", "jti"]
            },
        )
    except jwt.ExpiredSignatureError as exc:
        raise no_autenticado("El token ha expirado.") from exc
    except jwt.InvalidTokenError as exc:
        raise no_autenticado() from exc

    if claims.get("typ") != "staff":
        raise no_autenticado("Tipo de token incorrecto para esta API.")
    if claims.get("rol") not in STAFF_ROLES:
        raise no_autenticado("Rol de personal no reconocido.")
    return claims


def exigir_rol_staff(rol_actual: str, permitidos: tuple[str, ...]) -> None:
    """Comprueba el rol contra la matriz de permisos del endpoint."""
    if rol_actual not in permitidos:
        raise rol_staff_insuficiente()


def exigir_mfa_vigente(claims: dict[str, object]) -> datetime:
    """Comprueba la caducidad por inactividad del segundo factor (§18.4).

    Superado el plazo, la sesión no se renueva y el empleado repite el segundo
    factor. Devuelve el momento de la verificación para poder registrarlo.
    """
    s = get_admin_settings()
    marca = claims.get("mfa")
    if not isinstance(marca, int):
        raise mfa_requerido()
    mfa_at = datetime.fromtimestamp(marca, UTC)
    if datetime.now(UTC) - mfa_at > timedelta(minutes=s.staff_idle_timeout_min):
        raise mfa_requerido("Verifica de nuevo tu segundo factor.")
    return mfa_at


# ---------------------------------------------------------------- segundo factor
def nuevo_secreto_totp() -> str:
    """Secreto en base32. Se devuelve una única vez, en la inscripción (§18.3)."""
    return pyotp.random_base32()


def url_otpauth(secreto: str, email: str) -> str:
    """URL otpauth:// para el código QR del autenticador."""
    return pyotp.TOTP(secreto).provisioning_uri(name=email, issuer_name="Kallicode")


def verificar_totp(secreto: str, codigo: str) -> None:
    """Valida el código con la ventana configurada. Lanza MFA_INVALIDO si falla.

    La ventana es de un intervalo antes y después para tolerar desfase de reloj,
    y no más: ampliarla convierte el segundo factor en un trámite.
    """
    s = get_admin_settings()
    codigo = (codigo or "").strip().replace(" ", "")
    if not codigo.isdigit() or len(codigo) != 6:
        raise mfa_invalido()
    if not pyotp.TOTP(secreto).verify(codigo, valid_window=s.mfa_totp_window):
        raise mfa_invalido()


def generar_codigos_recuperacion() -> list[tuple[str, str]]:
    """Devuelve [(codigo_en_claro, hash)] de un solo uso.

    El claro se muestra una única vez y no existe endpoint para volver a
    consultarlo (§18.3).
    """
    s = get_admin_settings()
    salida: list[tuple[str, str]] = []
    for _ in range(s.mfa_recovery_codes):
        claro = f"{secrets.token_hex(2)}-{secrets.token_hex(2)}"
        salida.append((claro, hash_token(claro)))
    return salida


def comparar_hash(a: str, b: str) -> bool:
    """Comparación en tiempo constante para hashes y tokens opacos."""
    return hmac.compare_digest(a, b)
