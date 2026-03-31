"""Create all PVZ employee web-panel accounts.

Usage (local):
    python3 scripts/create_pvz_users.py

Usage (Docker):
    docker compose exec app python3 scripts/create_pvz_users.py
"""
from __future__ import annotations

import asyncio
import json

from sqlalchemy import select

from app.db.models import WebUser
from app.db.session import SessionLocal, init_db
from app.web.auth import hash_password

# ---------------------------------------------------------------------------
# User definitions
# ---------------------------------------------------------------------------
# Fields: login, password, full_name, roles
# Roles: manager = менеджер ПВЗ, senior = управляющий ПВЗ, disputes = оспаривания
USERS = [
    # ── WB ──────────────────────────────────────────────────────────────────
    ("d.zhevlakov",    "Zhev@pvz25",  "Даниил Жевлаков",       ["manager", "senior"]),
    ("a.lobiger",      "Lobi@pvz25",  "Александра Лобигер",    ["manager", "senior"]),
    ("a.kolupayeva",   "Kolu@pvz25",  "Анна Колупаева",         ["manager", "disputes"]),
    ("i.fedina",       "Fedi@pvz25",  "Илона Федина",           ["manager"]),
    ("d.perevalova",   "Pere@pvz25",  "Дария Перевалова",       ["manager"]),
    ("a.kolova",       "Kolo@pvz25",  "Александра Колова",      ["manager"]),
    ("d.davydov",      "Davy@pvz25",  "Дмитрий Давыдов",        ["manager"]),
    ("a.nizovkina",    "Nizo@pvz25",  "Анна Низовкина",          ["manager"]),
    ("z.chizhov",      "Chiz@pvz25",  "Захар Чижов",             ["manager"]),
    ("k.kuzmenkova",   "Kuzm@pvz25",  "Ксения Кузьменкова",     ["manager"]),
    # ── Ozon (not on WB list) ────────────────────────────────────────────────
    ("v.fedorovtseva", "Fedo@pvz25",  "Виктория Федоровцева",  ["manager"]),
]


async def main() -> None:
    await init_db()

    created = []
    skipped = []

    async with SessionLocal() as session:
        for login, password, full_name, roles in USERS:
            existing = await session.execute(select(WebUser).where(WebUser.login == login))
            if existing.scalar_one_or_none():
                skipped.append(login)
                continue

            user = WebUser(
                login=login,
                password_hash=hash_password(password),
                full_name=full_name,
                roles_json=json.dumps(roles),
                is_active=True,
            )
            session.add(user)
            created.append((login, password, full_name, roles))

        await session.commit()

    print("\n" + "=" * 60)
    print(f"  Created: {len(created)}   Skipped (already exist): {len(skipped)}")
    print("=" * 60)

    if created:
        print("\nСозданные аккаунты:\n")
        print(f"{'Логин':<22} {'Пароль':<16} {'ФИО':<30} Роли")
        print("-" * 90)
        for login, password, full_name, roles in created:
            print(f"{login:<22} {password:<16} {full_name:<30} {', '.join(roles)}")

    if skipped:
        print(f"\nПропущены (уже существуют): {', '.join(skipped)}")

    print()


if __name__ == "__main__":
    asyncio.run(main())
