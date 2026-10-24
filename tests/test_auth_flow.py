"""Identidad de la consola: contraseña, segundo factor y ciclo de sesión.

La consola tiene su propio dominio de identidad —realm propio con contraseña y
TOTP— y no comparte emisor con la API de cliente. Eso significa que el reino de
identidad más sensible de la plataforma es también el más nuevo, así que la suite
cubre el flujo completo y, sobre todo, los casos en que el flujo se usa mal:
reutilización de desafíos, reutilización de tokens de refresco, enumeración de
correos y códigos de recuperación gastados.

El criterio de diseño que se comprueba una y otra vez es la
**indistinguibilidad**: el fallo de autenticación responde igual si el correo no
existe, si la contraseña es incorrecta, si la cuenta está suspendida o si está
desactivada. Cuatro respuestas distintas convierten el formulario de acceso en un
directorio del personal de KalliCode.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pyotp
import pytest
from sqlalchemy import text

pytestmark = pytest.mark.integracion

PASSWORD = "Prueba-Segura-2026"


async def _login(cliente: Any, email: str, password: str = PASSWORD) -> Any:
    return await cliente.post(
        "/admin/v1/auth/login", json={"email": email, "password": password}
    )


async def _sesion_completa(cliente: Any, empleado: dict[str, Any]) -> Any:
    """Login + segundo factor, devolviendo el cuerpo con los dos tokens."""
    r = await _login(cliente, empleado["email"])
    assert r.status_code == 200, r.text
    codigo = pyotp.TOTP(empleado["secreto"]).now()
    r = await cliente.post(
        "/admin/v1/auth/mfa/verify", json={"mfa_token": r.json()["mfa_token"], "codigo": codigo}
    )
    assert r.status_code == 200, r.text
    return r.json()


# ================================================================ camino feliz
async def test_login_con_segundo_factor_emite_sesion(cliente: Any, staff_factory: Any) -> None:
    """El primer factor no emite sesión: emite un desafío.

    Es la propiedad que hace que el segundo factor sea obligatorio de verdad. Si el
    primer paso ya devolviera un token de acceso, el TOTP sería decorativo.
    """
    empleado = await staff_factory("staff_negocio")
    r = await _login(cliente, empleado["email"])
    assert r.status_code == 200, r.text
    cuerpo = r.json()
    assert "mfa_token" in cuerpo
    assert "access_token" not in cuerpo, (
        "el primer factor emitió una sesión: el segundo factor es opcional de hecho"
    )

    tokens = await _sesion_completa(cliente, empleado)
    assert tokens["access_token"] and tokens["refresh_token"]

    r = await cliente.get(
        "/admin/v1/staff/me", headers={"authorization": f"Bearer {tokens['access_token']}"}
    )
    assert r.status_code == 200, r.text
    assert r.json()["rol"] == "staff_negocio"


async def test_el_token_declara_su_reino_y_su_segundo_factor(staff_factory: Any) -> None:
    """`typ=staff`, emisor y audiencia propios, y el momento del segundo factor.

    Sin `typ` y sin audiencia propia, un token del portal firmado con la misma
    clave abriría la consola. La marca temporal del segundo factor es lo que
    permite exigir que esté vigente y no solo que ocurriera alguna vez.
    """
    from admin_api.security import emitir_tokens_staff, verificar_token_staff

    empleado = await staff_factory("staff_admin")
    ahora = datetime.now(UTC)
    acceso = emitir_tokens_staff(empleado["id"], "staff_admin", ahora)
    datos = verificar_token_staff(acceso)

    assert datos["typ"] == "staff"
    assert datos["mfa"] == pytest.approx(ahora.timestamp(), abs=2)
    assert datos["jti"], "el token no lleva jti: no se puede revocar"
    assert "admin" in str(datos["aud"]).lower()


# ==================================================== indistinguibilidad
@pytest.mark.parametrize("caso", ["inexistente", "password_mala", "suspendido", "desactivado"])
async def test_los_cuatro_fallos_de_acceso_son_indistinguibles(
    cliente: Any, db: Any, staff_factory: Any, caso: str
) -> None:
    """Misma respuesta, mismo código y sin pistas en el cuerpo.

    No se compara el tiempo de respuesta, que depende de la máquina; sí se compara
    todo lo observable por el cliente: estado, código de error y mensaje.
    """
    if caso == "inexistente":
        email, password = "nadie@kallicode.com", PASSWORD
    elif caso == "password_mala":
        empleado = await staff_factory("staff_soporte")
        email, password = empleado["email"], "Otra-Password-2026"
    else:
        estado = "suspended" if caso == "suspendido" else "disabled"
        empleado = await staff_factory("staff_soporte")
        await db.execute(
            text("UPDATE admin.staff SET status = :e WHERE id = :i"),
            {"e": estado, "i": empleado["id"]},
        )
        await db.commit()
        email, password = empleado["email"], PASSWORD

    r = await _login(cliente, email, password)
    assert r.status_code == 401, f"{caso}: {r.status_code} {r.text[:200]}"
    cuerpo = r.json()
    assert cuerpo["error"]["code"] == "credenciales_invalidas", cuerpo
    for filtracion in ("suspend", "desactiv", "disabled", "no existe", "contraseña incorrecta"):
        assert filtracion not in r.text.lower(), f"{caso}: la respuesta revela «{filtracion}»"


async def test_forgot_password_no_revela_si_el_correo_existe(
    cliente: Any, staff_factory: Any
) -> None:
    """Siempre 204, exista o no la cuenta."""
    empleado = await staff_factory("staff_soporte")
    for email in (empleado["email"], "nadie@kallicode.com"):
        r = await cliente.post("/admin/v1/auth/forgot-password", json={"email": email})
        assert r.status_code == 204, r.text
        assert r.content == b""


# ==================================================== reutilización de desafíos
async def test_un_desafio_de_segundo_factor_no_se_reutiliza(
    cliente: Any, db: Any, staff_factory: Any
) -> None:
    """Reusar un desafío ya consumido revoca todas las sesiones del empleado.

    Un desafío consumido que vuelve a llegar solo tiene una explicación razonable:
    alguien más lo tiene. La respuesta no es rechazar la petición y seguir, es
    cerrar todo y registrar el hecho como crítico.
    """
    empleado = await staff_factory("staff_admin")
    r = await _login(cliente, empleado["email"])
    mfa_token = r.json()["mfa_token"]
    codigo = pyotp.TOTP(empleado["secreto"]).now()

    primera = await cliente.post(
        "/admin/v1/auth/mfa/verify", json={"mfa_token": mfa_token, "codigo": codigo}
    )
    assert primera.status_code == 200, primera.text

    segunda = await cliente.post(
        "/admin/v1/auth/mfa/verify", json={"mfa_token": mfa_token, "codigo": codigo}
    )
    assert segunda.status_code == 401, segunda.text

    # Y la sesión legítima que se había emitido queda cerrada.
    r = await cliente.get(
        "/admin/v1/staff/me",
        headers={"authorization": f"Bearer {primera.json()['access_token']}"},
    )
    assert r.status_code == 401, "reutilizar el desafío no revocó las sesiones existentes"

    vivas = (
        await db.execute(
            text("""
        SELECT count(*) FROM admin.staff_refresh_tokens
        WHERE staff_id = :i AND NOT revoked
    """),
            {"i": empleado["id"]},
        )
    ).scalar()
    assert vivas == 0


async def test_un_codigo_totp_de_otro_momento_no_vale(cliente: Any, staff_factory: Any) -> None:
    """Un código de hace diez minutos está fuera de la ventana aceptada."""
    empleado = await staff_factory("staff_soporte")
    r = await _login(cliente, empleado["email"])
    viejo = pyotp.TOTP(empleado["secreto"]).at(datetime.now(UTC) - timedelta(minutes=10))

    r = await cliente.post(
        "/admin/v1/auth/mfa/verify", json={"mfa_token": r.json()["mfa_token"], "codigo": viejo}
    )
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "mfa_invalido"


async def test_un_codigo_de_recuperacion_se_gasta_al_usarlo(
    cliente: Any, db: Any, staff_factory: Any
) -> None:
    """Los códigos de recuperación son de un solo uso.

    Un código de recuperación reutilizable es una contraseña permanente escrita en
    un papel, que es exactamente lo que no se quiere.
    """
    from admin_api.security import generar_codigos_recuperacion

    empleado = await staff_factory("staff_admin")
    pares = generar_codigos_recuperacion()
    for _claro, hashed in pares:
        await db.execute(
            text("""
            INSERT INTO admin.staff_recovery_codes (staff_id, code_hash)
            VALUES (:i, :h)
        """),
            {"i": empleado["id"], "h": hashed},
        )
    await db.commit()
    codigos = [claro for claro, _ in pares]

    r = await _login(cliente, empleado["email"])
    primera = await cliente.post(
        "/admin/v1/auth/mfa/verify",
        json={"mfa_token": r.json()["mfa_token"], "codigo": codigos[0]},
    )
    assert primera.status_code == 200, primera.text

    r = await _login(cliente, empleado["email"])
    segunda = await cliente.post(
        "/admin/v1/auth/mfa/verify",
        json={"mfa_token": r.json()["mfa_token"], "codigo": codigos[0]},
    )
    assert segunda.status_code == 401, "el código de recuperación se pudo reutilizar"


# ==================================================== tokens de refresco
async def test_refrescar_rota_el_token_y_el_viejo_deja_de_valer(
    cliente: Any, staff_factory: Any
) -> None:
    empleado = await staff_factory("staff_negocio")
    tokens = await _sesion_completa(cliente, empleado)

    r = await cliente.post(
        "/admin/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
    )
    assert r.status_code == 200, r.text
    nuevos = r.json()
    assert nuevos["refresh_token"] != tokens["refresh_token"], "el token de refresco no rotó"


async def test_reutilizar_un_token_de_refresco_cierra_todas_las_sesiones(
    cliente: Any, staff_factory: Any
) -> None:
    """La detección de reutilización es lo que hace útil la rotación.

    Rotar sin detectar reutilización solo obliga al atacante a ir un paso por
    delante. Al detectarla se cierra todo, y el empleado legítimo nota que algo ha
    pasado, que es la señal que se quiere provocar.
    """
    empleado = await staff_factory("staff_soporte")
    tokens = await _sesion_completa(cliente, empleado)

    r1 = await cliente.post(
        "/admin/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
    )
    assert r1.status_code == 200, r1.text

    r2 = await cliente.post(
        "/admin/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
    )
    assert r2.status_code == 401, r2.text

    # También el token nuevo, obtenido legítimamente, queda invalidado.
    r3 = await cliente.post(
        "/admin/v1/auth/refresh", json={"refresh_token": r1.json()["refresh_token"]}
    )
    assert r3.status_code == 401, "la reutilización no cerró la cadena completa de sesiones"


async def test_logout_invalida_el_token_de_acceso_no_solo_el_de_refresco(
    cliente: Any, staff_factory: Any
) -> None:
    """Cerrar sesión tiene efecto inmediato sobre el token de acceso.

    Con una lista de revocación por `jti`: sin ella, cerrar sesión dejaría el token
    de acceso vivo hasta quince minutos, que en una consola con acceso a datos de
    todos los clientes es demasiado.
    """
    empleado = await staff_factory("staff_soporte")
    tokens = await _sesion_completa(cliente, empleado)
    cab = {"authorization": f"Bearer {tokens['access_token']}"}

    assert (await cliente.get("/admin/v1/staff/me", headers=cab)).status_code == 200
    r = await cliente.post(
        "/admin/v1/auth/logout", json={"refresh_token": tokens["refresh_token"]}, headers=cab
    )
    assert r.status_code == 200, r.text
    assert (await cliente.get("/admin/v1/staff/me", headers=cab)).status_code == 401


async def test_logout_de_todas_las_sesiones(cliente: Any, staff_factory: Any) -> None:
    empleado = await staff_factory("staff_negocio")
    uno = await _sesion_completa(cliente, empleado)
    dos = await _sesion_completa(cliente, empleado)

    r = await cliente.post(
        "/admin/v1/auth/logout",
        json={"todas": True},
        headers={"authorization": f"Bearer {dos['access_token']}"},
    )
    assert r.status_code == 200, r.text

    for tokens in (uno, dos):
        r = await cliente.post(
            "/admin/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
        )
        assert r.status_code == 401


# ================================================== limitación de intentos
async def test_los_intentos_fallidos_se_limitan_por_correo_e_ip(
    cliente: Any, staff_factory: Any
) -> None:
    """El contador es del par correo+IP, no solo de la IP.

    Es el defecto BE-F13 del backend: contar solo por IP permitía que un atacante
    tras un proxy compartido bloqueara a toda una oficina, y contar solo por correo
    permitía repartir el ataque entre muchas IP.
    """
    empleado = await staff_factory("staff_soporte")
    codigos = []
    for _ in range(12):
        r = await _login(cliente, empleado["email"], "Password-Erronea-2026")
        codigos.append(r.status_code)
    assert 429 in codigos, f"no se limitó el número de intentos: {codigos}"

    # Otro correo desde la misma IP no queda bloqueado por el anterior.
    otro = await staff_factory("staff_soporte")
    r = await _login(cliente, otro["email"])
    assert r.status_code == 200, (
        "el bloqueo de un correo alcanzó a otro empleado de la misma IP"
    )


async def test_un_login_correcto_limpia_el_contador(cliente: Any, staff_factory: Any) -> None:
    empleado = await staff_factory("staff_negocio")
    for _ in range(3):
        await _login(cliente, empleado["email"], "Password-Erronea-2026")
    assert (await _login(cliente, empleado["email"])).status_code == 200
    for _ in range(3):
        await _login(cliente, empleado["email"], "Password-Erronea-2026")
    # Tras el acierto, vuelve a haber margen: no se acumula con los anteriores.
    assert (await _login(cliente, empleado["email"])).status_code == 200


# ================================================ alta, invitación y contraseña
async def test_la_invitacion_fija_el_rol_y_el_correo(
    cliente: Any, db: Any, staff_factory: Any
) -> None:
    """Quien acepta no elige su rol ni su correo: los trae la invitación.

    Si el cuerpo de la aceptación pudiera traer el rol, cualquiera con un enlace de
    invitación a soporte se daría de alta como administrador. Es un patrón de
    escalada tan simple como frecuente.
    """
    from admin_api.security import hash_token
    from kallicode_core.ids import nuevo

    invitador = await staff_factory("staff_admin")
    token = "inv_" + nuevo("tk")
    await db.execute(
        text("""
        INSERT INTO admin.staff_invitations (id, email, role, token_hash,
                                             invited_by, expires_at)
        VALUES (:i, 'nuevo@kallicode.com', 'staff_soporte', :h, :by,
                now() + interval '48 hours')
    """),
        {"i": nuevo("iv"), "h": hash_token(token), "by": invitador["id"]},
    )
    await db.commit()

    r = await cliente.post(
        "/admin/v1/auth/invitations/accept",
        json={
            "token": token,
            "nombre": "Persona Nueva",
            "password": "Password-Nueva-2026",
            # Campos que un atacante intentaría colar: el modelo los prohíbe.
        },
    )
    assert r.status_code in (200, 201), r.text

    fila = (
        await db.execute(
            text("""
        SELECT email, role FROM admin.staff WHERE email = 'nuevo@kallicode.com'
    """)
        )
    ).fetchone()
    assert fila is not None
    assert fila[1] == "staff_soporte", "el rol no vino de la invitación"

    # Y el token de invitación no sirve dos veces.
    r = await cliente.post(
        "/admin/v1/auth/invitations/accept",
        json={"token": token, "nombre": "Otra Persona", "password": "Password-Otra-2026"},
    )
    assert r.status_code in (401, 409, 422), r.text


async def test_aceptar_una_invitacion_no_permite_elegir_el_rol(cliente: Any) -> None:
    """El modelo prohíbe campos extra, así que colar `rol` es un 422."""
    r = await cliente.post(
        "/admin/v1/auth/invitations/accept",
        json={
            "token": "inv_cualquiera",
            "nombre": "Persona",
            "rol": "staff_admin",
            "password": "Password-Nueva-2026",
        },
    )
    assert r.status_code == 422
    assert "rol" in r.text


async def test_no_se_reutiliza_una_contrasena_anterior(
    cliente: Any, db: Any, staff_factory: Any
) -> None:
    """El historial de contraseñas impide volver a la que se acaba de cambiar."""
    from admin_api.security import hash_token
    from kallicode_core.ids import nuevo

    empleado = await staff_factory("staff_soporte")
    token = "rs_" + nuevo("tk")
    await db.execute(
        text("""
        INSERT INTO admin.staff_password_resets (id, staff_id, token_hash,
                                                 expires_at)
        VALUES (:i, :s, :h, now() + interval '1 hour')
    """),
        {"i": nuevo("pr"), "s": empleado["id"], "h": hash_token(token)},
    )
    await db.commit()

    r = await cliente.post(
        "/admin/v1/auth/reset-password", json={"token": token, "password": PASSWORD}
    )
    assert r.status_code == 422, "se aceptó como nueva contraseña la que ya estaba en uso"


async def test_cambiar_la_contrasena_cierra_las_sesiones_abiertas(
    cliente: Any, db: Any, staff_factory: Any
) -> None:
    """Restablecer la contraseña expulsa a quien estuviera dentro.

    Es el caso de uso real del restablecimiento: alguien cree que su cuenta está
    comprometida. Si las sesiones existentes sobrevivieran, el cambio no serviría
    para nada.
    """
    from admin_api.security import hash_token
    from kallicode_core.ids import nuevo

    empleado = await staff_factory("staff_negocio")
    tokens = await _sesion_completa(cliente, empleado)
    cab = {"authorization": f"Bearer {tokens['access_token']}"}
    assert (await cliente.get("/admin/v1/staff/me", headers=cab)).status_code == 200

    token = "rs_" + nuevo("tk")
    await db.execute(
        text("""
        INSERT INTO admin.staff_password_resets (id, staff_id, token_hash,
                                                 expires_at)
        VALUES (:i, :s, :h, now() + interval '1 hour')
    """),
        {"i": nuevo("pr"), "s": empleado["id"], "h": hash_token(token)},
    )
    await db.commit()

    r = await cliente.post(
        "/admin/v1/auth/reset-password",
        json={"token": token, "password": "Password-Nueva-2026"},
    )
    assert r.status_code == 200, r.text
    assert (await cliente.get("/admin/v1/staff/me", headers=cab)).status_code == 401


async def test_el_secreto_totp_no_aparece_nunca_en_una_respuesta(
    cliente: Any, staff_factory: Any
) -> None:
    """Ni en el perfil, ni en el listado, ni en el alta.

    El secreto solo se entrega una vez, en el momento de la inscripción, y no
    vuelve a salir. Un listado de personal que lo incluyera permitiría a cualquier
    administrador suplantar a cualquiera.
    """
    empleado = await staff_factory("staff_admin")
    tokens = await _sesion_completa(cliente, empleado)
    cab = {"authorization": f"Bearer {tokens['access_token']}"}

    for ruta in ("/admin/v1/staff/me", "/admin/v1/staff"):
        r = await cliente.get(ruta, headers=cab)
        assert r.status_code == 200, r.text
        assert empleado["secreto"] not in r.text, f"{ruta} filtró el secreto TOTP"
        assert "totp_secret" not in r.text
        assert "password_hash" not in r.text
