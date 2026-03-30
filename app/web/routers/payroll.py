from __future__ import annotations

import io
from datetime import date, datetime, timedelta
from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.models import (
    PayrollItem,
    PayrollRun,
    User,
)
from app.db.repositories import PayrollRepo, UserRepo
from app.services.payroll import PayrollService
from app.services.reports import ReportService
from app.web.deps import get_current_user, get_db, require_manager

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

router = APIRouter(prefix="/payroll", tags=["payroll"])


@router.get("", response_class=HTMLResponse)
async def list_payroll_runs(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_manager),
):
    repo = PayrollRepo(db)
    runs = await repo.list_runs(limit=50)

    return templates.TemplateResponse(request, "payroll/list.html", {
        "current_user": current_user,
        "active_page": "payroll",
        "runs": runs,
    })


@router.get("/generate", response_class=HTMLResponse)
async def generate_form(
    request: Request,
    current_user=Depends(require_manager),
):
    from app.utils.dates import payroll_period_for_payout

    today = date.today()
    p10_start, p10_end = payroll_period_for_payout(10, today)
    p25_start, p25_end = payroll_period_for_payout(25, today)

    return templates.TemplateResponse(request, "payroll/generate.html", {
        "current_user": current_user,
        "active_page": "payroll",
        "today": today,
        "p10_start": p10_start.isoformat(),
        "p10_end": p10_end.isoformat(),
        "p25_start": p25_start.isoformat(),
        "p25_end": p25_end.isoformat(),
        "error": None,
    })


@router.post("/generate")
async def generate_payroll(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_manager),
):
    form = await request.form()
    payout_day = int(form.get("payout_day", 10))
    period_start_str = form.get("period_start", "")
    period_end_str = form.get("period_end", "")

    try:
        period_start = date.fromisoformat(period_start_str)
        period_end = date.fromisoformat(period_end_str)
    except (ValueError, TypeError):
        return templates.TemplateResponse(request, "payroll/generate.html", {
            "current_user": current_user,
            "active_page": "payroll",
            "today": date.today(),
            "error": "Укажите корректные даты периода",
        })

    settings = get_settings()
    service = PayrollService(db, settings)
    run_id, results = await service.run_payroll(
        period_start=period_start,
        period_end=period_end,
        payout_day=payout_day,
        generated_by=current_user.id,
    )

    return RedirectResponse(url=f"/payroll/{run_id}", status_code=302)


@router.get("/{run_id}", response_class=HTMLResponse)
async def view_payroll_run(
    run_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_manager),
):
    result = await db.execute(select(PayrollRun).where(PayrollRun.id == run_id))
    run = result.scalar_one_or_none()
    if not run:
        return RedirectResponse(url="/payroll", status_code=302)

    repo = PayrollRepo(db)
    items = await repo.list_run_items(run_id)

    user_repo = UserRepo(db)
    users = await user_repo.list_all()
    users_map = {u.id: u for u in users}

    total_amount = sum(i.total_amount_rub or 0 for i in items)

    return templates.TemplateResponse(request, "payroll/detail.html", {
        "current_user": current_user,
        "active_page": "payroll",
        "run": run,
        "items": items,
        "users_map": users_map,
        "total_amount": total_amount,
    })


@router.get("/{run_id}/sheet/{item_id}", response_class=HTMLResponse)
async def view_employee_sheet(
    run_id: int,
    item_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_manager),
):
    result = await db.execute(select(PayrollRun).where(PayrollRun.id == run_id))
    run = result.scalar_one_or_none()
    if not run:
        return RedirectResponse(url="/payroll", status_code=302)

    result = await db.execute(select(PayrollItem).where(PayrollItem.id == item_id, PayrollItem.run_id == run_id))
    item = result.scalar_one_or_none()
    if not item:
        return RedirectResponse(url=f"/payroll/{run_id}", status_code=302)

    result = await db.execute(select(User).where(User.id == item.user_id))
    employee = result.scalar_one_or_none()

    return templates.TemplateResponse(request, "payroll/sheet.html", {
        "current_user": current_user,
        "active_page": "payroll",
        "run": run,
        "item": item,
        "employee": employee,
    })


@router.get("/{run_id}/export")
async def export_payroll_xlsx(
    run_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_manager),
):
    result = await db.execute(select(PayrollRun).where(PayrollRun.id == run_id))
    run = result.scalar_one_or_none()
    if not run:
        return RedirectResponse(url="/payroll", status_code=302)

    repo = PayrollRepo(db)
    items = await repo.list_run_items(run_id)

    user_repo = UserRepo(db)
    users = await user_repo.list_all()
    users_map = {u.id: u for u in users}

    from app.services.payroll import EmployeePayrollBreakdown
    breakdowns = []
    for item in items:
        user = users_map.get(item.user_id)
        if not user:
            continue
        breakdowns.append(EmployeePayrollBreakdown(
            user=user,
            shifts_count=item.shifts_count,
            hours_total=item.hours_total or 0,
            base_amount_rub=item.base_amount_rub or 0,
            motivation_amount_rub=item.motivation_amount_rub or 0,
            issued_bonus_rub=item.issued_bonus_rub or 0,
            dispute_deduction_rub=item.dispute_deduction_rub or 0,
            manager_bonus_rub=item.manager_bonus_rub or 0,
            adjustments_rub=item.adjustments_rub or 0,
            total_amount_rub=item.total_amount_rub or 0,
            issued_items_total=0,
            details={},
        ))

    svc = ReportService(export_dir="/tmp/pvz_exports")
    path = svc.export_payroll_summary_xlsx(run.period_start, run.period_end, breakdowns)

    def iterfile():
        with open(path, "rb") as f:
            yield from f

    filename = f"payroll_{run.period_start}_{run.period_end}.xlsx"
    return StreamingResponse(
        iterfile(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/{run_id}/export-sheets")
async def export_employee_sheets_xlsx(
    run_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_manager),
):
    result = await db.execute(select(PayrollRun).where(PayrollRun.id == run_id))
    run = result.scalar_one_or_none()
    if not run:
        return RedirectResponse(url="/payroll", status_code=302)

    repo = PayrollRepo(db)
    items = await repo.list_run_items(run_id)

    user_repo = UserRepo(db)
    users = await user_repo.list_all()
    users_map = {u.id: u for u in users}

    from app.services.payroll import EmployeePayrollBreakdown
    breakdowns = []
    for item in items:
        user = users_map.get(item.user_id)
        if not user:
            continue
        breakdowns.append(EmployeePayrollBreakdown(
            user=user,
            shifts_count=item.shifts_count,
            hours_total=item.hours_total or 0,
            base_amount_rub=item.base_amount_rub or 0,
            motivation_amount_rub=item.motivation_amount_rub or 0,
            issued_bonus_rub=item.issued_bonus_rub or 0,
            dispute_deduction_rub=item.dispute_deduction_rub or 0,
            manager_bonus_rub=item.manager_bonus_rub or 0,
            adjustments_rub=item.adjustments_rub or 0,
            total_amount_rub=item.total_amount_rub or 0,
            issued_items_total=0,
            details={},
        ))

    svc = ReportService(export_dir="/tmp/pvz_exports")
    path = svc.export_employee_payroll_sheets(run.period_start, run.period_end, breakdowns)

    def iterfile():
        with open(path, "rb") as f:
            yield from f

    filename = f"payroll_sheets_{run.period_start}_{run.period_end}.xlsx"
    return StreamingResponse(
        iterfile(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
