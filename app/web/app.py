from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from app.config import get_settings
from app.web.auth import router as auth_router


BASE_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title="PVZ Admin",
        docs_url=None,
        redoc_url=None,
    )

    app.add_middleware(SessionMiddleware, secret_key=settings.web_secret_key)

    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    # Auth routes
    app.include_router(auth_router)

    # Import and register all CRUD routers
    from app.web.routers.dashboard import router as dashboard_router
    from app.web.routers.points import router as points_router
    from app.web.routers.employees import router as employees_router
    from app.web.routers.shifts import router as shifts_router
    from app.web.routers.defects import router as defects_router
    from app.web.routers.sos import router as sos_router
    from app.web.routers.supplies import router as supplies_router
    from app.web.routers.deliveries import router as deliveries_router
    from app.web.routers.appeals import router as appeals_router
    from app.web.routers.marketing import router as marketing_router
    from app.web.routers.reports import router as reports_router
    from app.web.routers.users import router as users_router
    from app.web.routers.audit import router as audit_router
    from app.web.routers.payroll import router as payroll_router
    from app.web.routers.adjustments import router as adjustments_router
    from app.web.routers.geofence import router as geofence_router
    from app.web.routers.marketplaces import router as marketplaces_router
    from app.web.routers.confirm import router as confirm_router
    from app.web.routers.salary import router as salary_router
    from app.web.routers.profile import router as profile_router
    from app.web.routers.reception import router as reception_router
    from app.web.routers.my import router as my_router

    app.include_router(dashboard_router)
    app.include_router(points_router)
    app.include_router(employees_router)
    app.include_router(shifts_router)
    app.include_router(defects_router)
    app.include_router(sos_router)
    app.include_router(supplies_router)
    app.include_router(deliveries_router)
    app.include_router(appeals_router)
    app.include_router(marketing_router)
    app.include_router(reports_router)
    app.include_router(users_router)
    app.include_router(audit_router)
    app.include_router(payroll_router)
    app.include_router(adjustments_router)
    app.include_router(geofence_router)
    app.include_router(marketplaces_router)
    app.include_router(confirm_router)
    app.include_router(salary_router)
    app.include_router(profile_router)
    app.include_router(reception_router)
    app.include_router(my_router)

    @app.exception_handler(401)
    async def unauthorized_handler(request: Request, exc):
        return RedirectResponse(url="/login", status_code=302)

    return app
