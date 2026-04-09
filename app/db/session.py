from __future__ import annotations

from collections.abc import AsyncGenerator

from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import get_settings
from app.db.models import Base

settings = get_settings()
engine = create_async_engine(settings.database_url, echo=False, future=True)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with SessionLocal() as session:
        yield session


def _ensure_user_rate_columns(sync_conn) -> None:
    """Lightweight schema patch for personal user rates (without Alembic)."""
    try:
        existing_cols = {c["name"] for c in inspect(sync_conn).get_columns("users")}
    except Exception:
        return

    dialect = sync_conn.dialect.name
    statements: list[str] = []

    if "shift_rate_rub" not in existing_cols:
        if dialect == "sqlite":
            statements.append("ALTER TABLE users ADD COLUMN shift_rate_rub NUMERIC NOT NULL DEFAULT 0")
        else:
            statements.append("ALTER TABLE users ADD COLUMN shift_rate_rub NUMERIC(10,2) NOT NULL DEFAULT 0")

    if "hourly_rate_rub" not in existing_cols:
        if dialect == "sqlite":
            statements.append("ALTER TABLE users ADD COLUMN hourly_rate_rub NUMERIC")
        else:
            statements.append("ALTER TABLE users ADD COLUMN hourly_rate_rub NUMERIC(10,2)")

    if "color" not in existing_cols:
        statements.append("ALTER TABLE users ADD COLUMN color VARCHAR(7)")

    for stmt in statements:
        sync_conn.execute(text(stmt))


def _ensure_appeal_columns(sync_conn) -> None:
    """Lightweight schema patch for appeal fields added after initial release."""
    try:
        existing_cols = {c["name"] for c in inspect(sync_conn).get_columns("appeals")}
    except Exception:
        return

    statements: list[str] = []
    if "feedback_from_nadezhda" not in existing_cols:
        statements.append("ALTER TABLE appeals ADD COLUMN feedback_from_nadezhda TEXT")
    if "feedback_from_anna" not in existing_cols:
        statements.append("ALTER TABLE appeals ADD COLUMN feedback_from_anna TEXT")

    for stmt in statements:
        sync_conn.execute(text(stmt))


def _ensure_planned_shift_columns(sync_conn) -> None:
    """Lightweight schema patch for planned shift flags and time window."""
    try:
        existing_cols = {c["name"] for c in inspect(sync_conn).get_columns("planned_shifts")}
    except Exception:
        return

    dialect = sync_conn.dialect.name
    statements: list[str] = []
    if "is_reserve" not in existing_cols:
        statements.append("ALTER TABLE planned_shifts ADD COLUMN is_reserve BOOLEAN NOT NULL DEFAULT FALSE")
    if "is_substitution" not in existing_cols:
        statements.append("ALTER TABLE planned_shifts ADD COLUMN is_substitution BOOLEAN NOT NULL DEFAULT FALSE")
    if "start_time" not in existing_cols:
        statements.append("ALTER TABLE planned_shifts ADD COLUMN start_time TIME")
    if "end_time" not in existing_cols:
        statements.append("ALTER TABLE planned_shifts ADD COLUMN end_time TIME")
    if "status" not in existing_cols:
        if dialect == "sqlite":
            statements.append(
                "ALTER TABLE planned_shifts ADD COLUMN status VARCHAR(16) NOT NULL DEFAULT 'planned'"
            )
        else:
            statements.append(
                "ALTER TABLE planned_shifts ADD COLUMN status VARCHAR(16) NOT NULL DEFAULT 'planned'"
            )

    for stmt in statements:
        sync_conn.execute(text(stmt))


def _ensure_payroll_item_columns(sync_conn) -> None:
    """Lightweight schema patch for payroll bonus columns."""
    try:
        existing_cols = {c["name"] for c in inspect(sync_conn).get_columns("payroll_items")}
    except Exception:
        return

    statements: list[str] = []
    if "reserve_bonus_rub" not in existing_cols:
        statements.append("ALTER TABLE payroll_items ADD COLUMN reserve_bonus_rub NUMERIC(12,2) NOT NULL DEFAULT 0")
    if "substitution_bonus_rub" not in existing_cols:
        statements.append("ALTER TABLE payroll_items ADD COLUMN substitution_bonus_rub NUMERIC(12,2) NOT NULL DEFAULT 0")
    if "rating_bonus_rub" not in existing_cols:
        statements.append("ALTER TABLE payroll_items ADD COLUMN rating_bonus_rub NUMERIC(12,2) NOT NULL DEFAULT 0")
    if "stuck_deduction_rub" not in existing_cols:
        statements.append("ALTER TABLE payroll_items ADD COLUMN stuck_deduction_rub NUMERIC(12,2) NOT NULL DEFAULT 0")
    if "substitution_deduction_rub" not in existing_cols:
        statements.append("ALTER TABLE payroll_items ADD COLUMN substitution_deduction_rub NUMERIC(12,2) NOT NULL DEFAULT 0")
    if "defect_deduction_rub" not in existing_cols:
        statements.append("ALTER TABLE payroll_items ADD COLUMN defect_deduction_rub NUMERIC(12,2) NOT NULL DEFAULT 0")
    if "debt_adjustment_rub" not in existing_cols:
        statements.append("ALTER TABLE payroll_items ADD COLUMN debt_adjustment_rub NUMERIC(12,2) NOT NULL DEFAULT 0")

    for stmt in statements:
        sync_conn.execute(text(stmt))


def _ensure_point_columns(sync_conn) -> None:
    """Add email field to points table."""
    try:
        existing_cols = {c["name"] for c in inspect(sync_conn).get_columns("points")}
    except Exception:
        return

    statements: list[str] = []
    if "email" not in existing_cols:
        statements.append("ALTER TABLE points ADD COLUMN email VARCHAR(255)")

    for stmt in statements:
        sync_conn.execute(text(stmt))


def _ensure_shift_open_codes_table(sync_conn) -> None:
    """Create shift_open_codes table if it doesn't exist yet."""
    try:
        inspector = inspect(sync_conn)
        if "shift_open_codes" not in inspector.get_table_names():
            sync_conn.execute(text("""
                CREATE TABLE shift_open_codes (
                    id SERIAL PRIMARY KEY,
                    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    point_id INTEGER NOT NULL REFERENCES points(id) ON DELETE CASCADE,
                    shift_date DATE NOT NULL,
                    code VARCHAR(4) NOT NULL,
                    used BOOLEAN NOT NULL DEFAULT FALSE,
                    expires_at TIMESTAMP NOT NULL,
                    created_at TIMESTAMP NOT NULL DEFAULT NOW()
                )
            """))
            sync_conn.execute(text("CREATE INDEX ix_shift_open_codes_user_id ON shift_open_codes(user_id)"))
            sync_conn.execute(text("CREATE INDEX ix_shift_open_codes_point_id ON shift_open_codes(point_id)"))
    except Exception:
        return


async def init_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_ensure_user_rate_columns)
        await conn.run_sync(_ensure_appeal_columns)
        await conn.run_sync(_ensure_planned_shift_columns)
        await conn.run_sync(_ensure_payroll_item_columns)
        await conn.run_sync(_ensure_point_columns)
        await conn.run_sync(_ensure_shift_open_codes_table)
