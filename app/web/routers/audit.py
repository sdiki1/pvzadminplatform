from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AuditLog, WebUser
from app.web.deps import get_db, require_admin

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

router = APIRouter(prefix="/audit", tags=["audit"])


@router.get("", response_class=HTMLResponse)
async def list_audit(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: WebUser = Depends(require_admin),
    entity_type: str = "",
    action_type: str = "",
    date_from: str = "",
    date_to: str = "",
    page: int = 1,
):
    per_page = 50
    query = select(AuditLog)

    if entity_type:
        query = query.where(AuditLog.entity_type == entity_type)
    if action_type:
        query = query.where(AuditLog.action_type == action_type)
    if date_from:
        query = query.where(AuditLog.changed_at >= date_from)
    if date_to:
        query = query.where(AuditLog.changed_at <= date_to)

    total = (await db.execute(select(func.count()).select_from(query.subquery()))).scalar() or 0
    query = query.order_by(AuditLog.changed_at.desc())
    query = query.offset((page - 1) * per_page).limit(per_page)
    result = await db.execute(query)
    items = result.scalars().all()
    total_pages = max(1, (total + per_page - 1) // per_page)

    # User lookup
    users_result = await db.execute(select(WebUser))
    users_map = {u.id: u for u in users_result.scalars().all()}

    return templates.TemplateResponse("audit/list.html", {
        "request": request,
        "current_user": current_user,
        "active_page": "audit",
        "items": items,
        "total": total,
        "page": page,
        "total_pages": total_pages,
        "users_map": users_map,
        "entity_type": entity_type,
        "action_type": action_type,
        "date_from": date_from,
        "date_to": date_to,
    })
