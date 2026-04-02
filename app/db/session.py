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
    """Lightweight schema patch for planned shift flags."""
    try:
        existing_cols = {c["name"] for c in inspect(sync_conn).get_columns("planned_shifts")}
    except Exception:
        return

    statements: list[str] = []
    if "is_reserve" not in existing_cols:
        statements.append("ALTER TABLE planned_shifts ADD COLUMN is_reserve BOOLEAN NOT NULL DEFAULT FALSE")
    if "is_substitution" not in existing_cols:
        statements.append("ALTER TABLE planned_shifts ADD COLUMN is_substitution BOOLEAN NOT NULL DEFAULT FALSE")

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


async def init_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_ensure_user_rate_columns)
        await conn.run_sync(_ensure_appeal_columns)
        await conn.run_sync(_ensure_planned_shift_columns)
        await conn.run_sync(_ensure_payroll_item_columns)
