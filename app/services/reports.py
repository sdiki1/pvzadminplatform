from __future__ import annotations

import csv
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from openpyxl import Workbook

from app.db.models import Expense, Point, Shift, User
from app.services.payroll import EmployeePayrollBreakdown


class ReportService:
    def __init__(self, export_dir: str = "exports"):
        self.export_dir = Path(export_dir)
        self.export_dir.mkdir(parents=True, exist_ok=True)

    def export_payroll_summary_xlsx(
        self,
        period_start: date,
        period_end: date,
        rows: list[EmployeePayrollBreakdown],
    ) -> Path:
        wb = Workbook()
        ws = wb.active
        ws.title = "Payroll"

        ws.append(["Период", f"{period_start:%d.%m.%Y} - {period_end:%d.%m.%Y}"])
        ws.append([])
        ws.append(
            [
                "Сотрудник",
                "Смены",
                "Часы",
                "База",
                "Мотивация",
                "Бонус выдача",
                "Резерв",
                "Резервный выход",
                "Удержания спорные",
                "Бонус менеджера",
                "Корректировки",
                "Итого",
            ]
        )

        for row in rows:
            ws.append(
                [
                    row.user.full_name,
                    row.shifts_count,
                    float(row.hours_total),
                    float(row.base_amount_rub),
                    float(row.motivation_amount_rub),
                    float(row.issued_bonus_rub),
                    float(row.reserve_bonus_rub),
                    float(row.substitution_bonus_rub),
                    float(row.dispute_deduction_rub),
                    float(row.manager_bonus_rub),
                    float(row.adjustments_rub),
                    float(row.total_amount_rub),
                ]
            )

        path = self.export_dir / f"payroll_summary_{period_start}_{period_end}.xlsx"
        wb.save(path)
        return path

    def export_employee_payroll_sheets(
        self,
        period_start: date,
        period_end: date,
        rows: list[EmployeePayrollBreakdown],
    ) -> Path:
        wb = Workbook()
        first = True

        for row in rows:
            if first:
                ws = wb.active
                first = False
            else:
                ws = wb.create_sheet()
            ws.title = (row.user.full_name[:28] or "Employee").replace("/", " ")

            ws.append([row.user.full_name])
            ws.append(["Период начислений", "", "", f"{period_start:%d.%m.%Y} - {period_end:%d.%m.%Y}"])
            ws.append([])
            ws.append(["Оклад", "", row.shifts_count, float(row.base_amount_rub)])
            ws.append(["Мотивирующие начисления", "", "", float(row.motivation_amount_rub)])
            ws.append(["Премия за выдачу", "", "", float(row.issued_bonus_rub)])
            ws.append(["Резервные дежурства", "", "", float(row.reserve_bonus_rub)])
            ws.append(["Резервные выходы", "", "", float(row.substitution_bonus_rub)])
            ws.append(["Удержания по товарам (не оспорено)", "", "", float(row.dispute_deduction_rub)])
            ws.append(["Доп. выплаты менеджера", "", "", float(row.manager_bonus_rub)])
            ws.append(["Премия / удержание руководства", "", "", float(row.adjustments_rub)])
            ws.append(["Итого", "", "", float(row.total_amount_rub)])

        path = self.export_dir / f"payroll_sheets_{period_start}_{period_end}.xlsx"
        wb.save(path)
        return path

    def export_shifts_csv(
        self,
        period_start: date,
        period_end: date,
        shifts: list[Shift],
        users_by_id: dict[int, User],
        points_by_id: dict[int, Point],
    ) -> Path:
        path = self.export_dir / f"shifts_{period_start}_{period_end}.csv"
        with path.open("w", encoding="utf-8", newline="") as f:
            writer = csv.writer(f, delimiter=";")
            writer.writerow(
                [
                    "id",
                    "date",
                    "employee",
                    "point",
                    "opened_at",
                    "closed_at",
                    "duration_min",
                    "open_distance_m",
                    "close_distance_m",
                ]
            )
            for s in shifts:
                writer.writerow(
                    [
                        s.id,
                        s.shift_date.isoformat(),
                        users_by_id.get(s.user_id).full_name if s.user_id in users_by_id else s.user_id,
                        points_by_id.get(s.point_id).name if s.point_id in points_by_id else s.point_id,
                        s.opened_at.isoformat() if s.opened_at else "",
                        s.closed_at.isoformat() if s.closed_at else "",
                        s.duration_minutes or 0,
                        float(s.open_distance_m or 0),
                        float(s.close_distance_m or 0),
                    ]
                )
        return path

    def export_expenses_csv(self, period_start: date, period_end: date, expenses: list[Expense], points_by_id: dict[int, Point]) -> Path:
        path = self.export_dir / f"expenses_{period_start}_{period_end}.csv"
        with path.open("w", encoding="utf-8", newline="") as f:
            writer = csv.writer(f, delimiter=";")
            writer.writerow(["date", "point", "category", "amount_rub", "description"])
            for e in expenses:
                writer.writerow(
                    [
                        e.expense_date.isoformat(),
                        points_by_id.get(e.point_id).name if e.point_id in points_by_id else e.point_id,
                        e.category,
                        float(e.amount_rub),
                        e.description or "",
                    ]
                )
        return path
