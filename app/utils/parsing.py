from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation


DATE_FORMATS = [
    "%d.%m.%Y",
    "%Y-%m-%d",
    "%d/%m/%Y",
    "%d.%m.%y",
]


def parse_date(value: str | date | datetime | None) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value

    text = str(value).strip()
    if not text:
        return None

    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue

    # Excel serial support
    if text.isdigit():
        serial = int(text)
        if serial > 30000:
            # Excel epoch 1899-12-30
            return (datetime(1899, 12, 30) + timedelta(days=serial)).date()

    return None


def parse_decimal(value: str | int | float | Decimal | None, default: Decimal = Decimal("0")) -> Decimal:
    if value is None:
        return default
    if isinstance(value, Decimal):
        return value
    if isinstance(value, (int, float)):
        return Decimal(str(value))

    text = str(value).strip().replace(" ", "")
    if not text:
        return default
    text = text.replace(",", ".")
    try:
        return Decimal(text)
    except InvalidOperation:
        return default


def normalize_text(value: str | None) -> str:
    if not value:
        return ""
    return " ".join(value.strip().lower().split())
