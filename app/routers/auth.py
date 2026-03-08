import bcrypt
from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.dependencies import flash, get_db, template_ctx, templates
from app.models.user import User

router = APIRouter(prefix="/auth", tags=["auth"])


def _hash_pw(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def _verify_pw(password: str, hashed: str) -> bool:
    return bcrypt.checkpw(password.encode(), hashed.encode())


@router.get("/login")
def login_page(request: Request):
    return templates.TemplateResponse("auth/login.html", template_ctx(request))


@router.post("/login")
async def login(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    login_id = form.get("username", "").strip()  # can be username or email
    password = form.get("password", "")

    user = db.query(User).filter(
        (User.username == login_id) | (User.email == login_id)
    ).first()
    if not user or not _verify_pw(password, user.password_hash):
        flash(request, "Invalid username/email or password.", "danger")
        return RedirectResponse("/auth/login", status_code=303)

    request.session["user_id"] = user.id
    flash(request, f"Welcome back, {user.username}!", "success")
    next_url = request.query_params.get("next", "/")
    return RedirectResponse(next_url, status_code=303)


@router.get("/register")
def register_page(request: Request):
    return templates.TemplateResponse("auth/register.html", template_ctx(request))


@router.post("/register")
async def register(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    username = form.get("username", "").strip()
    email = form.get("email", "").strip()
    password = form.get("password", "")
    confirm = form.get("confirm_password", "")

    errors = []
    if not username or len(username) < 3:
        errors.append("Username must be at least 3 characters.")
    if not email or "@" not in email:
        errors.append("Please enter a valid email.")
    if len(password) < 6:
        errors.append("Password must be at least 6 characters.")
    if password != confirm:
        errors.append("Passwords do not match.")
    if db.query(User).filter(User.email == email).first():
        errors.append("An account with this email already exists.")
    if db.query(User).filter(User.username == username).first():
        errors.append("This username is taken.")

    if errors:
        for e in errors:
            flash(request, e, "danger")
        return RedirectResponse("/auth/register", status_code=303)

    is_first_user = db.query(User).count() == 0
    user = User(
        username=username,
        email=email,
        password_hash=_hash_pw(password),
        is_admin=is_first_user,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    request.session["user_id"] = user.id
    msg = "Account created! You are the admin." if is_first_user else "Account created!"
    flash(request, msg, "success")
    return RedirectResponse("/", status_code=303)


@router.get("/logout")
def logout(request: Request):
    request.session.clear()
    flash(request, "You have been logged out.", "info")
    return RedirectResponse("/", status_code=303)
