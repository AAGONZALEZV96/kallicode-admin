"""Códigos de error propios de la API de administración.

Reutiliza `AppError` de la plataforma para que el sobre de respuesta, el
`trace_id` y el manejador central sean los mismos que en /api/v1. Aquí solo se
añaden los doce códigos que el apéndice §19 incorpora en la versión 1.1 del
documento de diseño.

Regla de higiene específica de esta superficie: ningún mensaje de error revela
nombres de excepción, rutas internas, nombres de tabla ni identificadores de
otros clientes. Es más estricta que en /api/v1 porque el actor que ve el mensaje
tiene acceso a varios clientes.
"""

from __future__ import annotations

from kallicode_core.errors import CATALOGO_ERRORES, AppError

_ERRORES_ADMIN = {
    "CREDENCIALES_INVALIDAS": {
        "http": 401,
        "descripcion": "Correo o contraseña incorrectos.",
    },
    "TOKEN_INVALIDO": {
        "http": 401,
        "descripcion": "Token de acceso de personal inválido o no reconocido.",
    },
    "MFA_REQUERIDO": {"http": 403, "descripcion": "Verificación de segundo factor requerida."},
    "MFA_INVALIDO": {"http": 401, "descripcion": "El código de verificación no es correcto."},
    "MFA_NO_INSCRITO": {
        "http": 403,
        "descripcion": "Debes inscribir tu segundo factor antes de continuar.",
    },
    "STAFF_DESACTIVADO": {"http": 403, "descripcion": "Tu cuenta está desactivada."},
    "ROL_STAFF_INSUFICIENTE": {
        "http": 403,
        "descripcion": "Tu rol no permite esta operación.",
    },
    "ACCESO_NO_JUSTIFICADO": {"http": 403, "descripcion": "Acceso a datos no justificado."},
    "CONCESION_CADUCADA": {
        "http": 403,
        "descripcion": "La concesión de acceso ha caducado.",
    },
    "CONCESION_DUPLICADA": {"http": 409, "descripcion": "Ya existe una concesión activa."},
    "MOTIVO_INSUFICIENTE": {
        "http": 422,
        "descripcion": "El motivo proporcionado es insuficiente.",
    },
    "AGREGADO_NO_DISPONIBLE": {
        "http": 503,
        "descripcion": "Agregado analítico no disponible.",
    },
    "SLA_SIN_DEFINICION": {
        "http": 409,
        "descripcion": "No hay objetivos de nivel de servicio configurados.",
    },
    "TELEMETRIA_NO_DISPONIBLE": {
        "http": 503,
        "descripcion": "La telemetría del pipeline no está disponible.",
    },
}
CATALOGO_ERRORES.update(_ERRORES_ADMIN)

__all__ = [
    "acceso_no_justificado",
    "agregado_no_disponible",
    "concesion_caducada",
    "concesion_duplicada",
    "credenciales_invalidas",
    "mfa_invalido",
    "mfa_no_inscrito",
    "mfa_requerido",
    "motivo_insuficiente",
    "rol_staff_insuficiente",
    "sla_sin_definicion",
    "staff_desactivado",
    "telemetria_no_disponible",
    "token_invalido",
]


# --------------------------------------------------------------- identidad
def token_invalido(
    msj: str = "Token de acceso de personal inválido.",
) -> AppError:
    """401 · token de acceso ausente, alterado, caducado o con claims incorrectos."""
    return AppError("TOKEN_INVALIDO", 401, msj)


def credenciales_invalidas(
    msj: str = "Correo o contraseña incorrectos.",
) -> AppError:
    """401 · credenciales incorrectas o cuenta en estado no autenticable."""
    return AppError("CREDENCIALES_INVALIDAS", 401, msj)


def mfa_requerido(
    msj: str = "Verificación de segundo factor requerida.",
) -> AppError:
    """403 · el token no acredita segundo factor vigente en esta sesión."""
    return AppError("MFA_REQUERIDO", 403, msj)


def mfa_invalido(
    msj: str = "El código de verificación no es correcto.",
) -> AppError:
    """401 · código TOTP incorrecto o fuera de la ventana admitida."""
    return AppError("MFA_INVALIDO", 401, msj)


def mfa_no_inscrito(
    msj: str = "Debes inscribir tu segundo factor antes de continuar.",
) -> AppError:
    """403 · la cuenta no tiene secreto TOTP inscrito (§18.3)."""
    return AppError("MFA_NO_INSCRITO", 403, msj)


def staff_desactivado(msj: str = "Tu cuenta está desactivada.") -> AppError:
    """403 · cuenta de personal desactivada."""
    return AppError("STAFF_DESACTIVADO", 403, msj)


def rol_staff_insuficiente(
    msj: str = "Tu rol no permite esta operación.",
) -> AppError:
    """403 · el rol no figura entre los autorizados del endpoint."""
    return AppError("ROL_STAFF_INSUFICIENTE", 403, msj)


# ------------------------------------------------------- acceso a cliente
def acceso_no_justificado(
    tenant_id: str | None = None,
    alcance: str | None = None,
) -> AppError:
    """403 · se pidió un dato identificable sin concesión vigente (§18.13).

    A diferencia de §3.3, aquí se devuelve 403 y no 404: en esta superficie la
    existencia del cliente no es información que ocultar al personal; lo que hay
    que controlar y registrar es el acceso a sus datos (§3.3.1).
    """
    detalle: dict[str, str] = {}
    if tenant_id:
        detalle["tenant_id"] = tenant_id
    if alcance:
        detalle["alcance_requerido"] = alcance
    return AppError(
        "ACCESO_NO_JUSTIFICADO",
        403,
        "Necesitas una concesión de acceso vigente para ver los datos "
        "identificables de este cliente.",
        detalle or None,
    )


def concesion_caducada(
    msj: str = "La concesión de acceso ha caducado o ha sido revocada.",
) -> AppError:
    """403 · la concesión invocada ya no está vigente."""
    return AppError("CONCESION_CADUCADA", 403, msj)


def concesion_duplicada(grant_id: str) -> AppError:
    """409 · ya existe una concesión vigente equivalente (§18.13).

    Devuelve el identificador de la existente para que la interfaz pueda
    reutilizarla en lugar de pedir al empleado que repita el motivo.
    """
    return AppError(
        "CONCESION_DUPLICADA",
        409,
        "Ya tienes una concesión vigente equivalente.",
        {"grant_id": grant_id},
    )


def motivo_insuficiente(razon: str) -> AppError:
    """422 · motivo demasiado corto, genérico o sin la referencia exigida.

    La auditoría vale lo que valga el motivo: un motivo vacío convierte el
    registro de accesos en un trámite sin valor probatorio.
    """
    return AppError(
        "MOTIVO_INSUFICIENTE",
        422,
        "El motivo debe describir el caso concreto que justifica el acceso.",
        {"razon": razon},
    )


# ------------------------------------------------------- datos y agregados
def agregado_no_disponible(vista: str, edad_s: int | None = None) -> AppError:
    """503 · la vista materializada está en refresco o su refresco falló.

    Se devuelve error en lugar de servir un dato viejo como actual: mostrar una
    cifra obsoleta sin decirlo es peor que no mostrarla.
    """
    detalle: dict[str, object] = {"vista": vista}
    if edad_s is not None:
        detalle["antiguedad_s"] = edad_s
    return AppError(
        "AGREGADO_NO_DISPONIBLE",
        503,
        "Los datos agregados se están recalculando. Vuelve a intentarlo en unos minutos.",
        detalle,
    )


def sla_sin_definicion(plan: str | None = None, etapa: str | None = None) -> AppError:
    """409 · no hay objetivos de nivel de servicio configurados (§18.27).

    Se prefiere el error a calcular sobre un supuesto: un cumplimiento
    inventado erosiona la confianza en el resto de la consola.
    """
    detalle = {k: v for k, v in (("plan", plan), ("etapa", etapa)) if v}
    return AppError(
        "SLA_SIN_DEFINICION",
        409,
        "No hay objetivos de nivel de servicio configurados para ese plan.",
        detalle or None,
    )


def telemetria_no_disponible(edad_s: int | None = None) -> AppError:
    """503 · el contrato de telemetría no responde o su dato es demasiado viejo.

    Distinguir esto de «no hay trabajo» es obligatorio: en la pantalla de
    guardia son situaciones opuestas y confundirlas es el error clásico de este
    tipo de panel (§18.24).
    """
    return AppError(
        "TELEMETRIA_NO_DISPONIBLE",
        503,
        "La telemetría del pipeline no está disponible.",
        {"antiguedad_s": edad_s} if edad_s is not None else None,
    )
