"""Pruebas unitarias y de integración para KC-ADM-B6-06 (ADM-G04).

Cubre la migración e integración de auditoría de personal hacia la cadena
central del tenant (`audit.audit_events` y `audit.chain_heads`):
  - Modelo canónico (`actor.typ = "staff"`, motivo, recurso, timestamp UTC)
  - Sellado SHA-256 encadenado determinista: SHA-256(sello_n-1 || canonico(evento_n))
  - Política no-fuga en payload/metadata antes del sellado
  - Detección determinista de tampering en eventos intermedios y chain_heads
  - Regla anti-deadlock: reutilización de sesión `db` sin anidar `admin_session()`
  - Migración histórica idempotente desde `admin.staff_actions` sin pérdida ni mutación
  - Privilegios mínimos append-only en PostgreSQL real
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from admin_api.audit import (
    calcular_sello_cadena_central,
    construir_evento_canonico_staff,
    migrar_historico_staff_a_cadena_central,
    registrar_accion,
    registrar_lectura,
    sanitizar_metadata_auditoria,
    serializar_evento_canonico,
    validar_payload_sin_fuga,
    verificar_cadena_central_tenant,
    verificar_eventos_centrales_en_memoria,
)
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, InternalError, ProgrammingError
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool


# =========================================================================
# 1. Pruebas unitarias rápidas (sin BD)
# =========================================================================
def test_evento_canonico_exige_actor_typ_staff_tenant_y_motivo() -> None:
    """Valida los campos obligatorios del modelo canónico de evento staff."""
    ev = construir_evento_canonico_staff(
        tenant_id="org_acme",
        staff_id="st_01JXYZ",
        staff_role="staff_soporte",
        action="reveal",
        endpoint="GET /admin/v1/business/customers/org_acme",
        reason="Revisión de incidencia KC-4001 autorizada por el cliente",
        resource="customer:org_acme",
        scope="expediente",
        grant_id="gr_01JXYZ",
        request_id="tr_123",
        occurred_at="2026-11-25T20:20:00+00:00",
        staff_action_id=42,
        staff_action_seal="a" * 64,
        metadata={"bloques_revelados": ["identificacion", "usuarios"]},
    )
    assert ev["actor"] == {"typ": "staff", "staff_id": "st_01JXYZ", "rol": "staff_soporte"}
    assert ev["tenant_id"] == "org_acme"
    assert ev["resource"] == "customer:org_acme"
    assert ev["occurred_at"] == "2026-11-25T20:20:00.000000Z"

    with pytest.raises(ValueError, match="actor.typ"):
        construir_evento_canonico_staff(
            tenant_id="org_acme",
            staff_id="st_01",
            staff_role="staff_soporte",
            action="read",
            endpoint="GET /x",
            reason="Motivo válido",
            actor_typ="humano",
        )

    with pytest.raises(ValueError, match="tenant_id"):
        construir_evento_canonico_staff(
            tenant_id="",
            staff_id="st_01",
            staff_role="staff_soporte",
            action="read",
            endpoint="GET /x",
            reason="Motivo válido",
        )

    with pytest.raises(ValueError, match="reason"):
        construir_evento_canonico_staff(
            tenant_id="org_acme",
            staff_id="st_01",
            staff_role="staff_soporte",
            action="read",
            endpoint="GET /x",
            reason="   ",
        )


def test_serializacion_canonica_y_sha256_encadenado_determinista() -> None:
    """Verifica SHA-256(sello_n-1 || canonico(evento_n)) y orden determinista."""
    ev_a = construir_evento_canonico_staff(
        tenant_id="org_acme",
        staff_id="st_01",
        staff_role="staff_negocio",
        action="read",
        endpoint="GET /admin/v1/business/customers/org_acme",
        reason="Soporte caso KC-100",
        occurred_at=datetime(2026, 11, 25, 18, 0, 0, tzinfo=UTC),
        metadata={"b": 2, "a": 1},
    )
    ev_b = construir_evento_canonico_staff(
        tenant_id="org_acme",
        staff_id="st_01",
        staff_role="staff_negocio",
        action="read",
        endpoint="GET /admin/v1/business/customers/org_acme",
        reason="Soporte caso KC-100",
        occurred_at="2026-11-25T18:00:00.000000Z",
        metadata={"a": 1, "b": 2},
    )

    canon_a = serializar_evento_canonico(ev_a)
    canon_b = serializar_evento_canonico(ev_b)
    assert canon_a == canon_b

    prev = "0" * 64
    sello_1 = calcular_sello_cadena_central(prev, ev_a)
    esperado_1 = hashlib.sha256((prev + canon_a).encode("utf-8")).hexdigest()
    assert sello_1 == esperado_1
    assert len(sello_1) == 64

    ev_2 = construir_evento_canonico_staff(
        tenant_id="org_acme",
        staff_id="st_01",
        staff_role="staff_negocio",
        action="reveal",
        endpoint="GET /admin/v1/business/customers/org_acme",
        reason="Revelación expediente KC-100",
        occurred_at="2026-11-25T18:05:00.000000Z",
    )
    sello_2 = calcular_sello_cadena_central(sello_1, ev_2)
    assert sello_2 != calcular_sello_cadena_central(prev, ev_2)


def test_politica_no_fuga_rechaza_y_sanea_claves_sensibles() -> None:
    """Claves de código fuente, secretos o PII en claro no se sellan en payload."""
    for clave in ("contenido_codigo", "source_code", "password", "totp_secret", "token"):
        with pytest.raises(ValueError, match="clave sensible prohibida"):
            validar_payload_sin_fuga({"detalle": {clave: "secreto-no-filtrar"}})

        with pytest.raises(ValueError, match="clave sensible prohibida"):
            construir_evento_canonico_staff(
                tenant_id="org_acme",
                staff_id="st_01",
                staff_role="staff_soporte",
                action="read",
                endpoint="GET /x",
                reason="Soporte técnico",
                metadata={clave: "valor"},
            )

    saneado = sanitizar_metadata_auditoria(
        {
            "bloques_revelados": ["identificacion"],
            "contenido_codigo": "SELECT * FROM secret;",
            "contacto": "ana.garcia@cliente.es",
        }
    )
    assert "contenido_codigo" not in saneado
    assert saneado["bloques_revelados"] == ["identificacion"]
    assert "ana.garcia@" not in saneado["contacto"]
    assert saneado["contacto"].startswith("a***@")


def test_verificar_eventos_centrales_detecta_tampering_y_desincronia_head() -> None:
    """Detecta alteración de evento intermedio, omisión de eslabón y head manipulado."""
    genesis = "0" * 64
    eventos: list[dict[str, Any]] = []
    prev = genesis

    for idx in range(3):
        canon = construir_evento_canonico_staff(
            tenant_id="org_acme",
            staff_id="st_01",
            staff_role="staff_soporte",
            action="read",
            endpoint=f"GET /admin/v1/business/customers/org_acme?i={idx}",
            reason=f"Caso SUP-10{idx}",
            occurred_at=f"2026-11-25T10:0{idx}:00.000000Z",
            staff_action_id=idx + 1,
            staff_action_seal=f"{idx + 1:064x}",
        )
        c_seal = calcular_sello_cadena_central(prev, canon)
        sello_ev = hashlib.sha256(f"{prev}|{idx}|{c_seal}".encode()).hexdigest()
        datos = {
            **canon,
            "canonical_prev_seal": prev,
            "canonical_seal": c_seal,
        }
        eventos.append(
            {
                "id": idx + 1,
                "tenant_id": "org_acme",
                "actor_tipo": "staff",
                "actor_id": "st_01",
                "evento": "staff_read",
                "resumen": f"Acceso de personal (staff_soporte): Caso SUP-10{idx}",
                "datos": datos,
                "sello_previo": prev,
                "sello": sello_ev,
                "creado_en": f"2026-11-25T10:0{idx}:00Z",
            }
        )
        prev = sello_ev

    head_ok = {"tenant_id": "org_acme", "ultimo_sello": prev, "eventos": 3}
    assert verificar_eventos_centrales_en_memoria(eventos, head_ok).integra is True

    # 1. Alteración de motivo en evento intermedio (sin tocar canonical_seal)
    ev_alterados = json.loads(json.dumps(eventos))
    ev_alterados[1]["datos"]["reason"] = "Motivo falsificado"
    res_mod = verificar_eventos_centrales_en_memoria(ev_alterados, head_ok)
    assert res_mod.integra is False
    assert res_mod.primer_evento_roto is not None
    assert res_mod.primer_evento_roto["broken_id"] == 2

    # 2. Eliminación de evento intermedio
    res_del = verificar_eventos_centrales_en_memoria([eventos[0], eventos[2]], head_ok)
    assert res_del.integra is False
    assert res_del.primer_evento_roto is not None
    assert res_del.primer_evento_roto["broken_id"] == 3

    # 3. Desincronización de chain_heads.ultimo_sello
    head_mal = {"tenant_id": "org_acme", "ultimo_sello": "f" * 64, "eventos": 3}
    res_head = verificar_eventos_centrales_en_memoria(eventos, head_mal)
    assert res_head.integra is False


async def test_anti_deadlock_reutiliza_sesion_db_sin_anidar_admin_session() -> None:
    """Ninguna función de auditoría o migración abre una segunda `admin_session()`."""
    db_mock = AsyncMock()
    fila_sa = {
        "id": 99,
        "occurred_at": datetime(2026, 11, 25, 12, 0, tzinfo=UTC),
        "seal": "a" * 64,
    }
    err_sesion = AssertionError("admin_session prohibida")

    with (
        patch("admin_api.db.admin_session", side_effect=err_sesion),
        patch("admin_api.audit.uno", side_effect=[fila_sa, None, None]) as mock_uno,
    ):
        sello = await registrar_accion(
            db_mock,
            staff_id="st_01",
            staff_role="staff_soporte",
            action="read",
            endpoint="GET /admin/v1/business/customers/org_acme",
            tenant_id="org_acme",
            reason="Caso KC-1",
        )
        assert sello == "a" * 64
        assert mock_uno.await_count >= 2

    with (
        patch("admin_api.db.admin_session", side_effect=err_sesion),
        patch("admin_api.audit.uno", side_effect=[fila_sa, None, {"id": "gr_1"}]),
    ):
        sello_lect = await registrar_lectura(
            db_mock,
            staff_id="st_01",
            staff_role="staff_soporte",
            endpoint="GET /admin/v1/business/customers/org_acme",
            tenant_id="org_acme",
            grant_id="gr_1",
            scope="datos_negocio",
            reason="Caso KC-1",
        )
        assert sello_lect == "a" * 64

    with (
        patch("admin_api.db.admin_session", side_effect=err_sesion),
        patch(
            "admin_api.audit.uno",
            return_value={"tiene_eventos": False, "tiene_cabezas": False},
        ),
    ):
        res_mig = await migrar_historico_staff_a_cadena_central(db_mock)
        assert res_mig == {"procesados": 0, "migrados": 0, "omitidos": 0}


# =========================================================================
# 2. Pruebas de integración con PostgreSQL real
# =========================================================================
@pytest.mark.integracion
async def test_migracion_005_privilegios_y_politicas_append_only(db: Any, db_ro: Any) -> None:
    """Verifica permisos append-only en audit.audit_events, RLS y roles de consola."""
    fallos = (await db.execute(text("SELECT * FROM admin.validate_read_role()"))).fetchall()
    fallos_permisos = [f for f in fallos if f[0] != "V6_cadena_integra"]
    assert (
        fallos_permisos == []
    ), f"validate_read_role reportó fallos tras 005: {fallos_permisos}"

    # kallicode_admin_app solo puede insertar actor_tipo = 'staff' (bloqueado por RLS)
    with pytest.raises((ProgrammingError, InternalError, DBAPIError)):
        await db.execute(
            text(
                """
            INSERT INTO audit.audit_events
                (tenant_id, actor_tipo, actor_id, evento, resumen, sello_previo, sello)
            VALUES ('org_acme', 'humano', 'usr_fake', 'login', 'x', '', :s)
        """
            ),
            {"s": "b" * 64},
        )
    await db.rollback()

    # kallicode_admin_app no puede mutar ni borrar eventos centrales
    with pytest.raises((ProgrammingError, InternalError, DBAPIError)):
        await db.execute(text("UPDATE audit.audit_events SET resumen = 'x'"))
    await db.rollback()

    with pytest.raises((ProgrammingError, InternalError, DBAPIError)):
        await db.execute(text("DELETE FROM audit.audit_events"))
    await db.rollback()

    # kallicode_admin_ro puede consultar audit_events pero jamás escribir
    res_ro = await db_ro.execute(text("SELECT count(*) FROM audit.audit_events"))
    assert res_ro.scalar_one() >= 0

    with pytest.raises((ProgrammingError, InternalError, DBAPIError)):
        await db_ro.execute(
            text(
                """
            INSERT INTO audit.audit_events
                (tenant_id, actor_tipo, actor_id, evento, resumen, sello_previo, sello)
            VALUES ('org_acme', 'staff', 'st_ro', 'staff_read', 'x', '', :s)
        """
            ),
            {"s": "a" * 64},
        )


@pytest.mark.integracion
async def test_escritura_dual_customer_detail_y_concesion_en_cadena_central(
    dsn: str, db: Any, staff_factory: Any
) -> None:
    """CustomerDetail/reveal y grant_created encadenan el sello central del tenant."""
    from kallicode_core.ids import nuevo

    st = await staff_factory("staff_soporte")
    gid = nuevo("gr")
    tenant = f"org_b606_{uuid.uuid4().hex[:8]}"
    engine_su = create_async_engine(
        dsn.replace("postgresql://", "postgresql+asyncpg://"),
        poolclass=NullPool,
    )
    async with engine_su.begin() as conn:
        await conn.execute(
            text(
                """
            INSERT INTO core.organizations
                (id, nombre, idioma, timezone, despliegue, fabrica_activa)
            VALUES (:tid, 'Tenant Prueba B606 S.L.', 'es', 'Europe/Madrid', 'cloud', true)
            ON CONFLICT (id) DO NOTHING
        """
            ),
            {"tid": tenant},
        )
    await engine_su.dispose()

    motivo_kc = "Revisión autorizada de incidencia KC-7701 por soporte"
    await db.execute(
        text(
            """
        INSERT INTO admin.access_grants
            (id, staff_id, tenant_id, scope, reason, reference, granted_at, expires_at)
        VALUES (:gid, :sid, :tid, 'expediente', :rz, 'KC-7701',
                now(), now() + interval '30 minutes')
    """
        ),
        {"gid": gid, "sid": st["id"], "tid": tenant, "rz": motivo_kc},
    )

    sello_grant = await registrar_accion(
        db,
        staff_id=st["id"],
        staff_role="staff_soporte",
        action="grant_created",
        endpoint="POST /admin/v1/access-grants",
        tenant_id=tenant,
        grant_id=gid,
        scope="expediente",
        reason=motivo_kc,
        resource=f"grant:{gid}",
        request_id="tr_kc7701_a",
    )
    sello_read = await registrar_lectura(
        db,
        staff_id=st["id"],
        staff_role="staff_soporte",
        endpoint=f"GET /admin/v1/business/customers/{tenant}",
        tenant_id=tenant,
        grant_id=gid,
        scope="expediente",
        reason=motivo_kc,
        resource=tenant,
        request_id="tr_kc7701_b",
        revelado=["identificacion", "usuarios"],
    )
    await db.commit()

    assert len(sello_grant) == 64
    assert len(sello_read) == 64

    evs = (
        await db.execute(
            text(
                """
            SELECT actor_tipo, actor_id, evento, resumen, datos, sello_previo, sello
            FROM audit.audit_events
            WHERE tenant_id = :tid AND actor_tipo = 'staff' AND datos->>'grant_id' = :gid
            ORDER BY id ASC
        """
            ),
            {"tid": tenant, "gid": gid},
        )
    ).fetchall()
    assert len(evs) == 2

    ev_grant, ev_reveal = evs
    assert ev_grant.actor_tipo == "staff"
    assert ev_grant.actor_id == st["id"]
    assert ev_grant.evento == "staff_grant_created"
    assert st["id"] not in ev_grant.resumen
    assert ev_grant.datos["actor"] == {
        "typ": "staff",
        "staff_id": st["id"],
        "rol": "staff_soporte",
    }
    assert ev_grant.datos["staff_action_seal"] == sello_grant
    assert len(ev_grant.datos["canonical_seal"]) == 64

    assert ev_reveal.evento == "staff_reveal"
    assert ev_reveal.sello_previo == ev_grant.sello
    assert ev_reveal.datos["resource"] == tenant
    assert ev_reveal.datos["metadata"] == {"bloques_revelados": ["identificacion", "usuarios"]}

    res_central = await verificar_cadena_central_tenant(db, tenant)
    assert res_central.integra is True, res_central.roturas
    assert res_central.verificado is True


@pytest.mark.integracion
async def test_migracion_historica_idempotente_sin_perdida_ni_duplicados(
    db: Any, staff_factory: Any
) -> None:
    """Migra registros históricos previos de `admin.staff_actions` de forma idempotente."""
    st = await staff_factory("staff_negocio")
    tenant = "org_globex"
    tag = f"HIST-{uuid.uuid4().hex[:8]}"

    # Insertar 2 acciones históricas directamente en admin.staff_actions
    for idx in range(2):
        await db.execute(
            text(
                """
            INSERT INTO admin.staff_actions
                (staff_id, staff_role, action, tenant_id, scope, reason, resource,
                 endpoint, request_id, payload, prev_seal, seal)
            VALUES (:sid, 'staff_negocio', 'read', :tid, 'datos_negocio', :rz, :res,
                    '/admin/v1/business/customers/org_globex', :rq,
                    CAST('{"origen":"historico"}' AS jsonb), '', '')
        """
            ),
            {
                "sid": st["id"],
                "tid": tenant,
                "rz": f"Consulta histórica {tag}-{idx}",
                "res": f"customer:{tenant}",
                "rq": f"req_{tag}_{idx}",
            },
        )
    await db.commit()

    # Verificar que aún no existen en audit.audit_events
    antes = (
        await db.execute(
            text(
                """
            SELECT count(*) FROM audit.audit_events
            WHERE tenant_id = :tid AND datos->>'reason' LIKE :pat
        """
            ),
            {"tid": tenant, "pat": f"%{tag}%"},
        )
    ).scalar_one()
    assert antes == 0

    res_1 = await migrar_historico_staff_a_cadena_central(db, tenant_id=tenant)
    await db.commit()
    assert res_1["migrados"] >= 2

    despues_1 = (
        await db.execute(
            text(
                """
            SELECT count(*) FROM audit.audit_events
            WHERE tenant_id = :tid AND datos->>'reason' LIKE :pat
        """
            ),
            {"tid": tenant, "pat": f"%{tag}%"},
        )
    ).scalar_one()
    assert despues_1 == 2

    # Segunda ejecución idempotente: no duplica
    res_2 = await migrar_historico_staff_a_cadena_central(db, tenant_id=tenant)
    await db.commit()
    assert res_2["migrados"] == 0
    assert res_2["omitidos"] >= 2

    despues_2 = (
        await db.execute(
            text(
                """
            SELECT count(*) FROM audit.audit_events
            WHERE tenant_id = :tid AND datos->>'reason' LIKE :pat
        """
            ),
            {"tid": tenant, "pat": f"%{tag}%"},
        )
    ).scalar_one()
    assert despues_2 == 2

    verif = await verificar_cadena_central_tenant(db, tenant)
    assert verif.integra is True, verif.roturas


@pytest.mark.integracion
async def test_tampering_central_y_chain_head_detectado_por_verificador(
    dsn: str, db: Any, staff_factory: Any
) -> None:
    """Superusuario altera `datos` o desincroniza `audit.chain_heads`; limpieza en finally."""
    st = await staff_factory("staff_admin")
    tenant = f"org_b606_{uuid.uuid4().hex[:8]}"
    tag = f"TAMPER-{uuid.uuid4().hex[:8]}"

    engine_su = create_async_engine(
        dsn.replace("postgresql://", "postgresql+asyncpg://"),
        poolclass=NullPool,
    )
    async with engine_su.begin() as conn:
        await conn.execute(
            text(
                """
            INSERT INTO core.organizations
                (id, nombre, idioma, timezone, despliegue, fabrica_activa)
            VALUES (:tid, 'Tenant Tamper B606 S.L.', 'es', 'Europe/Madrid', 'cloud', true)
            ON CONFLICT (id) DO NOTHING
        """
            ),
            {"tid": tenant},
        )

    await registrar_accion(
        db,
        staff_id=st["id"],
        staff_role="staff_admin",
        action="read",
        endpoint=f"/admin/v1/business/customers/{tenant}",
        tenant_id=tenant,
        scope="datos_negocio",
        reason=f"Lectura auditada {tag}",
        resource=f"customer:{tenant}",
    )
    await db.commit()

    assert (await verificar_cadena_central_tenant(db, tenant)).integra is True

    async with engine_su.begin() as conn:
        row = (
            await conn.execute(
                text(
                    """
                SELECT id, creado_en, datos::text AS dat
                FROM audit.audit_events
                WHERE tenant_id = :tid AND datos->>'reason' LIKE :pat
                ORDER BY id DESC LIMIT 1
            """
                ),
                {"tid": tenant, "pat": f"%{tag}%"},
            )
        ).fetchone()
        assert row is not None
        ev_id, ev_ts, orig_datos = row.id, row.creado_en, row.dat

        head_row = (
            await conn.execute(
                text("SELECT ultimo_sello FROM audit.chain_heads WHERE tenant_id = :tid"),
                {"tid": tenant},
            )
        ).fetchone()
        assert head_row is not None
        orig_head = head_row.ultimo_sello

    try:
        # Caso 1: alterar payload `datos` en audit.audit_events
        async with engine_su.begin() as conn:
            await conn.execute(
                text("ALTER TABLE audit.audit_events DISABLE TRIGGER trg_audit_immutable")
            )
            try:
                await conn.execute(
                    text(
                        """
                    UPDATE audit.audit_events
                    SET datos = jsonb_set(
                        datos,
                        '{reason}',
                        '"Motivo alterado en ataque"'::jsonb
                    )
                    WHERE id = :id AND creado_en = :ts
                """
                    ),
                    {"id": ev_id, "ts": ev_ts},
                )
            finally:
                await conn.execute(
                    text("ALTER TABLE audit.audit_events ENABLE TRIGGER trg_audit_immutable")
                )

        res_tamper_ev = await verificar_cadena_central_tenant(db, tenant)
        assert res_tamper_ev.integra is False
        assert res_tamper_ev.verificado is False

        # Restaurar evento y probar Caso 2: desincronizar chain_heads.ultimo_sello
        async with engine_su.begin() as conn:
            await conn.execute(
                text("ALTER TABLE audit.audit_events DISABLE TRIGGER trg_audit_immutable")
            )
            try:
                await conn.execute(
                    text(
                        """
                    UPDATE audit.audit_events
                    SET datos = CAST(:dat AS jsonb)
                    WHERE id = :id AND creado_en = :ts
                """
                    ),
                    {"dat": orig_datos, "id": ev_id, "ts": ev_ts},
                )
            finally:
                await conn.execute(
                    text("ALTER TABLE audit.audit_events ENABLE TRIGGER trg_audit_immutable")
                )

            await conn.execute(
                text("UPDATE audit.chain_heads SET ultimo_sello = :mal WHERE tenant_id = :tid"),
                {"mal": "e" * 64, "tid": tenant},
            )

        res_tamper_head = await verificar_cadena_central_tenant(db, tenant)
        assert res_tamper_head.integra is False
        assert res_tamper_head.verificado is False
    finally:
        async with engine_su.begin() as conn:
            await conn.execute(
                text("ALTER TABLE audit.audit_events DISABLE TRIGGER trg_audit_immutable")
            )
            try:
                await conn.execute(
                    text(
                        """
                    UPDATE audit.audit_events
                    SET datos = CAST(:dat AS jsonb)
                    WHERE id = :id AND creado_en = :ts
                """
                    ),
                    {"dat": orig_datos, "id": ev_id, "ts": ev_ts},
                )
            finally:
                await conn.execute(
                    text("ALTER TABLE audit.audit_events ENABLE TRIGGER trg_audit_immutable")
                )
            await conn.execute(
                text("UPDATE audit.chain_heads SET ultimo_sello = :ok WHERE tenant_id = :tid"),
                {"ok": orig_head, "tid": tenant},
            )
        await engine_su.dispose()

    assert (await verificar_cadena_central_tenant(db, tenant)).integra is True
