import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from app.config import settings
from app.database import Base, engine
from app.dependencies import AuthRedirect, template_ctx, templates

BASE_DIR = Path(__file__).resolve().parent


# ---------------------------------------------------------------------------
# Security-headers middleware  (pure ASGI — avoids BaseHTTPMiddleware
# buffering that stalls SSE StreamingResponse connections)
# ---------------------------------------------------------------------------

_SECURITY_DEFAULTS = [
    (b"x-content-type-options", b"nosniff"),
    (b"x-frame-options", b"DENY"),
    (b"x-xss-protection", b"1; mode=block"),
    (b"referrer-policy", b"strict-origin-when-cross-origin"),
    (b"permissions-policy", b"camera=(self), microphone=(), geolocation=()"),
]

_HSTS_HEADER = (
    b"strict-transport-security",
    b"max-age=31536000; includeSubDomains",
)


class SecurityHeadersMiddleware:
    """Attach defensive HTTP response headers to every response."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_headers(message):
            if message["type"] == "http.response.start":
                raw = list(message.get("headers", []))
                existing = {k for k, _ in raw}
                for k, v in _SECURITY_DEFAULTS:
                    if k not in existing:
                        raw.append((k, v))
                if not settings.debug and _HSTS_HEADER[0] not in existing:
                    raw.append(_HSTS_HEADER)
                message = {**message, "headers": raw}
            await send(message)

        await self.app(scope, receive, send_with_headers)


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

if settings.debug:
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


@application.get("/service-worker.js", include_in_schema=False)
async def service_worker():
    sw_path = BASE_DIR / "static" / "service-worker.js"
    return FileResponse(sw_path, media_type="application/javascript",
                        headers={"Cache-Control": "no-cache", "Service-Worker-Allowed": "/"})


@application.get("/offline", include_in_schema=False)
async def offline_page(request: Request):
    return templates.TemplateResponse("offline.html", template_ctx(request))


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
