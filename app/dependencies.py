from pathlib import Path
from typing import Optional

from fastapi import Depends, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models.user import User
from app.utils import now_ist  # noqa: F401 — re-exported for routers

BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_current_user(request: Request, db: Session = Depends(get_db)) -> Optional[User]:
    user_id = request.session.get("user_id")
    if user_id:
        return db.query(User).filter(User.id == user_id).first()
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
    if user_id:
        db = SessionLocal()
        try:
            user = db.query(User).filter(User.id == user_id).first()
        finally:
            db.close()
    ctx = {
        "request": request,
        "user": user,
        "flashes": get_flashes(request),
    }
    ctx.update(kwargs)
    return ctx
