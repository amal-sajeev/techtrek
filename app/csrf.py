import secrets

from fastapi import Form, HTTPException, Request


def get_csrf_token(request: Request) -> str:
    """Return the session CSRF token, creating one if it doesn't exist."""
    token = request.session.get("csrf_token")
    if not token:
        token = secrets.token_hex(32)
        request.session["csrf_token"] = token
    return token


def _verify_csrf_token(request: Request, submitted: str) -> None:
    """Raise 403 if the submitted token doesn't match the session token."""
    expected = request.session.get("csrf_token", "")
    if not expected or not secrets.compare_digest(expected, submitted):
        raise HTTPException(status_code=403, detail="Invalid or missing CSRF token.")


async def require_csrf_form(request: Request, csrf_token: str = Form(default="")) -> None:
    """FastAPI dependency for explicit form-based POST endpoints."""
    _verify_csrf_token(request, csrf_token)


async def csrf_protection(request: Request, csrf_token: str = Form(default="")) -> None:
    """Router-level dependency: skip CSRF for safe methods and JSON requests."""
    if request.method not in ("POST", "PUT", "PATCH", "DELETE"):
        return
    content_type = request.headers.get("content-type", "")
    if "application/json" in content_type:
        # JSON/XHR endpoints are protected by SameSite=lax + session auth
        return
    _verify_csrf_token(request, csrf_token)
