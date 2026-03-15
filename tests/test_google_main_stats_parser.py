from __future__ import annotations

from datetime import date

from app.config import Settings
from app.services.google_sheets import GoogleSheetsService


def test_parse_main_stats_matrix_block_format() -> None:
    settings = Settings(BOT_TOKEN="123:token", ADMIN_IDS="")
    service = GoogleSheetsService(settings)

    values = [
        ["ПВЗ №1 Гоголя 18"],
        ["Дата", "2026-03-01", "2026-03-02", "2026-03-03"],
        ["Товаров отдали", "121", "199", "0"],
        ["Статистика приёмки", "100.5", "-20", "0"],
    ]

    rows = service._parse_main_stats_matrix(values)
    assert len(rows) == 2

    assert rows[0].point_name == "ПВЗ №1 Гоголя 18"
    assert rows[0].record_date == date(2026, 3, 1)
    assert rows[0].issued_items_count == 121
    assert float(rows[0].acceptance_amount_rub) == 100.5

    assert rows[1].record_date == date(2026, 3, 2)
    assert rows[1].issued_items_count == 199
    assert float(rows[1].acceptance_amount_rub) == -20.0
