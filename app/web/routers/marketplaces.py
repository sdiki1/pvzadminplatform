from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Marketplace
from app.web.deps import get_current_user, get_db, require_manager

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

router = APIRouter(prefix="/marketplaces", tags=["marketplaces"])


@router.get("", response_class=HTMLResponse)
async def list_marketplaces(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    result = await db.execute(select(Marketplace).order_by(Marketplace.name))
    items = result.scalars().all()

    return templates.TemplateResponse(request, "marketplaces/list.html", {
        "current_user": current_user,
        "active_page": "marketplaces",
        "items": items,
    })


@router.get("/new", response_class=HTMLResponse)
async def new_marketplace(
    request: Request,
    current_user=Depends(require_manager),
):
    return templates.TemplateResponse(request, "marketplaces/form.html", {
        "current_user": current_user,
        "active_page": "marketplaces",
        "item": None,
        "error": None,
    })


@router.post("/new")
async def create_marketplace(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_manager),
):
    form = await request.form()
    code = form.get("code", "").strip().lower()
    name = form.get("name", "").strip()

    if not code or not name:
        return templates.TemplateResponse(request, "marketplaces/form.html", {
            "current_user": current_user,
            "active_page": "marketplaces",
            "item": None,
            "error": "Код и название обязательны",
        })

    existing = await db.execute(select(Marketplace).where(Marketplace.code == code))
    if existing.scalar_one_or_none():
        return templates.TemplateResponse(request, "marketplaces/form.html", {
            "current_user": current_user,
            "active_page": "marketplaces",
            "item": None,
            "error": f"Маркетплейс с кодом «{code}» уже существует",
        })

    db.add(Marketplace(code=code, name=name, is_active=form.get("is_active") != "off"))
    await db.commit()
    return RedirectResponse(url="/marketplaces", status_code=302)


@router.get("/{mp_id}/edit", response_class=HTMLResponse)
async def edit_marketplace(
    mp_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_manager),
):
    result = await db.execute(select(Marketplace).where(Marketplace.id == mp_id))
    item = result.scalar_one_or_none()
    if not item:
        return RedirectResponse(url="/marketplaces", status_code=302)

    return templates.TemplateResponse(request, "marketplaces/form.html", {
        "current_user": current_user,
        "active_page": "marketplaces",
        "item": item,
        "error": None,
    })


@router.post("/{mp_id}/edit")
async def update_marketplace(
    mp_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_manager),
):
    result = await db.execute(select(Marketplace).where(Marketplace.id == mp_id))
    item = result.scalar_one_or_none()
    if not item:
        return RedirectResponse(url="/marketplaces", status_code=302)

    form = await request.form()
    item.name = form.get("name", "").strip() or item.name
    item.is_active = form.get("is_active") == "on"
    await db.commit()
    return RedirectResponse(url="/marketplaces", status_code=302)
