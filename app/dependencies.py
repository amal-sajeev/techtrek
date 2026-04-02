import time
from pathlib import Path
from typing import Optional

from fastapi import Depends, Request
from fastapi.responses import RedirectResponse
from starlette.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.config import settings
from app.csrf import get_csrf_token
from app.database import SessionLocal
from app.models.speaker import Speaker
from app.models.user import User
from app.utils import now_ist  # noqa: F401 — re-exported for routers

ASSET_VERSION = str(int(time.time()))

BASE_DIR = Path(__file__).resolve().parent

class CompatJinja2Templates(Jinja2Templates):
    """Accept both old and new Starlette TemplateResponse signatures."""

    def TemplateResponse(self, *args, **kwargs):
        # Old style used across this codebase:
        #   TemplateResponse("template.html", {"request": request, ...}, ...)
        if args and isinstance(args[0], str):
            name = args[0]
            context = args[1] if len(args) > 1 else kwargs.pop("context", {})
            if not isinstance(context, dict):
                raise TypeError("Template context must be a dict for old-style TemplateResponse calls.")
            request = context.get("request")
            if request is None:
                raise ValueError("Template context must include 'request'.")
            return super().TemplateResponse(request, name, context, **kwargs)
        # Starlette expects TemplateResponse(request, name: str, context, ...).
        # If code passes TemplateResponse(request, context_dict), Jinja2 receives a dict
        # as the template name and raises TypeError: unhashable type: 'dict'.
        if (
            len(args) >= 2
            and isinstance(args[0], Request)
            and isinstance(args[1], dict)
        ):
            raise TypeError(
                "TemplateResponse was called with (request, dict, ...). The second "
                "positional argument must be the template file name (str), not the "
                'context. Use TemplateResponse("path/template.html", context, ...) or '
                'TemplateResponse(request, "path/template.html", context, ...).'
            )
        # New style:
        #   TemplateResponse(request, "template.html", {...}, ...)
        return super().TemplateResponse(*args, **kwargs)


templates = CompatJinja2Templates(directory=str(BASE_DIR / "templates"))

def _gettext_noop(s: str) -> str:
    """Passthrough until real translations are wired up."""
    return s

templates.env.globals["_"] = _gettext_noop
templates.env.globals["gettext"] = _gettext_noop
templates.env.globals["asset_version"] = ASSET_VERSION


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_current_user(request: Request, db: Session = Depends(get_db)) -> Optional[User]:
    user_id = request.session.get("user_id")
    if user_id:
        user = db.query(User).filter(User.id == user_id, User.deleted_at.is_(None)).first()
        if not user:
            request.session.clear()
        return user
    return None


def require_auth(request: Request, db: Session = Depends(get_db)) -> User:
    user = get_current_user(request, db)
    if not user:
        raise _redirect_to_login(request)
    return user


def require_admin(request: Request, db: Session = Depends(get_db)) -> User:
    user = get_current_user(request, db)
    if not user or not user.is_admin:
        raise _redirect_to_login(request)
    return user


class AuthRedirect(Exception):
    def __init__(self, url: str):
        self.url = url


def _redirect_to_login(request: Request):
    return AuthRedirect(f"/auth/login?next={request.url.path}")


def flash(request: Request, message: str, category: str = "info"):
    flashes = request.session.get("_flashes", [])
    flashes.append({"message": message, "category": category})
    request.session["_flashes"] = flashes


def get_flashes(request: Request) -> list:
    return request.session.pop("_flashes", [])


def template_ctx(request: Request, **kwargs) -> dict:
    user_id = request.session.get("user_id")
    user = None
    is_speaker = False
    pending_feedback = []
    if user_id:
        db = SessionLocal()
        try:
            user = db.query(User).filter(User.id == user_id).first()
            if user:
                is_speaker = db.query(Speaker).filter(Speaker.user_id == user.id).first() is not None

                from app.models.feedback import Feedback
                from app.models.event import Event
                pending = (
                    db.query(Feedback)
                    .filter(
                        Feedback.user_id == user_id,
                        Feedback.submitted_at == None,  # noqa: E711
                        Feedback.dismissed == False,
                    )
                    .all()
                )
                for fb in pending:
                    event = db.query(Event).get(fb.event_id) if fb.event_id else None
                    if event:
                        from app.models.auditorium import Auditorium
                        aud = db.query(Auditorium).get(event.auditorium_id) if event.auditorium_id else None
                        pending_feedback.append({
                            "event_id": event.id,
                            "event_name": event.name,
                            "event_date": event.start_date.strftime("%d %b %Y") if event.start_date else "",
                            "venue": f"{aud.name}, {aud.location}" if aud else "",
                        })
        finally:
            db.close()
    # Count of published events (for nav: show Home/Events only when more than one)
    from sqlalchemy import func
    from app.models.event import Event
    db = SessionLocal()
    try:
        total_events = db.query(func.count(Event.id)).filter(Event.status == "published").scalar() or 0
    finally:
        db.close()
    ctx = {
        "request": request,
        "user": user,
        "is_speaker": is_speaker,
        "pending_feedback": pending_feedback,
        "flashes": get_flashes(request),
        "csrf_token": get_csrf_token(request),
        "google_sso": bool(settings.google_client_id),
        "total_events": total_events,
    }
    ctx.update(kwargs)
    return ctx