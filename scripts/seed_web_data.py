"""Seed reference data for the web admin panel.

Creates:
  - Marketplaces (WB, Ozon)
  - Supply catalog items
  - Daily stat metric definitions

Usage:
    python3 scripts/seed_web_data.py
"""
from __future__ import annotations

import asyncio

from sqlalchemy import select

from app.db.models import DailyStatMetricDef, Marketplace, SupplyItem
from app.db.session import SessionLocal, init_db


# ── Marketplaces ─────────────────────────────────────────────
MARKETPLACES = [
    {"code": "wb", "name": "Wildberries"},
    {"code": "ozon", "name": "Ozon"},
]

# ── Supply catalog (spec section 15.4) ──────────────────────
SUPPLY_ITEMS = [
    # Упаковка
    {"category": "Упаковка", "name": "Пакет курьерский 150×210", "unit": "шт", "min_qty": 100},
    {"category": "Упаковка", "name": "Пакет курьерский 240×320", "unit": "шт", "min_qty": 100},
    {"category": "Упаковка", "name": "Пакет курьерский 300×400", "unit": "шт", "min_qty": 50},
    {"category": "Упаковка", "name": "Пакет курьерский 400×500", "unit": "шт", "min_qty": 50},
    {"category": "Упаковка", "name": "Пакет курьерский 500×600", "unit": "шт", "min_qty": 30},
    {"category": "Упаковка", "name": "Скотч прозрачный 48мм", "unit": "шт", "min_qty": 5},
    {"category": "Упаковка", "name": "Скотч коричневый 48мм", "unit": "шт", "min_qty": 5},
    {"category": "Упаковка", "name": "Стрейч-плёнка", "unit": "рул", "min_qty": 2},
    {"category": "Упаковка", "name": "Воздушно-пузырчатая плёнка", "unit": "м", "min_qty": 10},
    {"category": "Упаковка", "name": "Коробка 200×150×100", "unit": "шт", "min_qty": 20},
    {"category": "Упаковка", "name": "Коробка 300×200×150", "unit": "шт", "min_qty": 20},
    {"category": "Упаковка", "name": "Коробка 400×300×200", "unit": "шт", "min_qty": 10},
    # Канцелярия
    {"category": "Канцелярия", "name": "Бумага А4", "unit": "пачка", "min_qty": 2},
    {"category": "Канцелярия", "name": "Ручка шариковая", "unit": "шт", "min_qty": 10},
    {"category": "Канцелярия", "name": "Маркер перманентный", "unit": "шт", "min_qty": 3},
    {"category": "Канцелярия", "name": "Ножницы", "unit": "шт", "min_qty": 1},
    {"category": "Канцелярия", "name": "Степлер", "unit": "шт", "min_qty": 1},
    {"category": "Канцелярия", "name": "Скобы для степлера", "unit": "уп", "min_qty": 2},
    # Хозтовары
    {"category": "Хозтовары", "name": "Мешки для мусора 120л", "unit": "рул", "min_qty": 5},
    {"category": "Хозтовары", "name": "Мешки для мусора 60л", "unit": "рул", "min_qty": 5},
    {"category": "Хозтовары", "name": "Салфетки влажные", "unit": "уп", "min_qty": 5},
    {"category": "Хозтовары", "name": "Средство для мытья полов", "unit": "шт", "min_qty": 1},
    {"category": "Хозтовары", "name": "Тряпка для пола", "unit": "шт", "min_qty": 2},
    {"category": "Хозтовары", "name": "Перчатки рабочие", "unit": "пара", "min_qty": 5},
    # Оборудование
    {"category": "Оборудование", "name": "Этикетки 58×40", "unit": "рул", "min_qty": 5},
    {"category": "Оборудование", "name": "Чековая лента 57мм", "unit": "рул", "min_qty": 5},
    {"category": "Оборудование", "name": "Батарейки АА", "unit": "шт", "min_qty": 4},
    {"category": "Оборудование", "name": "Батарейки ААА", "unit": "шт", "min_qty": 4},
]

# ── Daily stat metrics (spec section 12.6) ──────────────────
METRICS = [
    {"code": "issued_wb", "name": "Выдано (WB)", "value_type": "int", "marketplace": "wb", "sort_order": 1},
    {"code": "accepted_wb", "name": "Принято (WB)", "value_type": "int", "marketplace": "wb", "sort_order": 2},
    {"code": "returns_wb", "name": "Возвраты (WB)", "value_type": "int", "marketplace": "wb", "sort_order": 3},
    {"code": "oversize_wb", "name": "Негабарит (WB)", "value_type": "int", "marketplace": "wb", "sort_order": 4},
    {"code": "issued_ozon", "name": "Выдано (Ozon)", "value_type": "int", "marketplace": "ozon", "sort_order": 5},
    {"code": "accepted_ozon", "name": "Принято (Ozon)", "value_type": "int", "marketplace": "ozon", "sort_order": 6},
    {"code": "returns_ozon", "name": "Возвраты (Ozon)", "value_type": "int", "marketplace": "ozon", "sort_order": 7},
    {"code": "revenue", "name": "Выручка", "value_type": "decimal", "marketplace": None, "sort_order": 8},
    {"code": "clients_total", "name": "Клиентов всего", "value_type": "int", "marketplace": None, "sort_order": 9},
    {"code": "clients_new", "name": "Новых клиентов", "value_type": "int", "marketplace": None, "sort_order": 10},
    {"code": "nps_score", "name": "NPS оценка", "value_type": "decimal", "marketplace": None, "sort_order": 11},
    {"code": "complaints", "name": "Жалобы", "value_type": "int", "marketplace": None, "sort_order": 12},
]


async def main() -> None:
    await init_db()

    async with SessionLocal() as session:
        # ── Marketplaces ──
        mp_map: dict[str, int] = {}
        for mp in MARKETPLACES:
            existing = await session.execute(
                select(Marketplace).where(Marketplace.code == mp["code"])
            )
            obj = existing.scalar_one_or_none()
            if not obj:
                obj = Marketplace(code=mp["code"], name=mp["name"], is_active=True)
                session.add(obj)
                await session.flush()
                print(f"  + Marketplace: {mp['name']}")
            mp_map[mp["code"]] = obj.id

        # ── Supply catalog ──
        for item in SUPPLY_ITEMS:
            existing = await session.execute(
                select(SupplyItem).where(
                    SupplyItem.name == item["name"],
                    SupplyItem.category == item["category"],
                )
            )
            if not existing.scalar_one_or_none():
                session.add(SupplyItem(
                    category=item["category"],
                    name=item["name"],
                    unit=item["unit"],
                    min_qty=item["min_qty"],
                    is_active=True,
                ))
                print(f"  + Supply: {item['category']} / {item['name']}")

        # ── Metric definitions ──
        for m in METRICS:
            existing = await session.execute(
                select(DailyStatMetricDef).where(DailyStatMetricDef.code == m["code"])
            )
            if not existing.scalar_one_or_none():
                session.add(DailyStatMetricDef(
                    code=m["code"],
                    name=m["name"],
                    value_type=m["value_type"],
                    marketplace_id=mp_map.get(m["marketplace"]) if m["marketplace"] else None,
                    is_active=True,
                    sort_order=m["sort_order"],
                ))
                print(f"  + Metric: {m['name']}")

        await session.commit()
        print("\nSeed data complete!")


if __name__ == "__main__":
    asyncio.run(main())
