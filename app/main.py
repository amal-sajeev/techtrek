from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from app.config import settings
from app.database import Base, engine, ensure_sqlite_columns
from app.dependencies import AuthRedirect, template_ctx, templates

BASE_DIR = Path(__file__).resolve().parent

app = FastAPI(title="TechTrek", docs_url="/api/docs" if settings.debug else None)
app.add_middleware(SessionMiddleware, secret_key=settings.secret_key)
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")

from app import models as _models  # noqa: F401, E402

Base.metadata.create_all(bind=engine)
ensure_sqlite_columns()

from app.routers import auth, public, booking, admin  # noqa: E402

app.include_router(auth.router)
app.include_router(public.router)
app.include_router(booking.router)
app.include_router(admin.router)


@app.exception_handler(AuthRedirect)
async def auth_redirect_handler(_request: Request, exc: AuthRedirect):
    return RedirectResponse(exc.url, status_code=303)


@app.exception_handler(404)
async def not_found(request: Request, _exc):
    return templates.TemplateResponse(
        "errors/404.html", template_ctx(request), status_code=404
    )


@app.exception_handler(500)
async def server_error(request: Request, _exc):
    return templates.TemplateResponse(
        "errors/500.html", template_ctx(request), status_code=500
    )
