from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from app.config import settings
from sqlalchemy import text

from app.database import Base, engine
from app.dependencies import AuthRedirect, template_ctx, templates

BASE_DIR = Path(__file__).resolve().parent

application = FastAPI(title="TechTrek", docs_url="/api/docs" if settings.debug else None)
application.add_middleware(SessionMiddleware, secret_key=settings.secret_key)
application.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")

from app import models as _models  # noqa: F401, E402

Base.metadata.create_all(bind=engine)

with engine.connect() as conn:
    for col in ("price_vip", "price_accessible"):
        try:
            conn.execute(text(f"ALTER TABLE lecture_sessions ADD COLUMN {col} NUMERIC(10,2)"))
            conn.commit()
        except Exception:
            conn.rollback()
    for col, col_type in [("booking_group", "VARCHAR(20)"), ("group_qr_data", "TEXT")]:
        try:
            conn.execute(text(f"ALTER TABLE bookings ADD COLUMN {col} {col_type}"))
            conn.commit()
        except Exception:
            conn.rollback()
    for col, col_type in [
        ("razorpay_order_id", "VARCHAR(50)"),
        ("razorpay_payment_id", "VARCHAR(50)"),
        ("razorpay_signature", "VARCHAR(128)"),
    ]:
        try:
            conn.execute(text(f"ALTER TABLE bookings ADD COLUMN {col} {col_type}"))
            conn.commit()
        except Exception:
            conn.rollback()
    for col, col_type in [("is_supervisor", "BOOLEAN DEFAULT FALSE")]:
        try:
            conn.execute(text(f"ALTER TABLE users ADD COLUMN {col} {col_type}"))
            conn.commit()
        except Exception:
            conn.rollback()

from app.routers import auth, public, booking, admin, supervisor  # noqa: E402

application.include_router(auth.router)
application.include_router(public.router)
application.include_router(booking.router)
application.include_router(admin.router)
application.include_router(supervisor.router)

app = application


@application.exception_handler(AuthRedirect)
async def auth_redirect_handler(_request: Request, exc: AuthRedirect):
    return RedirectResponse(exc.url, status_code=303)


@application.exception_handler(404)
async def not_found(request: Request, _exc):
    return templates.TemplateResponse(
        "errors/404.html", template_ctx(request), status_code=404
    )


@application.exception_handler(500)
async def server_error(request: Request, _exc):
    return templates.TemplateResponse(
        "errors/500.html", template_ctx(request), status_code=500
    )
