from __future__ import annotations

from datetime import date
from calendar import monthrange


def payroll_period_for_payout(payout_day: int, ref_date: date) -> tuple[date, date]:
    """
    10-е число: период с 16-го по последний день предыдущего месяца.
    25-е число: период с 1-го по 15-е текущего месяца.
    """
    if payout_day == 10:
        year = ref_date.year
        month = ref_date.month
        if month == 1:
            year -= 1
            month = 12
        else:
            month -= 1
        last_day = monthrange(year, month)[1]
        return date(year, month, 16), date(year, month, last_day)

    if payout_day == 25:
        return date(ref_date.year, ref_date.month, 1), date(ref_date.year, ref_date.month, 15)

    raise ValueError("Supported payout days are only 10 and 25")


def month_bounds(d: date) -> tuple[date, date]:
    last_day = monthrange(d.year, d.month)[1]
    return date(d.year, d.month, 1), date(d.year, d.month, last_day)
