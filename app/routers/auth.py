import bcrypt
from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.dependencies import flash, get_db, now_ist, template_ctx, templates
from app.models.speaker import Speaker
from app.models.user import User
from app.services.activity_log import log_activity
from app.services.email import send_signup_confirmation

router = APIRouter(prefix="/auth", tags=["auth"])


def _hash_pw(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def _verify_pw(password: str, hashed: str) -> bool:
    return bcrypt.checkpw(password.encode(), hashed.encode())


def _try_link_speaker_token(request: Request, db: Session, user: User):
    """If the session contains a pending speaker invite token, link the user."""
    token = request.session.pop("pending_speaker_token", None)
    if not token:
        return
    speaker = db.query(Speaker).filter(
        Speaker.invite_token == token,
        Speaker.user_id.is_(None),
    ).first()
    if not speaker:
        return
    if speaker.invite_token_expires and speaker.invite_token_expires < now_ist():
        flash(request, "Speaker invite has expired. Ask admin to resend.", "danger")
        return
    speaker.user_id = user.id
    speaker.invite_token = None
    speaker.invite_token_expires = None
    db.commit()
    flash(request, f"Your account is now linked as speaker: {speaker.name}", "success")


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
        log_activity(db, category="auth", action="login_failed", description=f"Failed login attempt for '{login_id}'", request=request)
        db.commit()
        flash(request, "Invalid username/email or password.", "danger")
        return RedirectResponse("/auth/login", status_code=303)

    request.session["user_id"] = user.id
    _try_link_speaker_token(request, db, user)
    log_activity(db, category="auth", action="login", description=f"{user.username} logged in", request=request, user_id=user.id, target_type="user", target_id=user.id)
    db.commit()
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
    full_name = form.get("full_name", "").strip()
    college = form.get("college", "").strip()
    discipline = form.get("discipline", "").strip()
    domain = form.get("domain", "").strip()
    year_raw = form.get("year_of_study", "")
    password = form.get("password", "")
    confirm = form.get("confirm_password", "")

    errors = []
    if not username or len(username) < 3:
        errors.append("Username must be at least 3 characters.")
    if not email or "@" not in email:
        errors.append("Please enter a valid email.")
    if not full_name:
        errors.append("Full name is required.")
    if len(password) < 6:
        errors.append("Password must be at least 6 characters.")
    if password != confirm:
        errors.append("Passwords do not match.")
    if db.query(User).filter(User.email == email).first():
        errors.append("An account with this email already exists.")
    if db.query(User).filter(User.username == username).first():
        errors.append("This username is taken.")

    year_of_study = None
    if year_raw:
        try:
            year_of_study = int(year_raw)
        except ValueError:
            pass

    if errors:
        for e in errors:
            flash(request, e, "danger")
        return RedirectResponse("/auth/register", status_code=303)

    is_first_user = db.query(User).count() == 0
    user = User(
        username=username,
        email=email,
        full_name=full_name,
        college=college or None,
        discipline=discipline or None,
        domain=domain or None,
        year_of_study=year_of_study,
        password_hash=_hash_pw(password),
        is_admin=is_first_user,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    request.session["user_id"] = user.id
    _try_link_speaker_token(request, db, user)
    log_activity(db, category="auth", action="register", description=f"New user registered: {user.username} ({user.email})", request=request, user_id=user.id, target_type="user", target_id=user.id)
    db.commit()
    msg = "Account created! You are the admin." if is_first_user else "Account created!"
    flash(request, msg, "success")
    send_signup_confirmation(user.email, user.username)
    next_url = request.session.pop("speaker_invite_next", "/")
    return RedirectResponse(next_url, status_code=303)


@router.get("/profile")
def profile_page(request: Request, db: Session = Depends(get_db)):
    user_id = request.session.get("user_id")
    if not user_id:
        return RedirectResponse("/auth/login?next=/auth/profile", status_code=303)
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        request.session.clear()
        return RedirectResponse("/auth/login", status_code=303)
    return templates.TemplateResponse("auth/profile.html", template_ctx(request, profile_user=user))


@router.post("/profile")
async def profile_update(request: Request, db: Session = Depends(get_db)):
    user_id = request.session.get("user_id")
    if not user_id:
        return RedirectResponse("/auth/login", status_code=303)
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        request.session.clear()
        return RedirectResponse("/auth/login", status_code=303)

    form = await request.form()
    full_name = form.get("full_name", "").strip()
    college = form.get("college", "").strip()
    discipline = form.get("discipline", "").strip()
    domain = form.get("domain", "").strip()
    year_raw = form.get("year_of_study", "")

    if not full_name:
        flash(request, "Full name is required.", "danger")
        return RedirectResponse("/auth/profile", status_code=303)

    year_of_study = None
    if year_raw:
        try:
            year_of_study = int(year_raw)
        except ValueError:
            pass

    user.full_name = full_name
    user.college = college or None
    user.discipline = discipline or None
    user.domain = domain or None
    user.year_of_study = year_of_study
    log_activity(db, category="auth", action="profile_update", description=f"{user.username} updated their profile", request=request, user_id=user.id, target_type="user", target_id=user.id)
    db.commit()

    flash(request, "Profile updated.", "success")
    return RedirectResponse("/auth/profile", status_code=303)


@router.get("/speaker-invite/{token}")
def speaker_invite_accept(request: Request, token: str, db: Session = Depends(get_db)):
    speaker = db.query(Speaker).filter(Speaker.invite_token == token).first()
    if not speaker:
        flash(request, "Invalid or already-used invite link.", "danger")
        return RedirectResponse("/", status_code=303)
    if speaker.invite_token_expires and speaker.invite_token_expires < now_ist():
        flash(request, "This invite link has expired. Ask the admin to resend.", "danger")
        return RedirectResponse("/", status_code=303)
    if speaker.user_id:
        flash(request, "This speaker account is already linked.", "info")
        return RedirectResponse("/speaker/", status_code=303)

    user_id = request.session.get("user_id")
    if user_id:
        user = db.query(User).filter(User.id == user_id).first()
        if user:
            existing = db.query(Speaker).filter(Speaker.user_id == user.id).first()
            if existing:
                flash(request, f"Your account is already linked to speaker: {existing.name}", "warning")
                return RedirectResponse("/speaker/", status_code=303)
            speaker.user_id = user.id
            speaker.invite_token = None
            speaker.invite_token_expires = None
            log_activity(db, category="auth", action="invite_accepted", description=f"{user.username} accepted speaker invite for '{speaker.name}'", request=request, user_id=user.id, target_type="speaker", target_id=speaker.id)
            db.commit()
            flash(request, f"Welcome, {speaker.name}! Your speaker account is now active.", "success")
            return RedirectResponse("/speaker/", status_code=303)

    request.session["pending_speaker_token"] = token
    request.session["speaker_invite_next"] = "/speaker/"
    flash(request, "Please log in or create an account to accept the speaker invite.", "info")
    return RedirectResponse(f"/auth/login?next=/speaker/", status_code=303)


@router.get("/logout")
def logout(request: Request, db: Session = Depends(get_db)):
    user_id = request.session.get("user_id")
    if user_id:
        log_activity(db, category="auth", action="logout", description="User logged out", request=request, user_id=user_id, target_type="user", target_id=user_id)
        db.commit()
    request.session.clear()
    flash(request, "You have been logged out.", "info")
    return RedirectResponse("/", status_code=303)
