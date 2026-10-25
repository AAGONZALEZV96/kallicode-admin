"""Pruebas unitarias de tokens de personal, claims y seguridad de staff (KC-ADM-B1-07)."""

from __future__ import annotations

import time
import uuid
from datetime import UTC, datetime, timedelta

import jwt
import pyotp
import pytest
from admin_api.security import (
    STAFF_ROLES,
    _claves,
    emitir_tokens_staff,
    exigir_mfa_vigente,
    exigir_rol_staff,
    generar_codigos_recuperacion,
    hashear_password,
    nuevo_secreto_totp,
    verificar_password,
    verificar_token_staff,
    verificar_totp,
)
from admin_api.settings import get_admin_settings
from kallicode_core.errors import AppError


def test_emitir_tokens_staff_claims_obligatorios() -> None:
    """Verifica la presencia y formato de los claims obligatorios en el Access Token JWT."""
    s = get_admin_settings()
    staff_id = "st_01TESTSTAFFID00000000000"
    rol = "staff_admin"
    mfa_at = datetime.now(UTC)

    token = emitir_tokens_staff(staff_id, rol, mfa_at)
    assert isinstance(token, str)

    _, pub = _claves()
    claims = jwt.decode(
        token,
        pub,
        algorithms=["RS256"],
        issuer=s.jwt_issuer,
        audience=s.jwt_audience,
    )

    assert claims["typ"] == "staff"
    assert claims["iss"] == "kallicode-admin"
    assert claims["aud"] == "admin-v1"
    assert claims["sub"] == staff_id
    assert claims["rol"] == rol
    assert claims["mfa"] == int(mfa_at.timestamp())
    assert claims["jti"]
    assert len(claims["jti"]) >= 16
    assert claims["exp"] - claims["iat"] == s.staff_access_token_ttl_min * 60


@pytest.mark.parametrize("rol", STAFF_ROLES)
def test_emitir_tokens_staff_todos_los_roles(rol: str) -> None:
    """El generador admite todos los roles definidos en STAFF_ROLES."""
    token = emitir_tokens_staff("st_01TEST", rol, datetime.now(UTC))
    claims = verificar_token_staff(token)
    assert claims["rol"] == rol


def test_emitir_tokens_staff_rol_invalido_falla() -> None:
    """Un rol fuera del catálogo es rechazado de inmediato."""
    with pytest.raises(AppError) as exc:
        emitir_tokens_staff("st_01TEST", "super_hacker", datetime.now(UTC))
    assert exc.value.codigo == "ROL_STAFF_INSUFICIENTE"


def test_verificar_token_staff_valido() -> None:
    """Un token legítimo se decodifica correctamente y expone los claims."""
    mfa_momento = datetime.now(UTC)
    token = emitir_tokens_staff("st_test_valido", "staff_soporte", mfa_momento)
    claims = verificar_token_staff(token)

    assert claims["sub"] == "st_test_valido"
    assert claims["rol"] == "staff_soporte"
    assert claims["typ"] == "staff"
    assert claims["mfa"] == int(mfa_momento.timestamp())


def test_verificar_token_staff_expirado() -> None:
    """Un token cuya marca de expiración ya pasó es rechazado con NO_AUTENTICADO."""
    s = get_admin_settings()
    priv, _ = _claves()
    ahora = int(time.time()) - 1000

    token_expirado = jwt.encode(
        {
            "sub": "st_expirado",
            "rol": "staff_admin",
            "typ": "staff",
            "mfa": ahora - 500,
            "iss": s.jwt_issuer,
            "aud": s.jwt_audience,
            "jti": uuid.uuid4().hex,
            "iat": ahora - 1000,
            "exp": ahora - 100,
        },
        priv,
        algorithm="RS256",
    )

    with pytest.raises(AppError) as exc:
        verificar_token_staff(token_expirado)
    assert exc.value.http == 401
    assert "expirado" in exc.value.mensaje.lower()


def test_verificar_token_staff_typ_invalido() -> None:
    """Tokens de usuario cliente (typ=user o similar) son rechazados por la consola."""
    s = get_admin_settings()
    priv, _ = _claves()
    ahora = int(time.time())

    token_cliente = jwt.encode(
        {
            "sub": "usr_cliente",
            "rol": "staff_soporte",
            "typ": "bearer",
            "mfa": ahora,
            "iss": s.jwt_issuer,
            "aud": s.jwt_audience,
            "jti": uuid.uuid4().hex,
            "iat": ahora,
            "exp": ahora + 900,
        },
        priv,
        algorithm="RS256",
    )

    with pytest.raises(AppError) as exc:
        verificar_token_staff(token_cliente)
    assert exc.value.http == 401
    assert "tipo de token" in exc.value.mensaje.lower()


def test_exigir_rol_staff_cumplimiento() -> None:
    """Verifica la función de control de roles."""
    exigir_rol_staff("staff_admin", ("staff_admin", "staff_negocio"))
    exigir_rol_staff("staff_soporte", STAFF_ROLES)

    with pytest.raises(AppError) as exc:
        exigir_rol_staff("staff_soporte", ("staff_admin",))
    assert exc.value.codigo == "ROL_STAFF_INSUFICIENTE"


def test_exigir_mfa_vigente_exitoso_y_caducado() -> None:
    """Valida la caducidad por inactividad de la verificación MFA."""
    ahora = datetime.now(UTC)
    claims_validos: dict[str, object] = {"mfa": int(ahora.timestamp())}
    mfa_resuelto = exigir_mfa_vigente(claims_validos)
    assert abs((mfa_resuelto - ahora).total_seconds()) < 2

    # MFA verificado hace 40 minutos (timeout = 30 min)
    hace_40m = ahora - timedelta(minutes=40)
    claims_caducados: dict[str, object] = {"mfa": int(hace_40m.timestamp())}
    with pytest.raises(AppError) as exc:
        exigir_mfa_vigente(claims_caducados)
    assert exc.value.codigo == "MFA_REQUERIDO"


def test_argon2_hashing_y_verificacion() -> None:
    """Comprueba el cifrado y validación de contraseñas con Argon2id."""
    password = "Password-Super-Segura-2026!"
    hashed = hashear_password(password)
    assert hashed.startswith("$argon2id$")
    assert verificar_password(password, hashed) is True
    assert verificar_password("Password-Incorrecta-1234!", hashed) is False


def test_totp_generacion_y_validacion() -> None:
    """Comprueba la generación y validación de códigos TOTP."""
    secreto = nuevo_secreto_totp()
    assert len(secreto) == 32

    totp = pyotp.TOTP(secreto)
    codigo_actual = totp.now()
    verificar_totp(secreto, codigo_actual)

    # Código inválido
    with pytest.raises(AppError) as exc:
        verificar_totp(secreto, "000000" if codigo_actual != "000000" else "111111")
    assert exc.value.codigo == "MFA_INVALIDO"


def test_generar_codigos_recuperacion_unicidad() -> None:
    """Comprueba la estructura de los códigos de recuperación."""
    pares = generar_codigos_recuperacion()
    assert len(pares) >= 8
    claros = [c for c, _ in pares]
    assert len(set(claros)) == len(claros)
    for claro, hashed in pares:
        assert len(claro) == 9
        assert "-" in claro
        assert len(hashed) == 64
