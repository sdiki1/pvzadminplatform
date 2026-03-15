from __future__ import annotations

from datetime import datetime
from decimal import Decimal


def money(value: Decimal | float | int) -> str:
    return f"{Decimal(value):.2f} ₽"


def dt(value: datetime | None) -> str:
    if not value:
        return "-"
    return value.strftime("%d.%m.%Y %H:%M")
