from __future__ import annotations

from datetime import date
from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from decimal import Decimal, InvalidOperation

from app.db.models import (
    Point,
    SupplyItem,
    SupplyRequestHeader,
    SupplyRequestItem,
    SupplyStatusLog,
    WebUser,
)
from app.web.deps import get_current_user, get_db

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

router = APIRouter(prefix="/supplies", tags=["supplies"])

REQUEST_STATUSES = [
    ("new", "Новая"),
    ("partially_ordered", "Частично заказана"),
    ("ordered", "Заказана"),
    ("in_transit", "В пути"),
    ("partially_delivered", "Частично выдана"),
    ("delivered", "Выдана"),
    ("closed", "Закрыта"),
    ("cancelled", "Отменена"),
]

REQUEST_STATUS_LABELS = dict(REQUEST_STATUSES)

LINE_ITEM_STATUSES = [
    ("requested", "Запрошено"),
    ("ordered", "Заказано"),
    ("in_transit", "В пути"),
    ("delivered", "Выдано"),
    ("in_stock", "Есть в наличии"),
    ("not_needed", "Не требуется"),
    ("cancelled", "Отменено"),
]

LINE_ITEM_STATUS_LABELS = dict(LINE_ITEM_STATUSES)


@router.get("", response_class=HTMLResponse)
async def list_supplies(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: WebUser = Depends(get_current_user),
    point_id: int = 0,
    status: str = "",
    page: int = 1,
):
    per_page = 25
    query = select(SupplyRequestHeader)

    if point_id:
        query = query.where(SupplyRequestHeader.point_id == point_id)
    if status:
        query = query.where(SupplyRequestHeader.status == status)

    total = (await db.execute(select(func.count()).select_from(query.subquery()))).scalar() or 0
    query = query.order_by(SupplyRequestHeader.request_date.desc())
    query = query.offset((page - 1) * per_page).limit(per_page)
    result = await db.execute(query)
    items = result.scalars().all()
    total_pages = max(1, (total + per_page - 1) // per_page)

    points_result = await db.execute(select(Point).where(Point.is_active == True))
    points = points_result.scalars().all()
    points_map = {p.id: p for p in points}

    # Count ordered line items per request
    request_ids = [i.id for i in items]
    items_count_map: dict[int, int] = {}
    if request_ids:
        counts_result = await db.execute(
            select(SupplyRequestItem.request_id, func.count(SupplyRequestItem.id))
            .where(SupplyRequestItem.request_id.in_(request_ids))
            .group_by(SupplyRequestItem.request_id)
        )
        items_count_map = {row[0]: row[1] for row in counts_result.all()}

    return templates.TemplateResponse(request, "supplies/list.html", {"current_user": current_user,
        "active_page": "supplies",
        "items": items,
        "total": total,
        "page": page,
        "total_pages": total_pages,
        "points": points,
        "points_map": points_map,
        "point_id": point_id,
        "status": status,
        "statuses": REQUEST_STATUSES,
        "request_status_labels": REQUEST_STATUS_LABELS,
        "items_count_map": items_count_map})


@router.get("/catalog", response_class=HTMLResponse)
async def supply_catalog(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: WebUser = Depends(get_current_user),
):
    result = await db.execute(select(SupplyItem).order_by(SupplyItem.category, SupplyItem.name))
    items = result.scalars().all()

    return templates.TemplateResponse(request, "supplies/catalog.html", {"current_user": current_user,
        "active_page": "supplies",
        "items": items})


@router.get("/new", response_class=HTMLResponse)
async def new_supply_request(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: WebUser = Depends(get_current_user),
):
    points_result = await db.execute(select(Point).where(Point.is_active == True))
    points = points_result.scalars().all()

    items_result = await db.execute(select(SupplyItem).where(SupplyItem.is_active == True).order_by(SupplyItem.category, SupplyItem.name))
    supply_items = items_result.scalars().all()

    return templates.TemplateResponse(request, "supplies/form.html", {"current_user": current_user,
        "active_page": "supplies",
        "item": None,
        "points": points,
        "supply_items": supply_items,
        "statuses": REQUEST_STATUSES,
        "today": date.today().strftime("%Y-%m-%d"),
        "error": None})


@router.post("/new")
async def create_supply_request(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: WebUser = Depends(get_current_user),
):
    form = await request.form()

    all_good = form.get("all_good", "") == "1"

    header = SupplyRequestHeader(
        point_id=int(form["point_id"]),
        request_date=date.today(),
        status="delivered" if all_good else "new",
        comment=form.get("comment", "").strip() or ("Всё есть" if all_good else None),
        created_by_user_id=current_user.id,
    )
    db.add(header)
    await db.flush()

    # Process line items — only when specific items were marked as ordered
    if not all_good:
        items_result = await db.execute(select(SupplyItem).where(SupplyItem.is_active == True))
        for si in items_result.scalars().all():
            qty_raw = form.get(f"qty_{si.id}", "").strip()
            # Item is "ordered" if qty was filled OR if the qty field was submitted
            # (the form only shows qty for items toggled as ordered)
            if qty_raw:
                try:
                    qty_val = float(qty_raw)
                except ValueError:
                    qty_val = None
                line = SupplyRequestItem(
                    request_id=header.id,
                    supply_item_id=si.id,
                    requested_qty=qty_val,
                    item_status="requested",
                )
                db.add(line)

    await db.commit()
    return RedirectResponse(url="/supplies", status_code=302)


@router.get("/{request_id}", response_class=HTMLResponse)
async def supply_detail(
    request_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: WebUser = Depends(get_current_user),
):
    result = await db.execute(select(SupplyRequestHeader).where(SupplyRequestHeader.id == request_id))
    header = result.scalar_one_or_none()
    if not header:
        return RedirectResponse(url="/supplies", status_code=302)

    items_result = await db.execute(
        select(SupplyRequestItem).where(SupplyRequestItem.request_id == request_id)
    )
    line_items = items_result.scalars().all()

    supply_items_result = await db.execute(select(SupplyItem))
    supply_items_map = {s.id: s for s in supply_items_result.scalars().all()}

    points_result = await db.execute(select(Point))
    points_map = {p.id: p for p in points_result.scalars().all()}

    # History
    from app.db.models import WebUser as WU
    logs_result = await db.execute(
        select(SupplyStatusLog)
        .where(SupplyStatusLog.request_id == request_id)
        .order_by(SupplyStatusLog.changed_at.desc())
    )
    logs = logs_result.scalars().all()
    wu_result = await db.execute(select(WU))
    web_users_map = {u.id: u for u in wu_result.scalars().all()}

    return templates.TemplateResponse(request, "supplies/detail.html", {"current_user": current_user,
        "active_page": "supplies",
        "item": header,
        "line_items": line_items,
        "supply_items_map": supply_items_map,
        "points_map": points_map,
        "statuses": REQUEST_STATUSES,
        "line_item_statuses": LINE_ITEM_STATUSES,
        "request_status_labels": REQUEST_STATUS_LABELS,
        "line_item_status_labels": LINE_ITEM_STATUS_LABELS,
        "logs": logs,
        "web_users_map": web_users_map})


@router.post("/{request_id}/status")
async def update_supply_status(
    request_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: WebUser = Depends(get_current_user),
):
    result = await db.execute(select(SupplyRequestHeader).where(SupplyRequestHeader.id == request_id))
    header = result.scalar_one_or_none()
    if not header:
        return RedirectResponse(url="/supplies", status_code=302)

    form = await request.form()
    new_status = str(form.get("status", "")).strip()
    comment = str(form.get("comment", "")).strip() or None

    if new_status and new_status != header.status:
        log = SupplyStatusLog(
            request_id=request_id,
            line_item_id=None,
            old_status=header.status,
            new_status=new_status,
            comment=comment,
            changed_by_user_id=current_user.id,
        )
        db.add(log)
        header.status = new_status
        header.updated_by_user_id = current_user.id
        await db.commit()

    return RedirectResponse(url=f"/supplies/{request_id}", status_code=302)


@router.post("/{request_id}/line/{line_id}/status")
async def update_line_item_status(
    request_id: int,
    line_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: WebUser = Depends(get_current_user),
):
    result = await db.execute(
        select(SupplyRequestItem).where(
            SupplyRequestItem.id == line_id,
            SupplyRequestItem.request_id == request_id,
        )
    )
    line = result.scalar_one_or_none()
    if not line:
        return RedirectResponse(url=f"/supplies/{request_id}", status_code=302)

    form = await request.form()
    new_status = str(form.get("status", "")).strip()
    comment = str(form.get("comment", "")).strip() or None

    if new_status and new_status != line.item_status:
        log = SupplyStatusLog(
            request_id=request_id,
            line_item_id=line_id,
            old_status=line.item_status,
            new_status=new_status,
            comment=comment,
            changed_by_user_id=current_user.id,
        )
        db.add(log)
        line.item_status = new_status
        await db.commit()

    return RedirectResponse(url=f"/supplies/{request_id}", status_code=302)


@router.post("/catalog/new")
async def create_catalog_item(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: WebUser = Depends(get_current_user),
):
    form = await request.form()
    name = str(form.get("name", "")).strip()
    if not name:
        return RedirectResponse(url="/supplies/catalog", status_code=302)

    min_qty_raw = str(form.get("min_qty", "")).strip()
    try:
        min_qty = Decimal(min_qty_raw) if min_qty_raw else None
    except InvalidOperation:
        min_qty = None

    item = SupplyItem(
        name=name,
        category=str(form.get("category", "")).strip() or None,
        unit=str(form.get("unit", "шт")).strip() or "шт",
        min_qty=min_qty,
        comment=str(form.get("comment", "")).strip() or None,
        is_active=True,
    )
    db.add(item)
    await db.commit()
    return RedirectResponse(url="/supplies/catalog", status_code=302)


@router.post("/catalog/{item_id}/toggle")
async def toggle_catalog_item(
    item_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: WebUser = Depends(get_current_user),
):
    result = await db.execute(select(SupplyItem).where(SupplyItem.id == item_id))
    item = result.scalar_one_or_none()
    if item:
        item.is_active = not item.is_active
        await db.commit()
    return RedirectResponse(url="/supplies/catalog", status_code=302)
