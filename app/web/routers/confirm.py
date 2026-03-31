from __future__ import annotations

import json
import logging
from datetime import date
from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.models import WebUser
from app.services.email import EmailService  # used by verify_code
from app.web.deps import get_current_user, get_db

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

log = logging.getLogger(__name__)

router = APIRouter(prefix="/confirm", tags=["confirm"])

OPERATION_LABELS = {
    "payroll_generate": "Формирование расчётной ведомости",
    "user_create": "Создание пользователя",
    "user_edit_role": "Изменение роли / деактивация пользователя",
}


def _email_service() -> EmailService:
    return EmailService(get_settings())


@router.get("/verify", response_class=HTMLResponse)
async def verify_form(
    request: Request,
    operation: str,
    current_user: WebUser = Depends(get_current_user),
):
    label = OPERATION_LABELS.get(operation, operation)
    settings = get_settings()
    return templates.TemplateResponse(request, "confirm/verify.html", {
        "current_user": current_user,
        "active_page": "",
        "operation": operation,
        "operation_label": label,
        "error": None,
        "admin_email": current_user.email or "",
        "ttl_minutes": settings.email_code_ttl_minutes,
    })


@router.post("/verify")
async def do_verify(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: WebUser = Depends(get_current_user),
):
    form = await request.form()
    operation = str(form.get("operation", ""))
    code = str(form.get("code", "")).strip()

    email_svc = _email_service()
    ok, conf = await email_svc.verify_code(db, current_user.id, operation, code)

    if not ok:
        label = OPERATION_LABELS.get(operation, operation)
        settings = get_settings()
        return templates.TemplateResponse(request, "confirm/verify.html", {
            "current_user": current_user,
            "active_page": "",
            "operation": operation,
            "operation_label": label,
            "error": "Неверный или истёкший код. Попробуйте ещё раз.",
            "admin_email": current_user.email or "",
            "ttl_minutes": settings.email_code_ttl_minutes,
        })

    payload: dict = json.loads(conf.payload_json) if conf.payload_json else {}
    return await _dispatch(operation, payload, db, current_user)


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------

async def _dispatch(operation: str, payload: dict, db: AsyncSession, current_user: WebUser):
    if operation == "payroll_generate":
        return await _exec_payroll_generate(payload, db, current_user)
    if operation == "user_create":
        return await _exec_user_create(payload, db)
    if operation == "user_edit_role":
        return await _exec_user_edit(payload, db)
    return RedirectResponse(url="/", status_code=302)


# ---------------------------------------------------------------------------
# Execution helpers
# ---------------------------------------------------------------------------

async def _exec_payroll_generate(payload: dict, db: AsyncSession, current_user: WebUser):
    from app.services.payroll import PayrollService  # local import avoids cycles

    period_start = date.fromisoformat(payload["period_start"])
    period_end = date.fromisoformat(payload["period_end"])
    payout_day = int(payload["payout_day"])

    settings = get_settings()
    service = PayrollService(db, settings)
    run_id, _ = await service.run_payroll(
        period_start=period_start,
        period_end=period_end,
        payout_day=payout_day,
        generated_by=current_user.id,
    )
    return RedirectResponse(url=f"/payroll/{run_id}", status_code=302)


async def _exec_user_create(payload: dict, db: AsyncSession):
    roles = payload.get("roles") or ["viewer"]
    user = WebUser(
        login=payload["login"],
        password_hash=payload["password_hash"],
        full_name=payload.get("full_name") or payload["login"],
        phone=payload.get("phone") or None,
        email=payload.get("email") or None,
        roles_json=json.dumps(roles),
        is_active=payload.get("is_active", True),
    )
    db.add(user)
    await db.commit()
    return RedirectResponse(url="/users", status_code=302)


async def _exec_user_edit(payload: dict, db: AsyncSession):
    user_id = int(payload["user_id"])
    result = await db.execute(select(WebUser).where(WebUser.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        return RedirectResponse(url="/users", status_code=302)

    user.full_name = payload.get("full_name") or user.full_name
    user.phone = payload.get("phone") or None
    user.email = payload.get("email") or None
    if "roles" in payload:
        user.roles_json = json.dumps(payload["roles"])
    user.is_active = bool(payload.get("is_active", user.is_active))
    if payload.get("password_hash"):
        user.password_hash = payload["password_hash"]

    await db.commit()
    return RedirectResponse(url="/users", status_code=302)
