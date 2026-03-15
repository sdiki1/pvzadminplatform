from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from functools import cached_property
from typing import Any, Optional

import gspread
from google.oauth2.service_account import Credentials

from app.config import Settings
from app.utils.parsing import normalize_text, parse_date, parse_decimal


@dataclass
class MainStatsRow:
    record_date: date
    point_name: str | None
    manager_name: str | None
    acceptance_amount_rub: Decimal
    issued_items_count: int
    tickets_count: int
    raw_payload: str


@dataclass
class DisputeRow:
    record_date: date
    manager_name: str | None
    status: str | None
    amount_rub: Decimal
    raw_payload: str


class GoogleSheetsService:
    def __init__(self, settings: Settings):
        self.settings = settings

    @property
    def enabled(self) -> bool:
        return bool(self.settings.google_service_account_file)

    @cached_property
    def _client(self) -> gspread.Client:
        scopes = [
            "https://www.googleapis.com/auth/spreadsheets.readonly",
            "https://www.googleapis.com/auth/drive.readonly",
        ]
        creds = Credentials.from_service_account_file(self.settings.google_service_account_file, scopes=scopes)
        return gspread.authorize(creds)

    def _get_records(self, sheet_id: str, tab_name: str) -> list[dict[str, Any]]:
        sh = self._client.open_by_key(sheet_id)
        ws = sh.worksheet(tab_name)
        return ws.get_all_records(default_blank="")

    def _get_values(self, sheet_id: str, tab_name: str) -> list[list[Any]]:
        sh = self._client.open_by_key(sheet_id)
        ws = sh.worksheet(tab_name)
        return ws.get_all_values()

    @staticmethod
    def _find_value(row: dict[str, Any], aliases: list[str]) -> Any:
        normalized = {normalize_text(k): v for k, v in row.items()}
        for alias in aliases:
            key = normalize_text(alias)
            if key in normalized:
                return normalized[key]
        return None

    def fetch_main_stats(self) -> list[MainStatsRow]:
        if not self.enabled or not self.settings.google_main_sheet_id:
            return []

        rows = self._get_records(self.settings.google_main_sheet_id, self.settings.google_main_stats_tab)
        out = self._parse_main_stats_records(rows)
        if out:
            return out

        # Фолбэк под текущий формат таблицы:
        # блоки вида "ПВЗ ...", ниже строки "Дата"/"Товаров отдали"/"Статистика приёмки",
        # где даты идут по колонкам.
        values = self._get_values(self.settings.google_main_sheet_id, self.settings.google_main_stats_tab)
        return self._parse_main_stats_matrix(values)

    def _parse_main_stats_records(self, rows: list[dict[str, Any]]) -> list[MainStatsRow]:
        out: list[MainStatsRow] = []
        for row in rows:
            d = parse_date(
                self._find_value(
                    row,
                    ["дата", "date", "день"],
                )
            )
            if not d:
                continue

            manager_name = self._find_value(
                row,
                [
                    "менеджер",
                    "фио",
                    "фамилия",
                    "сотрудник",
                ],
            )
            point_name = self._find_value(row, ["пвз", "адрес", "точка", "пункт"])

            acceptance = parse_decimal(
                self._find_value(
                    row,
                    [
                        "приемка",
                        "приёмка",
                        "приемка, руб",
                        "сумма приемки",
                        "сумма приёмки",
                        "статистика приемки в деньгах",
                    ],
                )
            )

            issued = int(
                parse_decimal(
                    self._find_value(row, ["выдано", "кол-во выдано", "количество выданных товаров", "выдача"]),
                    default=Decimal("0"),
                )
            )

            tickets = int(
                parse_decimal(
                    self._find_value(
                        row,
                        [
                            "тикеты",
                            "созданные тикеты",
                            "количество тикетов",
                            "оспаривание тикеты",
                        ],
                    ),
                    default=Decimal("0"),
                )
            )

            out.append(
                MainStatsRow(
                    record_date=d,
                    point_name=str(point_name).strip() if point_name else None,
                    manager_name=str(manager_name).strip() if manager_name else None,
                    acceptance_amount_rub=acceptance,
                    issued_items_count=max(0, issued),
                    tickets_count=max(0, tickets),
                    raw_payload=json.dumps(row, ensure_ascii=False),
                )
            )
        return out

    def _parse_main_stats_matrix(self, values: list[list[Any]]) -> list[MainStatsRow]:
        out: list[MainStatsRow] = []
        if not values:
            return out

        current_point: str | None = None
        date_row: list[Any] | None = None
        issued_row: list[Any] | None = None

        for row in values:
            if not row:
                continue

            first = str(row[0]).strip() if row and row[0] is not None else ""
            label = normalize_text(first)

            if label.startswith("пвз"):
                current_point = first
                date_row = None
                issued_row = None
                continue

            if label == "дата":
                date_row = row
                continue

            if "товаров отдали" in label:
                issued_row = row
                continue

            if "статистика приемки" in label or "статистика приёмки" in label:
                if not (current_point and date_row and issued_row):
                    continue

                max_len = max(len(date_row), len(issued_row), len(row))
                for col_idx in range(1, max_len):
                    date_val = date_row[col_idx] if col_idx < len(date_row) else None
                    d = parse_date(date_val)
                    if not d:
                        continue

                    issued_val = issued_row[col_idx] if col_idx < len(issued_row) else None
                    acceptance_val = row[col_idx] if col_idx < len(row) else None

                    issued = int(parse_decimal(issued_val, default=Decimal("0")))
                    acceptance = parse_decimal(acceptance_val, default=Decimal("0"))

                    if issued == 0 and acceptance == 0:
                        continue

                    payload = {
                        "point": current_point,
                        "date_cell": date_val,
                        "issued_cell": issued_val,
                        "acceptance_cell": acceptance_val,
                    }
                    out.append(
                        MainStatsRow(
                            record_date=d,
                            point_name=current_point,
                            manager_name=None,
                            acceptance_amount_rub=acceptance,
                            issued_items_count=max(0, issued),
                            tickets_count=0,
                            raw_payload=json.dumps(payload, ensure_ascii=False),
                        )
                    )

        return out

    def fetch_disputes(self) -> list[DisputeRow]:
        if not self.enabled or not self.settings.google_disputes_sheet_id:
            return []

        rows = self._get_records(self.settings.google_disputes_sheet_id, self.settings.google_disputes_tab)
        out: list[DisputeRow] = []

        for row in rows:
            d = parse_date(self._find_value(row, ["дата", "date", "день"]))
            if not d:
                continue

            manager_name = self._find_value(row, ["менеджер", "фио", "фамилия", "сотрудник"])
            status = self._find_value(row, ["статус", "status"])
            amount = parse_decimal(self._find_value(row, ["сумма", "стоимость", "amount", "итого"]))

            out.append(
                DisputeRow(
                    record_date=d,
                    manager_name=str(manager_name).strip() if manager_name else None,
                    status=str(status).strip() if status else None,
                    amount_rub=amount,
                    raw_payload=json.dumps(row, ensure_ascii=False),
                )
            )

        return out
