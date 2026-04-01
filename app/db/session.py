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


async def init_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_ensure_user_rate_columns)
