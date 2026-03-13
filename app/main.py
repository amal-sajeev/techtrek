import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.sessions import SessionMiddleware

from app.config import settings
from app.database import Base, engine
from app.dependencies import AuthRedirect, template_ctx, templates

BASE_DIR = Path(__file__).resolve().parent


# ---------------------------------------------------------------------------
# Security-headers middleware
# ---------------------------------------------------------------------------

class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Attach defensive HTTP response headers to every response."""

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("X-XSS-Protection", "1; mode=block")
        response.headers.setdefault(
            "Referrer-Policy", "strict-origin-when-cross-origin"
        )
        response.headers.setdefault(
            "Permissions-Policy", "camera=(), microphone=(), geolocation=()"
        )
        # Only send HSTS over HTTPS (i.e., when not in debug/dev mode).
        if not settings.debug:
            response.headers.setdefault(
                "Strict-Transport-Security",
                "max-age=31536000; includeSubDomains",
            )
        return response


@asynccontextmanager
async def lifespan(app: FastAPI):
    from app.services.feedback import feedback_task_loop
    task = asyncio.create_task(feedback_task_loop())
    yield
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


application = FastAPI(
    title="TechTrek",
    docs_url="/api/docs" if settings.debug else None,
    lifespan=lifespan,
)

# Security headers must be added before session middleware so they apply to
# every response including error pages.
application.add_middleware(SecurityHeadersMiddleware)
application.add_middleware(
    SessionMiddleware,
    secret_key=settings.secret_key,
    https_only=not settings.debug,
    same_site="lax",
    max_age=86400,
)
application.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")

from app import models as _models  # noqa: F401, E402

Base.metadata.create_all(bind=engine)

from app.routers import auth, public, booking, admin, supervisor, speaker  # noqa: E402
from app.routers import webhook  # noqa: E402

application.include_router(auth.router)
application.include_router(public.router)
application.include_router(booking.router)
application.include_router(admin.router)
application.include_router(supervisor.router)
application.include_router(speaker.router)
application.include_router(webhook.router)

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
