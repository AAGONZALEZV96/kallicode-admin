import pytest
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
async def test_schema_and_partitions_structure(dsn: str) -> None:
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
