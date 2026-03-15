from __future__ import annotations

import asyncio
from datetime import datetime

from app.config import get_settings
from app.db.models import BrandEnum, RoleEnum
from app.db.repositories import PointRepo, UserRepo
from app.db.session import SessionLocal, init_db
from app.services.lesnoy_catalog import LESNOY_DEFAULT_POINTS

# ВАЖНО: координаты ниже временные (центр г. Лесной).
# Перед продуктивом задайте точные lat/lon для каждого ПВЗ.
DEFAULT_LAT = 58.6352
DEFAULT_LON = 59.7852


async def main() -> None:
    settings = get_settings()
    await init_db()

    async with SessionLocal() as session:
        user_repo = UserRepo(session)
        point_repo = PointRepo(session)

        for admin_tg in settings.admin_ids:
            await user_repo.create_or_update(
                telegram_id=admin_tg,
                full_name=f"Admin {admin_tg}",
                role=RoleEnum.ADMIN,
            )

        for p in LESNOY_DEFAULT_POINTS:
            await point_repo.create_or_update(
                name=p["name"],
                address=p["full_address"],
                brand=BrandEnum(p["brand"]),
                latitude=DEFAULT_LAT,
                longitude=DEFAULT_LON,
                radius_m=150,
                work_start=datetime.strptime(p["work_start"], "%H:%M").time(),
                work_end=datetime.strptime(p["work_end"], "%H:%M").time(),
                is_active=True,
            )

    print("Bootstrap complete")


if __name__ == "__main__":
    asyncio.run(main())
