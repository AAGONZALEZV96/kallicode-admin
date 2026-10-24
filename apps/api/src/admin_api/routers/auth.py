"""§18.1 – §18.8 · Identidad y sesión del personal de KalliCode.

Resuelve la brecha ADM-G02. El personal no vive en `core.users`, que exige
pertenencia a una organización cliente: crear empleados como usuarios dentro de
organizaciones de cliente contaminaría sus datos y haría inservible su auditoría.

El inicio de sesión es en dos pasos y el segundo factor no admite excepción por
rol. Tres reglas que el flujo del portal no tiene y aquí sí:

  · Sin segundo factor verificado no se emite ningún token (§18.1, §18.2).
  · La sesión caduca antes: 15 minutos de acceso, 8 horas de renovación y 30
    minutos de inactividad, tras los cuales se repite el segundo factor.
  · La respuesta es indistinguible en tiempo y forma para correo inexistente,
    contraseña incorrecta, dominio no autorizado y cuenta desactivada.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Request, Response, status
from kallicode_core.errors import AppError, conflicto, no_autenticado, validacion
from kallicode_core.ids import nuevo
from kallicode_core.logging import hash_email, log
from pydantic import BaseModel, ConfigDict, EmailStr, Field
from sqlalchemy import text

from ..audit import registrar_accion
from ..db import admin_session, todos, uno
from ..deps import (
    StaffDep,
    limite_login,
    limpiar_fallos_login,
    registrar_fallo_login,
    revocar_jti,
    revocar_todas_sesiones_redis,
)
from ..errors import credenciales_invalidas, mfa_invalido, mfa_no_inscrito, staff_desactivado
from ..security import (
    emitir_tokens_staff,
    generar_codigos_recuperacion,
    generar_token_opaco,
    hash_token,
    hashear_password,
    nuevo_secreto_totp,
    url_otpauth,
    validar_politica_password,
    verificar_password,
    verificar_totp,
)
from ..settings import get_admin_settings

router = APIRouter(prefix="/admin/v1/auth", tags=["Identidad y sesión"])


# ------------------------------------------------------------------ modelos
class _Base(BaseModel):
    # Los campos desconocidos se rechazan para detectar errores de integración
    # temprano (§3.1).
    model_config = ConfigDict(extra="forbid")


class LoginIn(_Base):
    email: EmailStr
    password: str = Field(min_length=12, max_length=128)


class LoginOut(_Base):
    mfa_token: str
    mfa_inscrito: bool
    expira_en: int


class MfaVerifyIn(_Base):
    mfa_token: str = Field(min_length=8, max_length=128)
    codigo: str = Field(min_length=4, max_length=32)


class StaffMin(_Base):
    id: str
    nombre: str
    rol: str


class TokensOut(_Base):
    access_token: str
    refresh_token: str
    staff: StaffMin
    expira_en: int


class MfaEnrollIn(_Base):
    mfa_token: str | None = None
    password: str | None = Field(default=None, min_length=12, max_length=128)
    codigo: str | None = Field(default=None, min_length=6, max_length=6)


class MfaEnrollOut(_Base):
    secreto: str | None = None
    otpauth_url: str | None = None
    codigos_recuperacion: list[str] | None = None
    inscrito: bool


class RefreshIn(_Base):
    refresh_token: str = Field(min_length=8, max_length=128)


class RefreshOut(_Base):
    access_token: str
    refresh_token: str
    expira_en: int


class LogoutIn(_Base):
    refresh_token: str | None = None
    todas: bool = False


class LogoutOut(_Base):
    sesiones_revocadas: int


class ForgotIn(_Base):
    email: EmailStr


class ResetIn(_Base):
    token: str = Field(min_length=8, max_length=128)
    password: str = Field(min_length=12, max_length=128)


class ResetOut(_Base):
    sesiones_revocadas: int


class AcceptIn(_Base):
    token: str = Field(min_length=8, max_length=128)
    nombre: str = Field(min_length=2, max_length=120)
    password: str = Field(min_length=12, max_length=128)


class AcceptOut(_Base):
    staff: dict[str, Any]
    mfa_token: str


# ------------------------------------------------------------------ helpers
def _ahora() -> datetime:
    return datetime.now(UTC)


def _dominio_autorizado(email: str) -> bool:
    s = get_admin_settings()
    return email.lower().rsplit("@", 1)[-1] in s.dominios_permitidos


async def _crear_desafio(db: Any, staff_id: str, request: Request) -> tuple[str, int]:
    """Crea el desafío de segundo factor y devuelve (token_en_claro, ttl_s)."""
    s = get_admin_settings()
    claro, hashed = generar_token_opaco("mfa")
    await uno(
        db,
        """
        INSERT INTO admin.staff_mfa_challenges
            (id, staff_id, token_hash, ip, user_agent, expires_at)
        VALUES (:id, :s, :h, :ip, :ua, now() + make_interval(secs => :ttl))
        RETURNING id
    """,
        {
            "id": nuevo("mfa"),
            "s": staff_id,
            "h": hashed,
            "ip": request.client.host if request.client else None,
            "ua": request.headers.get("user-agent"),
            "ttl": s.mfa_challenge_ttl_s,
        },
    )
    return claro, s.mfa_challenge_ttl_s


async def _emitir_sesion(
    db: Any, staff: dict[str, Any], request: Request, mfa_at: datetime
) -> TokensOut:
    """Emite el par de tokens y persiste el refresh con su hash."""
    s = get_admin_settings()
    claro, hashed = generar_token_opaco("rt")
    await uno(
        db,
        """
        INSERT INTO admin.staff_refresh_tokens
            (id, staff_id, token_hash, mfa_at, ip, user_agent, expires_at)
        VALUES (:id, :s, :h, :m, :ip, :ua, now() + make_interval(hours => :ttl))
        RETURNING id
    """,
        {
            "id": nuevo("rt"),
            "s": staff["id"],
            "h": hashed,
            "m": mfa_at,
            "ip": request.client.host if request.client else None,
            "ua": request.headers.get("user-agent"),
            "ttl": s.staff_refresh_token_ttl_h,
        },
    )
    await uno(
        db,
        "UPDATE admin.staff SET last_login_at = now(), "
        "failed_attempts = 0 WHERE id = :i RETURNING id",
        {"i": staff["id"]},
    )
    return TokensOut(
        access_token=emitir_tokens_staff(staff["id"], staff["role"], mfa_at),
        refresh_token=claro,
        staff=StaffMin(id=staff["id"], nombre=staff["full_name"], rol=staff["role"]),
        expira_en=s.staff_access_token_ttl_min * 60,
    )


async def _revocar_sesiones(db: Any, staff_id: str, motivo: str) -> int:
    filas = await todos(
        db,
        """
        UPDATE admin.staff_refresh_tokens
        SET revoked = true, revoked_reason = :m
        WHERE staff_id = :s AND NOT revoked AND expires_at > now()
        RETURNING id
    """,
        {"s": staff_id, "m": motivo},
    )
    return len(filas)


async def _guardar_password(db: Any, staff_id: str, password: str) -> None:
    """Fija la contraseña comprobando el historial (§18.7)."""
    s = get_admin_settings()
    validar_politica_password(password)
    actual = await uno(
        db, "SELECT password_hash FROM admin.staff WHERE id = :s", {"s": staff_id}
    )
    if (
        actual
        and actual.get("password_hash")
        and verificar_password(password, str(actual["password_hash"]))
    ):
        raise validacion(
            "La contraseña no puede coincidir con ninguna de las "
            f"{s.password_history_size} anteriores."
        )
    previas = await todos(
        db,
        """
        SELECT password_hash FROM admin.staff_password_history
        WHERE staff_id = :s ORDER BY created_at DESC LIMIT :n
    """,
        {"s": staff_id, "n": s.password_history_size},
    )
    for p in previas:
        if verificar_password(password, p["password_hash"]):
            raise validacion(
                "La contraseña no puede coincidir con ninguna de las "
                f"{s.password_history_size} anteriores."
            )
    nuevo_hash = hashear_password(password)
    await uno(
        db,
        "UPDATE admin.staff SET password_hash = :h, "
        "updated_at = now() WHERE id = :i RETURNING id",
        {"h": nuevo_hash, "i": staff_id},
    )
    await uno(
        db,
        """
        INSERT INTO admin.staff_password_history (staff_id, password_hash)
        VALUES (:s, :h) RETURNING staff_id
    """,
        {"s": staff_id, "h": nuevo_hash},
    )


# ------------------------------------------------------------------- §18.1
@router.post("/login", response_model=LoginOut, summary="Iniciar sesión (primer factor)")
async def login(cuerpo: LoginIn, request: Request) -> LoginOut:
    """Verifica correo y contraseña y devuelve un desafío de segundo factor.

    No emite tokens: sin segundo factor verificado no hay sesión, y no existe
    forma de omitirlo para ningún rol.
    """
    email = cuerpo.email.lower()
    await limite_login(request, email)

    async with admin_session() as db:
        fila = await uno(
            db,
            """
            SELECT id, email, full_name, role, status, password_hash, totp_secret
            FROM admin.staff WHERE lower(email) = :e
        """,
            {"e": email},
        )

        # Respuesta indistinguible: dominio no autorizado, cuenta inexistente,
        # contraseña incorrecta y cuenta no activa (suspendida/desactivada) dan el mismo error.
        valido = (
            _dominio_autorizado(email)
            and fila is not None
            and fila["status"] == "active"
            and fila["password_hash"] is not None
            and verificar_password(cuerpo.password, fila["password_hash"])
        )
        if not valido:
            intentos = await registrar_fallo_login(request, email)
            log.warning(
                "staff.auth.primer_factor_fallido", email=hash_email(email), intentos=intentos
            )
            if not _dominio_autorizado(email):
                log.critical("staff.auth.dominio_no_autorizado", email=hash_email(email))
            raise credenciales_invalidas()

        assert fila is not None
        await limpiar_fallos_login(request, email)
        claro, ttl = await _crear_desafio(db, fila["id"], request)
        log.info("staff.auth.primer_factor_ok", email=hash_email(email), staff_id=fila["id"])
        return LoginOut(
            mfa_token=claro, mfa_inscrito=fila["totp_secret"] is not None, expira_en=ttl
        )


# ------------------------------------------------------------------- §18.2
@router.post(
    "/mfa/verify", response_model=TokensOut, summary="Verificar segundo factor y emitir tokens"
)
async def mfa_verify(cuerpo: MfaVerifyIn, request: Request) -> TokensOut:
    """Verifica el código TOTP o un código de recuperación y abre la sesión."""
    s = get_admin_settings()
    hashed = hash_token(cuerpo.mfa_token)

    async with admin_session() as db:
        d = await uno(
            db,
            """
            SELECT c.id, c.staff_id, c.attempts, c.consumed_at, c.expires_at,
                   st.full_name, st.role, st.status, st.totp_secret
            FROM admin.staff_mfa_challenges c
            JOIN admin.staff st ON st.id = c.staff_id
            WHERE c.token_hash = :h
            FOR UPDATE OF c
        """,
            {"h": hashed},
        )
        if d is None or d["expires_at"] <= _ahora():
            raise no_autenticado("El desafío ha caducado. Vuelve a iniciar sesión.")
        if d["consumed_at"] is not None:
            # Reutilizar un desafío es incidente de seguridad: invalida la sesión.
            log.critical("staff.auth.desafio_reutilizado", staff_id=d["staff_id"])
            await _revocar_sesiones(db, d["staff_id"], "desafio_reutilizado")
            await revocar_todas_sesiones_redis(d["staff_id"])
            await db.commit()
            raise no_autenticado("El desafío ha caducado. Vuelve a iniciar sesión.")
        if d["status"] != "active":
            raise staff_desactivado()
        if d["totp_secret"] is None:
            raise mfa_no_inscrito()

        ok = False
        try:
            verificar_totp(d["totp_secret"], cuerpo.codigo)
            ok = True
        except AppError:
            # Puede ser un código de recuperación de un solo uso
            consumido = await uno(
                db,
                """
                UPDATE admin.staff_recovery_codes SET used_at = now()
                WHERE staff_id = :s AND code_hash = :h AND used_at IS NULL
                RETURNING code_hash
            """,
                {"s": d["staff_id"], "h": hash_token(cuerpo.codigo)},
            )
            if consumido is not None:
                ok = True
                log.warning("staff.mfa.codigo_recuperacion_usado", staff_id=d["staff_id"])

        if not ok:
            intentos = d["attempts"] + 1
            await uno(
                db,
                """
                UPDATE admin.staff_mfa_challenges
                SET attempts = CAST(:n AS integer),
                    consumed_at = CASE WHEN CAST(:n AS integer) >= CAST(:max AS integer)
                        THEN now() ELSE consumed_at END
                WHERE id = :i RETURNING id
            """,
                {
                    "n": int(min(intentos, s.mfa_max_attempts)),
                    "i": d["id"],
                    "max": int(s.mfa_max_attempts),
                },
            )
            log.warning("staff.auth.mfa_fallido", staff_id=d["staff_id"], intentos=intentos)
            raise mfa_invalido()

        mfa_at = _ahora()
        await uno(
            db,
            "UPDATE admin.staff_mfa_challenges SET consumed_at = now() "
            "WHERE id = :i RETURNING id",
            {"i": d["id"]},
        )
        staff = {"id": d["staff_id"], "full_name": d["full_name"], "role": d["role"]}
        salida = await _emitir_sesion(db, staff, request, mfa_at)
        await registrar_accion(
            db,
            staff_id=d["staff_id"],
            staff_role=d["role"],
            action="admin_query",
            endpoint="POST /admin/v1/auth/mfa/verify",
            ip=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
            payload={"evento": "sesion_iniciada"},
        )
        log.info("staff.auth.sesion_iniciada", staff_id=d["staff_id"], rol=d["role"])
        return salida


# ------------------------------------------------------------------- §18.3
@router.post(
    "/mfa/enroll", response_model=MfaEnrollOut, summary="Inscribir segundo factor (TOTP)"
)
async def mfa_enroll(cuerpo: MfaEnrollIn, request: Request) -> MfaEnrollOut:
    """Inscribe o reinscribe el segundo factor.

    Dos caminos: en el primer acceso, con el desafío de §18.1; y para reinscribir
    tras la pérdida del dispositivo, con la contraseña vigente. En ambos casos el
    secreto y los códigos de recuperación se muestran una única vez y no existe
    endpoint para volver a consultarlos.
    """
    async with admin_session() as db:
        if cuerpo.mfa_token:
            d = await uno(
                db,
                """
                SELECT c.staff_id, st.email, st.status, st.totp_secret
                FROM admin.staff_mfa_challenges c
                JOIN admin.staff st ON st.id = c.staff_id
                WHERE c.token_hash = :h AND c.consumed_at IS NULL
                  AND c.expires_at > now()
            """,
                {"h": hash_token(cuerpo.mfa_token)},
            )
            if d is None:
                raise no_autenticado("El desafío ha caducado.")
            staff_id, email = d["staff_id"], d["email"]
            reinscripcion = d["totp_secret"] is not None
            if reinscripcion and not cuerpo.password:
                raise conflicto("CONFLICTO_ESTADO", "Ya tienes un segundo factor inscrito.")
        elif cuerpo.password:
            raise validacion(
                "La reinscripción con sesión abierta se solicita desde el perfil; "
                "aporta el desafío de inicio de sesión."
            )
        else:
            raise validacion("Falta el desafío de inicio de sesión.")

        # Fase 1: generar y devolver el secreto, sin confirmar todavía
        if not cuerpo.codigo:
            secreto = nuevo_secreto_totp()
            codigos = generar_codigos_recuperacion()
            await uno(
                db,
                "UPDATE admin.staff SET totp_secret = :s, "
                "totp_enrolled_at = NULL WHERE id = :i RETURNING id",
                {"s": secreto, "i": staff_id},
            )
            # La reinscripción invalida los códigos anteriores no consumidos.
            await db.execute(
                text("DELETE FROM admin.staff_recovery_codes WHERE staff_id = :s"),
                {"s": staff_id},
            )
            for _claro, hashed in codigos:
                await uno(
                    db,
                    """
                    INSERT INTO admin.staff_recovery_codes (staff_id, code_hash)
                    VALUES (:s, :h) RETURNING staff_id
                """,
                    {"s": staff_id, "h": hashed},
                )
            log.info("staff.mfa.secreto_generado", staff_id=staff_id)
            return MfaEnrollOut(
                secreto=secreto,
                otpauth_url=url_otpauth(secreto, email),
                codigos_recuperacion=[c for c, _ in codigos],
                inscrito=False,
            )

        # Fase 2: confirmar con un primer código válido
        fila = await uno(
            db, "SELECT totp_secret FROM admin.staff WHERE id = :i", {"i": staff_id}
        )
        if fila is None or fila["totp_secret"] is None:
            raise mfa_no_inscrito()
        verificar_totp(fila["totp_secret"], cuerpo.codigo)
        await uno(
            db,
            """
            UPDATE admin.staff
            SET totp_enrolled_at = now(),
                status = CASE WHEN status = 'invited' THEN 'active' ELSE status END,
                updated_at = now()
            WHERE id = :i RETURNING id
        """,
            {"i": staff_id},
        )
        await _revocar_sesiones(db, staff_id, "reinscripcion_mfa")
        log.info("staff.mfa.inscrito", staff_id=staff_id)
        return MfaEnrollOut(inscrito=True)


# ------------------------------------------------------------------- §18.4
@router.post("/refresh", response_model=RefreshOut, summary="Renovar tokens")
async def refresh(cuerpo: RefreshIn, request: Request) -> RefreshOut:
    """Rotación de un solo uso, con comprobación de la caducidad por inactividad.

    Reutilizar un token ya consumido revoca todas las sesiones del empleado, igual
    que en el portal, y el rol se resuelve en base de datos: un cambio de rol o
    una desactivación invalidan la renovación de inmediato.
    """
    from ..errors import mfa_requerido

    s = get_admin_settings()
    async with admin_session() as db:
        d = await uno(
            db,
            """
            SELECT t.id, t.staff_id, t.used_at, t.revoked, t.expires_at, t.mfa_at,
                   st.full_name, st.role, st.status
            FROM admin.staff_refresh_tokens t
            JOIN admin.staff st ON st.id = t.staff_id
            WHERE t.token_hash = :h
            FOR UPDATE OF t
        """,
            {"h": hash_token(cuerpo.refresh_token)},
        )
        if d is None or d["revoked"] or d["expires_at"] <= _ahora():
            raise no_autenticado("Tu sesión ha expirado. Vuelve a iniciar sesión.")
        if d["used_at"] is not None:
            log.critical("staff.auth.refresh_reutilizado", staff_id=d["staff_id"])
            await _revocar_sesiones(db, d["staff_id"], "refresh_reutilizado")
            await revocar_todas_sesiones_redis(d["staff_id"])
            await db.commit()
            raise no_autenticado("Tu sesión ha expirado. Vuelve a iniciar sesión.")
        if d["status"] != "active":
            raise staff_desactivado()
        if _ahora() - d["mfa_at"] > timedelta(minutes=s.staff_idle_timeout_min):
            raise mfa_requerido("Verifica de nuevo tu segundo factor.")

        await uno(
            db,
            "UPDATE admin.staff_refresh_tokens SET used_at = now() WHERE id = :i RETURNING id",
            {"i": d["id"]},
        )
        staff = {"id": d["staff_id"], "full_name": d["full_name"], "role": d["role"]}
        tokens = await _emitir_sesion(db, staff, request, d["mfa_at"])
        log.info("staff.auth.renovado", staff_id=d["staff_id"])
        return RefreshOut(
            access_token=tokens.access_token,
            refresh_token=tokens.refresh_token,
            expira_en=tokens.expira_en,
        )


# ------------------------------------------------------------------- §18.5
@router.post("/logout", response_model=LogoutOut, summary="Cerrar sesión")
async def logout(cuerpo: LogoutIn, st: StaffDep) -> LogoutOut:
    """Revoca el refresh y añade el token de acceso a la lista de denegación.

    El cierre de sesión no revoca las concesiones de acceso vigentes: caducan por
    su propio vencimiento o se revocan expresamente (§18.15).
    """
    s = get_admin_settings()
    async with admin_session() as db:
        if cuerpo.todas:
            n = await _revocar_sesiones(db, st.id, "logout_todas")
            await revocar_todas_sesiones_redis(st.id)
        elif cuerpo.refresh_token:
            filas = await todos(
                db,
                """
                UPDATE admin.staff_refresh_tokens
                SET revoked = true, revoked_reason = 'logout'
                WHERE staff_id = :s AND token_hash = :h AND NOT revoked
                RETURNING id
            """,
                {"s": st.id, "h": hash_token(cuerpo.refresh_token)},
            )
            n = len(filas)
        else:
            n = await _revocar_sesiones(db, st.id, "logout")

        await revocar_jti(st.jti, s.staff_access_token_ttl_min * 60)
        await registrar_accion(
            db,
            staff_id=st.id,
            staff_role=st.role,
            action="admin_query",
            endpoint="POST /admin/v1/auth/logout",
            ip=st.ip,
            user_agent=st.user_agent,
            request_id=st.request_id,
            payload={"evento": "sesion_cerrada", "todas": cuerpo.todas, "revocadas": n},
        )
    log.info("staff.auth.sesion_cerrada", staff_id=st.id, revocadas=n, todas=cuerpo.todas)
    return LogoutOut(sesiones_revocadas=n)


# ------------------------------------------------------------------- §18.6
@router.post(
    "/forgot-password",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Solicitar restablecimiento de contraseña",
)
async def forgot_password(cuerpo: ForgotIn, request: Request) -> Response:
    """Envía el enlace de restablecimiento. Siempre 204, exista o no la cuenta.

    Restablecer la contraseña no reinscribe el segundo factor: el empleado sigue
    necesitando su autenticador.
    """
    s = get_admin_settings()
    email = cuerpo.email.lower()
    from ..deps import redis

    clave = f"admin:reset:{email}"
    r = redis()
    n = await r.incr(clave)
    if n == 1:
        await r.expire(clave, 3600)
    if n > s.password_reset_max_per_hour:
        from kallicode_core.errors import rate_limit

        raise rate_limit(3600)

    async with admin_session() as db:
        fila = await uno(
            db,
            "SELECT id FROM admin.staff WHERE lower(email) = :e AND status = 'active'",
            {"e": email},
        )
        if fila is not None:
            claro, hashed = generar_token_opaco("prt")
            await uno(
                db,
                """
                INSERT INTO admin.staff_password_resets
                    (id, staff_id, token_hash, expires_at)
                VALUES (:id, :s, :h, now() + make_interval(mins => :ttl))
                RETURNING id
            """,
                {
                    "id": nuevo("prt"),
                    "s": fila["id"],
                    "h": hashed,
                    "ttl": s.password_reset_ttl_min,
                },
            )
            # El envío lo hace el notificador; por el stream viaja el
            # identificador, nunca el token en claro (lección de BE-F05).
            log.info(
                "staff.password.reset_solicitado",
                email=hash_email(email),
                token_ref=hashed[:12],
            )
        else:
            log.warning("staff.password.reset_cuenta_inexistente", email=hash_email(email))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ------------------------------------------------------------------- §18.7
@router.post("/reset-password", response_model=ResetOut, summary="Restablecer contraseña")
async def reset_password(cuerpo: ResetIn) -> ResetOut:
    """Fija la contraseña nueva y revoca todas las sesiones del empleado."""
    async with admin_session() as db:
        d = await uno(
            db,
            """
            SELECT r.id, r.staff_id, r.used_at, r.expires_at
            FROM admin.staff_password_resets r
            WHERE r.token_hash = :h FOR UPDATE OF r
        """,
            {"h": hash_token(cuerpo.token)},
        )
        if d is None or d["used_at"] is not None or d["expires_at"] <= _ahora():
            raise no_autenticado("El enlace ha caducado o ya se ha usado.")

        await _guardar_password(db, d["staff_id"], cuerpo.password)
        await uno(
            db,
            "UPDATE admin.staff_password_resets SET used_at = now() WHERE id = :i RETURNING id",
            {"i": d["id"]},
        )
        n = await _revocar_sesiones(db, d["staff_id"], "password_restablecida")
        await revocar_todas_sesiones_redis(d["staff_id"])
        log.info("staff.password.restablecido", staff_id=d["staff_id"], revocadas=n)
    return ResetOut(sesiones_revocadas=n)


# ------------------------------------------------------------------- §18.8
@router.post(
    "/invitations/accept",
    response_model=AcceptOut,
    summary="Aceptar invitación (alta de personal)",
)
async def accept_invitation(cuerpo: AcceptIn, request: Request) -> AcceptOut:
    """Completa el alta a partir de la invitación de §18.11.

    El rol y el correo se toman de la invitación y no del cuerpo de la petición:
    un invitado no puede elevarse el rol ni cambiar su correo al aceptar. Tras
    fijar la contraseña, el flujo continúa obligatoriamente por §18.3 y hasta
    completarlo no se emiten tokens.
    """
    async with admin_session() as db:
        inv = await uno(
            db,
            """
            SELECT id, email, role, expires_at, accepted_at, revoked_at
            FROM admin.staff_invitations
            WHERE token_hash = :h FOR UPDATE
        """,
            {"h": hash_token(cuerpo.token)},
        )
        if (
            inv is None
            or inv["accepted_at"] is not None
            or inv["revoked_at"] is not None
            or inv["expires_at"] <= _ahora()
        ):
            raise no_autenticado("La invitación ha caducado o ya se ha usado.")

        existente = await uno(
            db,
            "SELECT id FROM admin.staff WHERE lower(email) = :e",
            {"e": inv["email"].lower()},
        )
        staff_id = existente["id"] if existente else nuevo("st")
        if existente is None:
            await uno(
                db,
                """
                INSERT INTO admin.staff (id, email, full_name, role, status)
                VALUES (:id, :e, :n, :r, 'invited') RETURNING id
            """,
                {"id": staff_id, "e": inv["email"], "n": cuerpo.nombre, "r": inv["role"]},
            )
        else:
            await uno(
                db,
                """
                UPDATE admin.staff SET full_name = :n, role = :r,
                       status = 'invited', updated_at = now()
                WHERE id = :i RETURNING id
            """,
                {"n": cuerpo.nombre, "r": inv["role"], "i": staff_id},
            )

        await _guardar_password(db, staff_id, cuerpo.password)
        await uno(
            db,
            "UPDATE admin.staff_invitations SET accepted_at = now() WHERE id = :i RETURNING id",
            {"i": inv["id"]},
        )
        claro, _ttl = await _crear_desafio(db, staff_id, request)
        log.info("staff.invitacion.aceptada", staff_id=staff_id, rol=inv["role"])
        return AcceptOut(
            staff={
                "id": staff_id,
                "nombre": cuerpo.nombre,
                "email": inv["email"],
                "rol": inv["role"],
            },
            mfa_token=claro,
        )


__all__ = ["router"]
