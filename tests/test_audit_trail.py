import re

import pytest
from admin_api.audit import (
    ResultadoIntegridadCadena,
    registrar_accion_staff,
    verificar_cadena_staff_actions,
)
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, InternalError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool


@pytest.mark.integracion
async def test_staff_actions_immutability(dsn: str, esquema: str) -> None:
    """Verifica que la tabla admin.staff_actions sea estrictamente append-only."""
    engine = create_async_engine(
        dsn.replace("postgresql://", "postgresql+asyncpg://"),
        poolclass=NullPool,
    )
    async with AsyncSession(engine) as session:
        # 1. Crear un empleado para satisfacer la FK
        await session.execute(
            text("""
            INSERT INTO admin.staff (id, email, full_name, role, status)
            VALUES ('st_test_immut', 'immut@kallicode.com', 'Test Immut',
                    'staff_admin', 'invited')
            ON CONFLICT (id) DO NOTHING
        """)
        )

        # 2. Insertar un registro de auditoría.
        await session.execute(
            text("""
            INSERT INTO admin.staff_actions (
                staff_id, staff_role, action, endpoint, ip, user_agent, prev_seal, seal
            ) VALUES (
                'st_test_immut', 'staff_admin', 'admin_query', '/test',
                '127.0.0.1', 'pytest', '',
                '0000000000000000000000000000000000000000000000000000000000000000'
            )
        """)
        )
        await session.flush()

        res = await session.execute(
            text("""
            SELECT id, occurred_at FROM admin.staff_actions
            WHERE staff_id = 'st_test_immut' LIMIT 1
        """)
        )
        row = res.fetchone()
        assert row is not None
        aid = row.id
        ts = row.occurred_at

        # 3. Intentar UPDATE debe fallar por el trigger trg_staff_actions_immutable
        with pytest.raises((InternalError, DBAPIError)) as excinfo:
            await session.execute(
                text("""
                UPDATE admin.staff_actions SET action = 'read'
                WHERE id = :id AND occurred_at = :ts
            """),
                {"id": aid, "ts": ts},
            )
        assert "append-only" in str(excinfo.value)
        await session.rollback()

        # Re-insertar registro para verificar DELETE en una transacción limpia
        await session.execute(
            text("""
            INSERT INTO admin.staff (id, email, full_name, role, status)
            VALUES ('st_test_immut', 'immut@kallicode.com', 'Test Immut',
                    'staff_admin', 'invited')
            ON CONFLICT (id) DO NOTHING
        """)
        )
        await session.execute(
            text("""
            INSERT INTO admin.staff_actions (
                staff_id, staff_role, action, endpoint, ip, user_agent, prev_seal, seal
            ) VALUES (
                'st_test_immut', 'staff_admin', 'admin_query', '/test',
                '127.0.0.1', 'pytest', '',
                '0000000000000000000000000000000000000000000000000000000000000000'
            )
        """)
        )
        await session.flush()

        res = await session.execute(
            text("""
            SELECT id, occurred_at FROM admin.staff_actions
            WHERE staff_id = 'st_test_immut' LIMIT 1
        """)
        )
        row = res.fetchone()
        assert row is not None
        aid = row.id
        ts = row.occurred_at

        # 4. Intentar DELETE debe fallar por el mismo trigger
        with pytest.raises((InternalError, DBAPIError)) as excinfo:
            await session.execute(
                text("""
                DELETE FROM admin.staff_actions
                WHERE id = :id AND occurred_at = :ts
            """),
                {"id": aid, "ts": ts},
            )
        assert "append-only" in str(excinfo.value)
        await session.rollback()

    await engine.dispose()


@pytest.mark.integracion
async def test_staff_actions_chain_verification(db, staff_factory):
    """Verifica que el sellado y encadenamiento de la auditoría sea íntegro."""
    staff = await staff_factory(rol="staff_admin")
    sid = staff["id"]

    for i in range(5):
        await db.execute(
            text("""
            INSERT INTO admin.staff_actions (
                staff_id, staff_role, action, endpoint, ip, user_agent, prev_seal, seal
            ) VALUES (
                :sid, 'staff_admin', 'admin_query', :ep, '127.0.0.1', 'pytest', '',
                '0000000000000000000000000000000000000000000000000000000000000000'
            )
        """),
            {"sid": sid, "ep": f"/api/v1/test-{i}"},
        )

    res = await db.execute(text("SELECT * FROM admin.verify_staff_action_chain()"))
    errors = res.fetchall()
    assert len(errors) == 0, f"Se detectaron roturas en la cadena de auditoría: {errors}"

    res = await db.execute(
        text("SELECT seal FROM admin.staff_actions ORDER BY occurred_at, id")
    )
    seals = [r.seal for r in res.fetchall()]
    assert len(seals) >= 5
    for s in seals:
        assert len(s) == 64


@pytest.mark.integracion
async def test_schema_and_partitions_structure(dsn: str, esquema: str) -> None:
    """Valida la presencia del esquema, tablas RBAC y particiones de staff_actions."""
    engine = create_async_engine(
        dsn.replace("postgresql://", "postgresql+asyncpg://"),
        poolclass=NullPool,
    )
    async with AsyncSession(engine) as session:
        # Verificar tablas requeridas del esquema admin
        tablas_esperadas = {
            "staff",
            "staff_actions",
            "staff_action_head",
            "staff_mfa_challenges",
            "staff_refresh_tokens",
            "staff_password_resets",
            "staff_invitations",
            "access_grants",
            "reports",
        }
        res = await session.execute(
            text("""
            SELECT table_name FROM information_schema.tables
            WHERE table_schema = 'admin'
        """)
        )
        tablas_encontradas = {r[0] for r in res.fetchall()}
        assert tablas_esperadas.issubset(tablas_encontradas)

        # Verificar particiones de admin.staff_actions
        res = await session.execute(
            text("""
            SELECT count(*) FROM pg_inherits
            JOIN pg_class parent ON pg_inherits.inhparent = parent.oid
            JOIN pg_namespace n ON parent.relnamespace = n.oid
            WHERE n.nspname = 'admin' AND parent.relname = 'staff_actions'
        """)
        )
        num_particiones = res.scalar()
        assert num_particiones is not None and num_particiones >= 12

    await engine.dispose()


@pytest.mark.integracion
async def test_registrar_accion_staff(db: AsyncSession, staff_factory, dsn: str) -> None:
    """Verifica el registro atómico de auditoría con registrar_accion_staff."""
    staff = await staff_factory(rol="staff_soporte")
    sid = staff["id"]
    email = staff["email"]

    # Crear organización como superusuario para satisfacer la FK
    engine_su = create_async_engine(
        dsn.replace("postgresql://", "postgresql+asyncpg://"),
        poolclass=NullPool,
    )
    async with AsyncSession(engine_su) as session_su:
        await session_su.execute(
            text("""
            INSERT INTO core.organizations (id, nombre, idioma, timezone,
                                            despliegue, fabrica_activa)
            VALUES ('org_audit_unit', 'Audit Unit S.L.', 'es', 'Europe/Madrid', 'cloud', true)
            ON CONFLICT (id) DO NOTHING;
        """)
        )
        await session_su.commit()
    await engine_su.dispose()

    sello = await registrar_accion_staff(
        db,
        staff_id=sid,
        staff_email=email,
        staff_rol="staff_soporte",
        accion="lectura",
        tenant_id="org_audit_unit",
        alcance="datos_negocio",
        motivo="Revisión de ticket TK-2024",
        recurso="tk_2024",
        datos={"filtro": "facturacion"},
    )

    assert isinstance(sello, str)
    assert len(sello) == 64
    assert re.fullmatch(r"^[0-9a-f]{64}$", sello)

    # Validar que los datos y el sello quedaron persistidos fielmente en admin.staff_actions
    res = await db.execute(
        text("SELECT * FROM admin.staff_actions WHERE seal = :s"),
        {"s": sello},
    )
    row = res.mappings().fetchone()
    assert row is not None
    assert row["staff_id"] == sid
    assert row["staff_email"] == email
    assert row["staff_role"] == "staff_soporte"
    assert row["action"] == "lectura"
    assert row["tenant_id"] == "org_audit_unit"
    assert row["scope"] == "datos_negocio"
    assert row["reason"] == "Revisión de ticket TK-2024"
    assert row["resource"] == "tk_2024"
    assert row["seal"] == sello
    assert row["payload"] == {"filtro": "facturacion"}


@pytest.mark.integracion
async def test_verificar_cadena_staff_actions_integra(db: AsyncSession, staff_factory) -> None:
    """Verifica que la cadena íntegra devuelva integra = True."""
    staff = await staff_factory(rol="staff_admin")
    sid = staff["id"]

    for i in range(3):
        await registrar_accion_staff(
            db,
            staff_id=sid,
            staff_rol="staff_admin",
            accion="admin_query",
            endpoint=f"/admin/v1/ops/test-{i}",
            motivo=f"Comprobación de métricas #{i}",
        )

    res = await verificar_cadena_staff_actions(db)
    assert isinstance(res, ResultadoIntegridadCadena)
    assert res.integra is True
    assert res["integra"] is True
    assert res.roturas == []
    assert res["roturas"] == []
    assert res.total_roturas == 0


@pytest.mark.integracion
async def test_verificar_cadena_detecta_manipulacion(dsn: str, esquema: str) -> None:
    """Verifica que cualquier alteración en los sellos sea detectada como rotura."""
    engine = create_async_engine(
        dsn.replace("postgresql://", "postgresql+asyncpg://"),
        poolclass=NullPool,
    )
    async with AsyncSession(engine) as session:
        await session.execute(
            text("""
            INSERT INTO admin.staff (id, email, full_name, role, status)
            VALUES ('st_tamper_test', 'tamper@kallicode.com', 'Tamper Staff',
                    'staff_admin', 'invited')
            ON CONFLICT (id) DO NOTHING;
        """)
        )
        for i in range(3):
            await registrar_accion_staff(
                session,
                staff_id="st_tamper_test",
                staff_rol="staff_admin",
                accion="admin_query",
                endpoint=f"/admin/v1/ops/tamper-{i}",
                motivo=f"Evento auditado #{i}",
            )
        await session.commit()

        # Cadena debe ser íntegra antes de la manipulación
        res_antes = await verificar_cadena_staff_actions(session)
        assert res_antes.integra is True

        # Simular manipulación: deshabilitar trigger, cambiar sello, rehabilitar trigger
        await session.execute(
            text("ALTER TABLE admin.staff_actions DISABLE TRIGGER trg_staff_actions_immutable;")
        )
        await session.execute(
            text("""
            UPDATE admin.staff_actions
            SET seal = 'deadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeef'
            WHERE id = (SELECT max(id) FROM admin.staff_actions);
        """)
        )
        await session.execute(
            text("ALTER TABLE admin.staff_actions ENABLE TRIGGER trg_staff_actions_immutable;")
        )
        await session.commit()

        # La verificación debe detectar la rotura
        res_despues = await verificar_cadena_staff_actions(session)
        assert res_despues.integra is False
        assert res_despues["integra"] is False
        assert len(res_despues.roturas) > 0
        assert res_despues.total_roturas > 0
        assert any(
            "sello no reproducible" in r["motivo"] or "encadenamiento roto" in r["motivo"]
            for r in res_despues.roturas
        )

    await engine.dispose()


@pytest.mark.integracion
async def test_staff_actions_dml_privileges_revoked(db: AsyncSession) -> None:
    """Verifica que UPDATE, DELETE y TRUNCATE estén revocados sobre staff_actions."""
    res = await db.execute(
        text("""
        SELECT privilege_type, grantee
        FROM information_schema.table_privileges
        WHERE table_schema = 'admin' AND table_name = 'staff_actions'
          AND grantee IN ('PUBLIC', 'kallicode_admin_app', 'kallicode_admin_ro')
          AND privilege_type IN ('UPDATE', 'DELETE', 'TRUNCATE');
    """)
    )
    rows = res.fetchall()
    assert len(rows) == 0, f"Se encontraron privilegios DML mutacionales no revocados: {rows}"
