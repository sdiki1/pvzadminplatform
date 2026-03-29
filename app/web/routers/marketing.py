from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import MarketingSurvey, WebUser
from app.web.deps import get_current_user, get_db

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

router = APIRouter(prefix="/marketing", tags=["marketing"])


@router.get("", response_class=HTMLResponse)
async def list_surveys(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: WebUser = Depends(get_current_user),
    search: str = "",
    date_from: str = "",
    date_to: str = "",
    page: int = 1,
):
    per_page = 25
    query = select(MarketingSurvey)

    if search:
        query = query.where(
            MarketingSurvey.child_full_name.ilike(f"%{search}%")
            | MarketingSurvey.parent_full_name.ilike(f"%{search}%")
            | MarketingSurvey.phone.ilike(f"%{search}%")
        )
    if date_from:
        query = query.where(MarketingSurvey.survey_date >= date_from)
    if date_to:
        query = query.where(MarketingSurvey.survey_date <= date_to)

    total = (await db.execute(select(func.count()).select_from(query.subquery()))).scalar() or 0
    query = query.order_by(MarketingSurvey.survey_date.desc())
    query = query.offset((page - 1) * per_page).limit(per_page)
    result = await db.execute(query)
    items = result.scalars().all()
    total_pages = max(1, (total + per_page - 1) // per_page)

    return templates.TemplateResponse("marketing/list.html", {
        "request": request,
        "current_user": current_user,
        "active_page": "marketing",
        "items": items,
        "total": total,
        "page": page,
        "total_pages": total_pages,
        "search": search,
        "date_from": date_from,
        "date_to": date_to,
    })


@router.get("/new", response_class=HTMLResponse)
async def new_survey(
    request: Request,
    current_user: WebUser = Depends(get_current_user),
):
    return templates.TemplateResponse("marketing/form.html", {
        "request": request,
        "current_user": current_user,
        "active_page": "marketing",
        "item": None,
        "error": None,
    })


@router.post("/new")
async def create_survey(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: WebUser = Depends(get_current_user),
):
    form = await request.form()

    age_raw = form.get("child_age_raw", "").strip()
    age_years = None
    if age_raw:
        try:
            age_years = int(age_raw.split()[0])
        except (ValueError, IndexError):
            pass

    survey = MarketingSurvey(
        child_full_name=form.get("child_full_name", "").strip(),
        child_age_raw=age_raw or None,
        child_age_years=age_years,
        parent_full_name=form.get("parent_full_name", "").strip(),
        phone=form.get("phone", "").strip() or None,
        residential_address=form.get("residential_address", "").strip() or None,
        buys_on_wb=form.get("buys_on_wb") == "on",
        current_pickup_point_text=form.get("current_pickup_point_text", "").strip() or None,
        attraction_reason=form.get("attraction_reason", "").strip() or None,
        personal_data_consent=form.get("personal_data_consent") == "on",
        survey_date=form["survey_date"],
        coupon_given=form.get("coupon_given") == "on",
        comment=form.get("comment", "").strip() or None,
        created_by_user_id=current_user.id,
    )
    db.add(survey)
    await db.commit()
    return RedirectResponse(url="/marketing", status_code=302)
