"""Create the first web superadmin user.

Usage:
    python3 scripts/create_web_admin.py <login> <password> [full_name]

Example:
    python3 scripts/create_web_admin.py admin secret123 "Главный Администратор"
"""
from __future__ import annotations

import asyncio
import sys

from sqlalchemy import select

from app.db.models import WebRoleEnum, WebUser
from app.db.session import SessionLocal, init_db
from app.web.auth import hash_password


async def main() -> None:
    if len(sys.argv) < 3:
        print("Usage: python3 scripts/create_web_admin.py <login> <password> [full_name]")
        sys.exit(1)

    login = sys.argv[1]
    password = sys.argv[2]
    full_name = sys.argv[3] if len(sys.argv) > 3 else "Superadmin"

    await init_db()

    async with SessionLocal() as session:
        existing = await session.execute(select(WebUser).where(WebUser.login == login))
        if existing.scalar_one_or_none():
            print(f"User '{login}' already exists")
            sys.exit(1)

        user = WebUser(
            login=login,
            password_hash=hash_password(password),
            full_name=full_name,
            roles_json='["superadmin"]',
            is_active=True,
        )
        session.add(user)
        await session.commit()
        print(f"Superadmin '{login}' created successfully")


if __name__ == "__main__":
    asyncio.run(main())
