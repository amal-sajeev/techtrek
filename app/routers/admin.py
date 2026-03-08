import json
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.dependencies import flash, get_db, template_ctx, templates
from app.models.auditorium import Auditorium
from app.models.booking import Booking
from app.models.seat import Seat
from app.models.session import LectureSession
from app.models.user import User
from app.models.waitlist import Waitlist
from app.config import settings

router = APIRouter(prefix="/admin", tags=["admin"])


def _require_admin(request: Request, db: Session) -> User | None:
    user_id = request.session.get("user_id")
    if not user_id:
        return None
    user = db.query(User).filter(User.id == user_id).first()
    if not user or not user.is_admin:
        return None
    return user


def _admin_ctx(request: Request, active_page: str = "", **kwargs):
    ctx = template_ctx(request, active_page=active_page)
    ctx.update(kwargs)
    return ctx


async def _form(request: Request):
    return await request.form()


# ─── Dashboard ───

@router.get("/")
def dashboard(request: Request, db: Session = Depends(get_db)):
    admin = _require_admin(request, db)
    if not admin:
        return RedirectResponse("/auth/login?next=/admin/", status_code=303)

    total_users = db.query(func.count(User.id)).scalar()
    total_bookings = db.query(func.count(Booking.id)).filter(Booking.payment_status == "paid").scalar()
    total_revenue = db.query(func.sum(LectureSession.price)).join(
        Booking, Booking.session_id == LectureSession.id
    ).filter(Booking.payment_status == "paid").scalar() or 0

    now = datetime.now(timezone.utc)
    upcoming_count = db.query(func.count(LectureSession.id)).filter(
        LectureSession.status == "published", LectureSession.start_time > now
    ).scalar()

    recent_bookings = (
        db.query(Booking)
        .filter(Booking.payment_status == "paid")
        .order_by(Booking.booked_at.desc())
        .limit(10)
        .all()
    )
    enriched_bookings = []
    for b in recent_bookings:
        u = db.query(User).get(b.user_id)
        s = db.query(LectureSession).get(b.session_id)
        seat = db.query(Seat).get(b.seat_id)
        enriched_bookings.append({"booking": b, "user": u, "session": s, "seat": seat})

    return templates.TemplateResponse(
        "admin/dashboard.html",
        _admin_ctx(
            request,
            active_page="dashboard",
            total_users=total_users,
            total_bookings=total_bookings,
            total_revenue=float(total_revenue),
            upcoming_count=upcoming_count,
            recent_bookings=enriched_bookings,
        ),
    )


# ─── Auditoriums ───

@router.get("/auditoriums")
def auditoriums_list(request: Request, db: Session = Depends(get_db)):
    admin = _require_admin(request, db)
    if not admin:
        return RedirectResponse("/auth/login", status_code=303)
    auditoriums = db.query(Auditorium).order_by(Auditorium.name).all()
    return templates.TemplateResponse(
        "admin/auditoriums.html",
        _admin_ctx(request, active_page="auditoriums", auditoriums=auditoriums),
    )


@router.get("/auditoriums/new")
def auditorium_new(request: Request, db: Session = Depends(get_db)):
    admin = _require_admin(request, db)
    if not admin:
        return RedirectResponse("/auth/login", status_code=303)
    return templates.TemplateResponse(
        "admin/auditorium_form.html",
        _admin_ctx(request, active_page="auditoriums", auditorium=None),
    )


@router.post("/auditoriums/new")
async def auditorium_create(request: Request, db: Session = Depends(get_db)):
    admin = _require_admin(request, db)
    if not admin:
        return RedirectResponse("/auth/login", status_code=303)

    form = await _form(request)
    aud = Auditorium(
        name=form.get("name", "").strip(),
        location=form.get("location", "").strip(),
        description=form.get("description", "").strip(),
        total_rows=int(form.get("total_rows", 10)),
        total_cols=int(form.get("total_cols", 15)),
    )
    db.add(aud)
    db.commit()
    db.refresh(aud)
    flash(request, f"Auditorium '{aud.name}' created.", "success")
    return RedirectResponse(f"/admin/auditoriums/{aud.id}/layout", status_code=303)


@router.get("/auditoriums/{aud_id}/edit")
def auditorium_edit(request: Request, aud_id: int, db: Session = Depends(get_db)):
    admin = _require_admin(request, db)
    if not admin:
        return RedirectResponse("/auth/login", status_code=303)
    aud = db.query(Auditorium).get(aud_id)
    if not aud:
        flash(request, "Auditorium not found.", "danger")
        return RedirectResponse("/admin/auditoriums", status_code=303)
    return templates.TemplateResponse(
        "admin/auditorium_form.html",
        _admin_ctx(request, active_page="auditoriums", auditorium=aud),
    )


@router.post("/auditoriums/{aud_id}/edit")
async def auditorium_update(request: Request, aud_id: int, db: Session = Depends(get_db)):
    admin = _require_admin(request, db)
    if not admin:
        return RedirectResponse("/auth/login", status_code=303)

    aud = db.query(Auditorium).get(aud_id)
    if not aud:
        flash(request, "Auditorium not found.", "danger")
        return RedirectResponse("/admin/auditoriums", status_code=303)

    form = await _form(request)
    aud.name = form.get("name", aud.name).strip()
    aud.location = form.get("location", aud.location).strip()
    aud.description = form.get("description", "").strip()
    aud.total_rows = int(form.get("total_rows", aud.total_rows))
    aud.total_cols = int(form.get("total_cols", aud.total_cols))
    db.commit()
    flash(request, f"Auditorium '{aud.name}' updated.", "success")
    return RedirectResponse("/admin/auditoriums", status_code=303)


@router.post("/auditoriums/{aud_id}/delete")
def auditorium_delete(request: Request, aud_id: int, db: Session = Depends(get_db)):
    admin = _require_admin(request, db)
    if not admin:
        return RedirectResponse("/auth/login", status_code=303)
    aud = db.query(Auditorium).get(aud_id)
    if aud:
        db.delete(aud)
        db.commit()
        flash(request, f"Auditorium '{aud.name}' deleted.", "success")
    return RedirectResponse("/admin/auditoriums", status_code=303)


# ─── Seat Layout Designer ───

@router.get("/auditoriums/{aud_id}/layout")
def seat_layout(request: Request, aud_id: int, db: Session = Depends(get_db)):
    admin = _require_admin(request, db)
    if not admin:
        return RedirectResponse("/auth/login", status_code=303)
    aud = db.query(Auditorium).get(aud_id)
    if not aud:
        flash(request, "Auditorium not found.", "danger")
        return RedirectResponse("/admin/auditoriums", status_code=303)

    seats = db.query(Seat).filter(Seat.auditorium_id == aud_id).order_by(Seat.row_num, Seat.col_num).all()
    seat_data = [
        {"id": s.id, "row": s.row_num, "col": s.col_num, "label": s.label,
         "type": s.seat_type, "active": s.is_active}
        for s in seats
    ]

    return templates.TemplateResponse(
        "admin/seat_layout.html",
        _admin_ctx(
            request,
            active_page="auditoriums",
            auditorium=aud,
            seat_data_json=json.dumps(seat_data),
        ),
    )


@router.post("/auditoriums/{aud_id}/layout")
async def seat_layout_save(request: Request, aud_id: int, db: Session = Depends(get_db)):
    admin = _require_admin(request, db)
    if not admin:
        return RedirectResponse("/auth/login", status_code=303)
    aud = db.query(Auditorium).get(aud_id)
    if not aud:
        return RedirectResponse("/admin/auditoriums", status_code=303)

    form = await _form(request)
    layout_json = form.get("layout_data", "[]")
    total_rows = form.get("total_rows")
    total_cols = form.get("total_cols")
    stage_cols_raw = form.get("stage_cols")
    try:
        layout = json.loads(layout_json)
    except json.JSONDecodeError:
        flash(request, "Invalid layout data.", "danger")
        return RedirectResponse(f"/admin/auditoriums/{aud_id}/layout", status_code=303)

    if total_rows is not None and total_cols is not None:
        try:
            r, c = int(total_rows), int(total_cols)
            if 1 <= r <= 50 and 1 <= c <= 50:
                aud.total_rows = r
                aud.total_cols = c
        except ValueError:
            pass

    if stage_cols_raw is not None:
        try:
            sc = int(stage_cols_raw)
            if 1 <= sc <= aud.total_cols:
                aud.stage_cols = sc
            else:
                aud.stage_cols = aud.total_cols
        except ValueError:
            aud.stage_cols = None
    else:
        aud.stage_cols = None

    row_gaps_raw = form.get("row_gaps", "[]")
    col_gaps_raw = form.get("col_gaps", "[]")
    try:
        rg = json.loads(row_gaps_raw)
        aud.row_gaps = json.dumps([int(x) for x in rg if 1 <= int(x) < aud.total_rows]) if rg else None
    except (json.JSONDecodeError, ValueError):
        aud.row_gaps = None
    try:
        cg = json.loads(col_gaps_raw)
        aud.col_gaps = json.dumps([int(x) for x in cg if 1 <= int(x) < aud.total_cols]) if cg else None
    except (json.JSONDecodeError, ValueError):
        aud.col_gaps = None

    db.query(Seat).filter(Seat.auditorium_id == aud_id).delete()

    for item in layout:
        seat = Seat(
            auditorium_id=aud_id,
            row_num=item["row"],
            col_num=item["col"],
            label=item.get("label", f"{chr(64 + item['row'])}{item['col']}"),
            seat_type=item.get("type", "standard"),
            is_active=item.get("active", True),
        )
        db.add(seat)

    aud.layout_config = layout
    db.commit()
    flash(request, "Seat layout saved.", "success")
    return RedirectResponse(f"/admin/auditoriums/{aud_id}/layout", status_code=303)


# ─── Sessions ───

@router.get("/sessions")
def sessions_list(request: Request, db: Session = Depends(get_db)):
    admin = _require_admin(request, db)
    if not admin:
        return RedirectResponse("/auth/login", status_code=303)
    sessions = db.query(LectureSession).order_by(LectureSession.start_time.desc()).all()
    enriched = []
    for s in sessions:
        aud = db.query(Auditorium).get(s.auditorium_id)
        booking_count = db.query(func.count(Booking.id)).filter(
            Booking.session_id == s.id, Booking.payment_status == "paid"
        ).scalar()
        enriched.append({"session": s, "auditorium": aud, "bookings": booking_count})
    return templates.TemplateResponse(
        "admin/sessions.html",
        _admin_ctx(request, active_page="sessions", sessions=enriched),
    )


@router.get("/sessions/new")
def session_new(request: Request, db: Session = Depends(get_db)):
    admin = _require_admin(request, db)
    if not admin:
        return RedirectResponse("/auth/login", status_code=303)
    auditoriums = db.query(Auditorium).order_by(Auditorium.name).all()
    return templates.TemplateResponse(
        "admin/session_form.html",
        _admin_ctx(request, active_page="sessions", lecture=None, auditoriums=auditoriums),
    )


@router.post("/sessions/new")
async def session_create(request: Request, db: Session = Depends(get_db)):
    admin = _require_admin(request, db)
    if not admin:
        return RedirectResponse("/auth/login", status_code=303)

    form = await _form(request)
    start_str = form.get("start_time", "")
    try:
        start_time = datetime.fromisoformat(start_str)
    except ValueError:
        flash(request, "Invalid date/time.", "danger")
        return RedirectResponse("/admin/sessions/new", status_code=303)

    session = LectureSession(
        auditorium_id=int(form.get("auditorium_id")),
        title=form.get("title", "").strip(),
        speaker=form.get("speaker", "").strip(),
        description=form.get("description", "").strip(),
        start_time=start_time,
        duration_minutes=int(form.get("duration_minutes", 30)),
        price=float(form.get("price", 0)),
        status=form.get("status", "draft"),
    )
    db.add(session)
    db.commit()
    flash(request, f"Session '{session.title}' created.", "success")
    return RedirectResponse("/admin/sessions", status_code=303)


@router.get("/sessions/{sess_id}/edit")
def session_edit(request: Request, sess_id: int, db: Session = Depends(get_db)):
    admin = _require_admin(request, db)
    if not admin:
        return RedirectResponse("/auth/login", status_code=303)
    lecture = db.query(LectureSession).get(sess_id)
    if not lecture:
        flash(request, "Session not found.", "danger")
        return RedirectResponse("/admin/sessions", status_code=303)
    auditoriums = db.query(Auditorium).order_by(Auditorium.name).all()
    return templates.TemplateResponse(
        "admin/session_form.html",
        _admin_ctx(request, active_page="sessions", lecture=lecture, auditoriums=auditoriums),
    )


@router.post("/sessions/{sess_id}/edit")
async def session_update(request: Request, sess_id: int, db: Session = Depends(get_db)):
    admin = _require_admin(request, db)
    if not admin:
        return RedirectResponse("/auth/login", status_code=303)

    lecture = db.query(LectureSession).get(sess_id)
    if not lecture:
        return RedirectResponse("/admin/sessions", status_code=303)

    form = await _form(request)
    start_str = form.get("start_time", "")
    try:
        start_time = datetime.fromisoformat(start_str)
    except ValueError:
        flash(request, "Invalid date/time.", "danger")
        return RedirectResponse(f"/admin/sessions/{sess_id}/edit", status_code=303)

    lecture.auditorium_id = int(form.get("auditorium_id", lecture.auditorium_id))
    lecture.title = form.get("title", lecture.title).strip()
    lecture.speaker = form.get("speaker", lecture.speaker).strip()
    lecture.description = form.get("description", "").strip()
    lecture.start_time = start_time
    lecture.duration_minutes = int(form.get("duration_minutes", 30))
    lecture.price = float(form.get("price", 0))
    lecture.status = form.get("status", lecture.status)
    db.commit()
    flash(request, f"Session '{lecture.title}' updated.", "success")
    return RedirectResponse("/admin/sessions", status_code=303)


@router.post("/sessions/{sess_id}/delete")
def session_delete(request: Request, sess_id: int, db: Session = Depends(get_db)):
    admin = _require_admin(request, db)
    if not admin:
        return RedirectResponse("/auth/login", status_code=303)
    lecture = db.query(LectureSession).get(sess_id)
    if lecture:
        db.delete(lecture)
        db.commit()
        flash(request, f"Session '{lecture.title}' deleted.", "success")
    return RedirectResponse("/admin/sessions", status_code=303)


# ─── Bookings ───

@router.get("/bookings")
def bookings_list(request: Request, db: Session = Depends(get_db)):
    admin = _require_admin(request, db)
    if not admin:
        return RedirectResponse("/auth/login", status_code=303)

    bookings = (
        db.query(Booking)
        .filter(Booking.payment_status.in_(["paid", "hold"]))
        .order_by(Booking.booked_at.desc())
        .all()
    )
    enriched = []
    for b in bookings:
        u = db.query(User).get(b.user_id)
        s = db.query(LectureSession).get(b.session_id)
        seat = db.query(Seat).get(b.seat_id)
        enriched.append({"booking": b, "user": u, "session": s, "seat": seat})

    return templates.TemplateResponse(
        "admin/bookings.html",
        _admin_ctx(request, active_page="bookings", bookings=enriched),
    )


@router.post("/bookings/{booking_id}/cancel")
def booking_cancel(request: Request, booking_id: int, db: Session = Depends(get_db)):
    admin = _require_admin(request, db)
    if not admin:
        return RedirectResponse("/auth/login", status_code=303)
    b = db.query(Booking).get(booking_id)
    if b:
        b.payment_status = "cancelled"
        db.commit()
        flash(request, f"Booking {b.booking_ref} cancelled.", "success")
    return RedirectResponse("/admin/bookings", status_code=303)


@router.post("/bookings/{booking_id}/refund")
def booking_refund(request: Request, booking_id: int, db: Session = Depends(get_db)):
    admin = _require_admin(request, db)
    if not admin:
        return RedirectResponse("/auth/login", status_code=303)
    b = db.query(Booking).get(booking_id)
    if b:
        b.payment_status = "refunded"
        db.commit()
        flash(request, f"Booking {b.booking_ref} refunded.", "success")
    return RedirectResponse("/admin/bookings", status_code=303)


# ─── Waitlist ───

@router.get("/waitlist")
def waitlist_list(request: Request, db: Session = Depends(get_db)):
    admin = _require_admin(request, db)
    if not admin:
        return RedirectResponse("/auth/login", status_code=303)

    entries = db.query(Waitlist).order_by(Waitlist.joined_at.desc()).all()
    enriched = []
    for w in entries:
        u = db.query(User).get(w.user_id)
        s = db.query(LectureSession).get(w.session_id)
        ps = db.query(LectureSession).get(w.priority_session_id) if w.priority_session_id else None
        enriched.append({"entry": w, "user": u, "session": s, "priority_session": ps})

    sessions_for_priority = (
        db.query(LectureSession)
        .filter(LectureSession.status == "published")
        .order_by(LectureSession.start_time)
        .all()
    )

    return templates.TemplateResponse(
        "admin/waitlist.html",
        _admin_ctx(
            request,
            active_page="waitlist",
            entries=enriched,
            sessions_for_priority=sessions_for_priority,
        ),
    )


@router.post("/waitlist/grant-priority")
async def grant_priority(request: Request, db: Session = Depends(get_db)):
    admin = _require_admin(request, db)
    if not admin:
        return RedirectResponse("/auth/login", status_code=303)

    form = await _form(request)
    source_session_id = int(form.get("source_session_id", 0))
    target_session_id = int(form.get("target_session_id", 0))

    if not source_session_id or not target_session_id:
        flash(request, "Please select both source and target sessions.", "danger")
        return RedirectResponse("/admin/waitlist", status_code=303)

    entries = db.query(Waitlist).filter(Waitlist.session_id == source_session_id).all()
    now = datetime.now(timezone.utc)
    expires = now + timedelta(hours=settings.priority_window_hours)

    for e in entries:
        e.priority_session_id = target_session_id
        e.priority_expires_at = expires
        e.notified = True

    db.commit()
    flash(request, f"Priority granted to {len(entries)} waitlisted user(s).", "success")
    return RedirectResponse("/admin/waitlist", status_code=303)


# ─── Users ───

@router.get("/users")
def users_list(request: Request, db: Session = Depends(get_db)):
    admin = _require_admin(request, db)
    if not admin:
        return RedirectResponse("/auth/login", status_code=303)
    users = db.query(User).order_by(User.created_at.desc()).all()
    return templates.TemplateResponse(
        "admin/users.html",
        _admin_ctx(request, active_page="users", users=users),
    )


@router.post("/users/{user_id}/toggle-admin")
def toggle_admin(request: Request, user_id: int, db: Session = Depends(get_db)):
    admin = _require_admin(request, db)
    if not admin:
        return RedirectResponse("/auth/login", status_code=303)
    u = db.query(User).get(user_id)
    if u and u.id != admin.id:
        u.is_admin = not u.is_admin
        db.commit()
        status = "admin" if u.is_admin else "regular user"
        flash(request, f"{u.username} is now a {status}.", "success")
    return RedirectResponse("/admin/users", status_code=303)
