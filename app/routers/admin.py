import csv
import io
import json
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import RedirectResponse, StreamingResponse
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.dependencies import flash, get_db, now_ist, template_ctx, templates
from app.services.activity_log import log_activity
from app.models.activity_log import ActivityLog
from app.models.auditorium import Auditorium
from app.services.invoice import generate_invoice_pdf
from app.models.booking import Booking
from app.models.city import City
from app.models.college import College
from app.models.seat import Seat
from app.models.seat_type import SeatType
from app.models.session import LectureSession
from app.models.session_speaker import SessionSpeaker, SPEAKER_ROLES
from app.models.speaker import Speaker
from app.models.agenda import AgendaItem
from app.models.testimonial import Testimonial
from app.models.user import User
from app.services.razorpay import process_refund as rz_process_refund
from app.models.waitlist import Waitlist
from app.config import settings

RECORDINGS_DIR = Path(__file__).resolve().parent.parent / "static" / "recordings"

router = APIRouter(prefix="/admin", tags=["admin"])


def _require_admin(request: Request, db: Session) -> User | None:
    user_id = request.session.get("user_id")
    if not user_id:
        return None
    user = db.query(User).filter(User.id == user_id).first()
    if not user or not user.is_admin:
        return None
    return user


def _require_supervisor_or_admin(request: Request, db: Session) -> User | None:
    user_id = request.session.get("user_id")
    if not user_id:
        return None
    user = db.query(User).filter(User.id == user_id).first()
    if not user or not (user.is_admin or user.is_supervisor):
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
    admin = _require_supervisor_or_admin(request, db)
    if not admin:
        return RedirectResponse("/auth/login?next=/admin/", status_code=303)

    total_users = db.query(func.count(User.id)).scalar()
    total_bookings = db.query(func.count(Booking.id)).filter(Booking.payment_status == "paid").scalar()
    total_revenue = db.query(func.sum(Booking.amount_paid)).filter(Booking.payment_status == "paid").scalar() or 0

    now = now_ist()
    upcoming_count = db.query(func.count(LectureSession.id)).filter(
        LectureSession.status == "published", LectureSession.start_time > now
    ).scalar()

    total_checked_in = db.query(func.count(Booking.id)).filter(Booking.checked_in == True).scalar()
    total_refunded = db.query(func.count(Booking.id)).filter(Booking.payment_status == "refunded").scalar()

    # Event status breakdown
    status_counts = (
        db.query(LectureSession.status, func.count(LectureSession.id))
        .group_by(LectureSession.status)
        .all()
    )
    event_statuses = {s: c for s, c in status_counts}

    # Top cities by registrations
    top_cities = []
    city_rows = (
        db.query(City.name, func.count(Booking.id))
        .select_from(Booking)
        .join(LectureSession, Booking.session_id == LectureSession.id)
        .join(Auditorium, LectureSession.auditorium_id == Auditorium.id)
        .join(College, Auditorium.college_id == College.id)
        .join(City, College.city_id == City.id)
        .filter(Booking.payment_status == "paid")
        .group_by(City.name)
        .order_by(func.count(Booking.id).desc())
        .limit(5)
        .all()
    )
    for city_name, count in city_rows:
        top_cities.append({"name": city_name, "count": count})

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
            total_checked_in=total_checked_in,
            total_refunded=total_refunded,
            event_statuses=event_statuses,
            top_cities=top_cities,
            recent_bookings=enriched_bookings,
        ),
    )


# ─── Cities ───

@router.get("/cities")
def cities_list(request: Request, db: Session = Depends(get_db)):
    admin = _require_admin(request, db)
    if not admin:
        return RedirectResponse("/auth/login", status_code=303)
    cities = db.query(City).order_by(City.name).all()
    return templates.TemplateResponse(
        "admin/cities.html",
        _admin_ctx(request, active_page="cities", cities=cities),
    )


@router.get("/cities/new")
def city_new(request: Request, db: Session = Depends(get_db)):
    admin = _require_admin(request, db)
    if not admin:
        return RedirectResponse("/auth/login", status_code=303)
    return templates.TemplateResponse(
        "admin/city_form.html",
        _admin_ctx(request, active_page="cities", city=None),
    )


@router.post("/cities/new")
async def city_create(request: Request, db: Session = Depends(get_db)):
    admin = _require_admin(request, db)
    if not admin:
        return RedirectResponse("/auth/login", status_code=303)
    form = await _form(request)
    city = City(
        name=form.get("name", "").strip(),
        state=form.get("state", "").strip(),
        is_active="is_active" in form,
    )
    db.add(city)
    db.flush()
    log_activity(db, category="admin", action="create", description=f"Created city '{city.name}'", request=request, user_id=admin.id, target_type="city", target_id=city.id)
    db.commit()
    flash(request, f"City '{city.name}' created.", "success")
    return RedirectResponse("/admin/cities", status_code=303)


@router.get("/cities/{city_id}/edit")
def city_edit(request: Request, city_id: int, db: Session = Depends(get_db)):
    admin = _require_admin(request, db)
    if not admin:
        return RedirectResponse("/auth/login", status_code=303)
    city = db.query(City).get(city_id)
    if not city:
        flash(request, "City not found.", "danger")
        return RedirectResponse("/admin/cities", status_code=303)
    return templates.TemplateResponse(
        "admin/city_form.html",
        _admin_ctx(request, active_page="cities", city=city),
    )


@router.post("/cities/{city_id}/edit")
async def city_update(request: Request, city_id: int, db: Session = Depends(get_db)):
    admin = _require_admin(request, db)
    if not admin:
        return RedirectResponse("/auth/login", status_code=303)
    city = db.query(City).get(city_id)
    if not city:
        return RedirectResponse("/admin/cities", status_code=303)
    form = await _form(request)
    city.name = form.get("name", city.name).strip()
    city.state = form.get("state", city.state).strip()
    city.is_active = "is_active" in form
    log_activity(db, category="admin", action="update", description=f"Updated city '{city.name}'", request=request, user_id=admin.id, target_type="city", target_id=city.id)
    db.commit()
    flash(request, f"City '{city.name}' updated.", "success")
    return RedirectResponse("/admin/cities", status_code=303)


@router.post("/cities/{city_id}/delete")
def city_delete(request: Request, city_id: int, db: Session = Depends(get_db)):
    admin = _require_admin(request, db)
    if not admin:
        return RedirectResponse("/auth/login", status_code=303)
    city = db.query(City).get(city_id)
    if city:
        log_activity(db, category="admin", action="delete", description=f"Deleted city '{city.name}'", request=request, user_id=admin.id, target_type="city", target_id=city_id)
        db.delete(city)
        db.commit()
        flash(request, f"City '{city.name}' deleted.", "success")
    return RedirectResponse("/admin/cities", status_code=303)


@router.post("/cities/{city_id}/toggle")
def city_toggle(request: Request, city_id: int, db: Session = Depends(get_db)):
    admin = _require_admin(request, db)
    if not admin:
        return RedirectResponse("/auth/login", status_code=303)
    city = db.query(City).get(city_id)
    if city:
        city.is_active = not city.is_active
        status = "active" if city.is_active else "inactive"
        log_activity(db, category="admin", action="update", description=f"Toggled city '{city.name}' to {status}", request=request, user_id=admin.id, target_type="city", target_id=city_id)
        db.commit()
        flash(request, f"City '{city.name}' is now {status}.", "success")
    return RedirectResponse("/admin/cities", status_code=303)


# ─── Colleges ───

@router.get("/colleges")
def colleges_list(request: Request, db: Session = Depends(get_db)):
    admin = _require_admin(request, db)
    if not admin:
        return RedirectResponse("/auth/login", status_code=303)
    colleges = db.query(College).order_by(College.name).all()
    enriched = []
    for col in colleges:
        city = db.query(City).get(col.city_id) if col.city_id else None
        enriched.append({"college": col, "city": city})
    return templates.TemplateResponse(
        "admin/colleges.html",
        _admin_ctx(request, active_page="colleges", colleges=enriched),
    )


@router.get("/colleges/new")
def college_new(request: Request, db: Session = Depends(get_db)):
    admin = _require_admin(request, db)
    if not admin:
        return RedirectResponse("/auth/login", status_code=303)
    cities = db.query(City).filter(City.is_active == True).order_by(City.name).all()
    return templates.TemplateResponse(
        "admin/college_form.html",
        _admin_ctx(request, active_page="colleges", college=None, cities=cities),
    )


@router.post("/colleges/new")
async def college_create(request: Request, db: Session = Depends(get_db)):
    admin = _require_admin(request, db)
    if not admin:
        return RedirectResponse("/auth/login", status_code=303)
    form = await _form(request)
    col = College(
        name=form.get("name", "").strip(),
        city_id=int(form.get("city_id")),
        address=form.get("address", "").strip() or None,
        is_active="is_active" in form,
    )
    db.add(col)
    db.flush()
    log_activity(db, category="admin", action="create", description=f"Created college '{col.name}'", request=request, user_id=admin.id, target_type="college", target_id=col.id)
    db.commit()
    flash(request, f"College '{col.name}' created.", "success")
    return RedirectResponse("/admin/colleges", status_code=303)


@router.get("/colleges/{college_id}/edit")
def college_edit(request: Request, college_id: int, db: Session = Depends(get_db)):
    admin = _require_admin(request, db)
    if not admin:
        return RedirectResponse("/auth/login", status_code=303)
    col = db.query(College).get(college_id)
    if not col:
        flash(request, "College not found.", "danger")
        return RedirectResponse("/admin/colleges", status_code=303)
    cities = db.query(City).filter(City.is_active == True).order_by(City.name).all()
    return templates.TemplateResponse(
        "admin/college_form.html",
        _admin_ctx(request, active_page="colleges", college=col, cities=cities),
    )


@router.post("/colleges/{college_id}/edit")
async def college_update(request: Request, college_id: int, db: Session = Depends(get_db)):
    admin = _require_admin(request, db)
    if not admin:
        return RedirectResponse("/auth/login", status_code=303)
    col = db.query(College).get(college_id)
    if not col:
        return RedirectResponse("/admin/colleges", status_code=303)
    form = await _form(request)
    col.name = form.get("name", col.name).strip()
    col.city_id = int(form.get("city_id", col.city_id))
    col.address = form.get("address", "").strip() or None
    col.is_active = "is_active" in form
    log_activity(db, category="admin", action="update", description=f"Updated college '{col.name}'", request=request, user_id=admin.id, target_type="college", target_id=college_id)
    db.commit()
    flash(request, f"College '{col.name}' updated.", "success")
    return RedirectResponse("/admin/colleges", status_code=303)


@router.post("/colleges/{college_id}/delete")
def college_delete(request: Request, college_id: int, db: Session = Depends(get_db)):
    admin = _require_admin(request, db)
    if not admin:
        return RedirectResponse("/auth/login", status_code=303)
    col = db.query(College).get(college_id)
    if col:
        log_activity(db, category="admin", action="delete", description=f"Deleted college '{col.name}'", request=request, user_id=admin.id, target_type="college", target_id=college_id)
        db.delete(col)
        db.commit()
        flash(request, f"College '{col.name}' deleted.", "success")
    return RedirectResponse("/admin/colleges", status_code=303)


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
    colleges = db.query(College).filter(College.is_active == True).order_by(College.name).all()
    return templates.TemplateResponse(
        "admin/auditorium_form.html",
        _admin_ctx(request, active_page="auditoriums", auditorium=None, colleges=colleges),
    )


@router.post("/auditoriums/new")
async def auditorium_create(request: Request, db: Session = Depends(get_db)):
    admin = _require_admin(request, db)
    if not admin:
        return RedirectResponse("/auth/login", status_code=303)

    form = await _form(request)
    college_id_raw = form.get("college_id")
    aud = Auditorium(
        name=form.get("name", "").strip(),
        college_id=int(college_id_raw) if college_id_raw and college_id_raw != "" else None,
        location=form.get("location", "").strip(),
        description=form.get("description", "").strip(),
        total_rows=int(form.get("total_rows", 10)),
        total_cols=int(form.get("total_cols", 15)),
    )
    db.add(aud)
    db.commit()
    db.refresh(aud)
    log_activity(db, category="admin", action="create", description=f"Created auditorium '{aud.name}'", request=request, user_id=admin.id, target_type="auditorium", target_id=aud.id)
    db.commit()
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
    colleges = db.query(College).filter(College.is_active == True).order_by(College.name).all()
    return templates.TemplateResponse(
        "admin/auditorium_form.html",
        _admin_ctx(request, active_page="auditoriums", auditorium=aud, colleges=colleges),
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
    college_id_raw = form.get("college_id")
    aud.name = form.get("name", aud.name).strip()
    aud.college_id = int(college_id_raw) if college_id_raw and college_id_raw != "" else None
    aud.location = form.get("location", aud.location).strip()
    aud.description = form.get("description", "").strip()
    aud.total_rows = int(form.get("total_rows", aud.total_rows))
    aud.total_cols = int(form.get("total_cols", aud.total_cols))
    log_activity(db, category="admin", action="update", description=f"Updated auditorium '{aud.name}'", request=request, user_id=admin.id, target_type="auditorium", target_id=aud_id)
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
        log_activity(db, category="admin", action="delete", description=f"Deleted auditorium '{aud.name}'", request=request, user_id=admin.id, target_type="auditorium", target_id=aud_id)
        db.delete(aud)
        db.commit()
        flash(request, f"Auditorium '{aud.name}' deleted.", "success")
    return RedirectResponse("/admin/auditoriums", status_code=303)


# ─── Seat Types ───

@router.get("/seat-types")
def seat_types_list(request: Request, db: Session = Depends(get_db)):
    admin = _require_admin(request, db)
    if not admin:
        return RedirectResponse("/auth/login", status_code=303)
    seat_types = db.query(SeatType).order_by(SeatType.name).all()
    return templates.TemplateResponse(
        "admin/seat_types.html",
        _admin_ctx(request, active_page="seat_types", seat_types=seat_types),
    )


@router.get("/seat-types/new")
def seat_type_new(request: Request, db: Session = Depends(get_db)):
    admin = _require_admin(request, db)
    if not admin:
        return RedirectResponse("/auth/login", status_code=303)
    return templates.TemplateResponse(
        "admin/seat_type_form.html",
        _admin_ctx(request, active_page="seat_types", seat_type=None),
    )


@router.post("/seat-types/new")
async def seat_type_create(request: Request, db: Session = Depends(get_db)):
    admin = _require_admin(request, db)
    if not admin:
        return RedirectResponse("/auth/login", status_code=303)
    form = await _form(request)
    st = SeatType(
        name=form.get("name", "").strip(),
        colour=form.get("colour", "#6366f1").strip(),
        icon=form.get("icon", "").strip() or None,
        is_custom=True,
    )
    db.add(st)
    db.flush()
    log_activity(db, category="admin", action="create", description=f"Created seat type '{st.name}'", request=request, user_id=admin.id, target_type="seat_type", target_id=st.id)
    db.commit()
    flash(request, f"Seat type '{st.name}' created.", "success")
    return RedirectResponse("/admin/seat-types", status_code=303)


@router.get("/seat-types/{st_id}/edit")
def seat_type_edit(request: Request, st_id: int, db: Session = Depends(get_db)):
    admin = _require_admin(request, db)
    if not admin:
        return RedirectResponse("/auth/login", status_code=303)
    st = db.query(SeatType).get(st_id)
    if not st:
        flash(request, "Seat type not found.", "danger")
        return RedirectResponse("/admin/seat-types", status_code=303)
    return templates.TemplateResponse(
        "admin/seat_type_form.html",
        _admin_ctx(request, active_page="seat_types", seat_type=st),
    )


@router.post("/seat-types/{st_id}/edit")
async def seat_type_update(request: Request, st_id: int, db: Session = Depends(get_db)):
    admin = _require_admin(request, db)
    if not admin:
        return RedirectResponse("/auth/login", status_code=303)
    st = db.query(SeatType).get(st_id)
    if not st:
        return RedirectResponse("/admin/seat-types", status_code=303)
    form = await _form(request)
    st.name = form.get("name", st.name).strip()
    st.colour = form.get("colour", st.colour).strip()
    st.icon = form.get("icon", "").strip() or None
    log_activity(db, category="admin", action="update", description=f"Updated seat type '{st.name}'", request=request, user_id=admin.id, target_type="seat_type", target_id=st_id)
    db.commit()
    flash(request, f"Seat type '{st.name}' updated.", "success")
    return RedirectResponse("/admin/seat-types", status_code=303)


@router.post("/seat-types/{st_id}/delete")
def seat_type_delete(request: Request, st_id: int, db: Session = Depends(get_db)):
    admin = _require_admin(request, db)
    if not admin:
        return RedirectResponse("/auth/login", status_code=303)
    st = db.query(SeatType).get(st_id)
    if st:
        in_use = db.query(Seat).filter(Seat.seat_type == f"custom_{st.id}").count()
        if in_use:
            flash(request, f"Cannot delete '{st.name}' — it is used by {in_use} seat(s).", "danger")
            return RedirectResponse("/admin/seat-types", status_code=303)
        log_activity(db, category="admin", action="delete", description=f"Deleted seat type '{st.name}'", request=request, user_id=admin.id, target_type="seat_type", target_id=st_id)
        db.delete(st)
        db.commit()
        flash(request, f"Seat type '{st.name}' deleted.", "success")
    return RedirectResponse("/admin/seat-types", status_code=303)


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

    custom_types = db.query(SeatType).filter(SeatType.is_custom == True).order_by(SeatType.name).all()
    custom_types_data = [
        {"id": st.id, "name": st.name, "colour": st.colour, "icon": st.icon}
        for st in custom_types
    ]

    return templates.TemplateResponse(
        "admin/seat_layout.html",
        _admin_ctx(
            request,
            active_page="auditoriums",
            auditorium=aud,
            seat_data_json=json.dumps(seat_data),
            custom_types_json=json.dumps(custom_types_data),
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

    stage_offset_raw = form.get("stage_offset", "0")
    try:
        aud.stage_offset = max(0, int(stage_offset_raw))
    except (ValueError, TypeError):
        aud.stage_offset = 0

    stage_label_raw = form.get("stage_label", "Stage")
    aud.stage_label = (stage_label_raw or "Stage").strip()[:100]

    entry_exit_raw = form.get("entry_exit_config", "[]")
    try:
        aud.entry_exit_config = json.loads(entry_exit_raw)
    except (json.JSONDecodeError, ValueError):
        aud.entry_exit_config = None

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

    seat_ids = [s.id for s in db.query(Seat.id).filter(Seat.auditorium_id == aud_id).all()]
    if seat_ids:
        db.query(Booking).filter(Booking.seat_id.in_(seat_ids)).delete(synchronize_session="fetch")
        db.query(Seat).filter(Seat.id.in_(seat_ids)).delete(synchronize_session="fetch")

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
    seat_count = sum(1 for item in layout if item.get("type") != "aisle")
    log_activity(db, category="admin", action="update", description=f"Saved seat layout for '{aud.name}' ({seat_count} seats)", request=request, user_id=admin.id, target_type="auditorium", target_id=aud_id)
    db.commit()
    flash(request, "Seat layout saved.", "success")
    return RedirectResponse(f"/admin/auditoriums/{aud_id}/layout", status_code=303)


# ─── Speakers ───

@router.get("/speakers")
def speakers_list(
    request: Request,
    db: Session = Depends(get_db),
    role: str = Query("", alias="role"),
):
    admin = _require_admin(request, db)
    if not admin:
        return RedirectResponse("/auth/login", status_code=303)
    query = db.query(Speaker)
    if role:
        query = query.join(SessionSpeaker).filter(SessionSpeaker.role == role)
    speakers = query.order_by(Speaker.name).all()
    return templates.TemplateResponse(
        "admin/speakers.html",
        _admin_ctx(request, active_page="speakers", speakers=speakers,
                   speaker_roles=SPEAKER_ROLES, role_filter=role),
    )


@router.get("/speakers/new")
def speaker_new(request: Request, db: Session = Depends(get_db)):
    admin = _require_admin(request, db)
    if not admin:
        return RedirectResponse("/auth/login", status_code=303)
    return templates.TemplateResponse(
        "admin/speaker_form.html",
        _admin_ctx(request, active_page="speakers", speaker=None),
    )


@router.post("/speakers/new")
async def speaker_create(request: Request, db: Session = Depends(get_db)):
    admin = _require_admin(request, db)
    if not admin:
        return RedirectResponse("/auth/login", status_code=303)
    form = await _form(request)
    sp = Speaker(
        name=form.get("name", "").strip(),
        title=form.get("title", "").strip() or None,
        bio=form.get("bio", "").strip() or None,
        photo_url=form.get("photo_url", "").strip() or None,
        email=form.get("email", "").strip() or None,
    )
    db.add(sp)
    db.flush()
    log_activity(db, category="admin", action="create", description=f"Created speaker '{sp.name}'", request=request, user_id=admin.id, target_type="speaker", target_id=sp.id)
    db.commit()
    flash(request, f"Speaker '{sp.name}' created.", "success")
    return RedirectResponse("/admin/speakers", status_code=303)


@router.get("/speakers/{speaker_id}/edit")
def speaker_edit(request: Request, speaker_id: int, db: Session = Depends(get_db)):
    admin = _require_admin(request, db)
    if not admin:
        return RedirectResponse("/auth/login", status_code=303)
    sp = db.query(Speaker).get(speaker_id)
    if not sp:
        flash(request, "Speaker not found.", "danger")
        return RedirectResponse("/admin/speakers", status_code=303)
    return templates.TemplateResponse(
        "admin/speaker_form.html",
        _admin_ctx(request, active_page="speakers", speaker=sp),
    )


@router.post("/speakers/{speaker_id}/edit")
async def speaker_update(request: Request, speaker_id: int, db: Session = Depends(get_db)):
    admin = _require_admin(request, db)
    if not admin:
        return RedirectResponse("/auth/login", status_code=303)
    sp = db.query(Speaker).get(speaker_id)
    if not sp:
        return RedirectResponse("/admin/speakers", status_code=303)
    form = await _form(request)
    sp.name = form.get("name", sp.name).strip()
    sp.title = form.get("title", "").strip() or None
    sp.bio = form.get("bio", "").strip() or None
    sp.photo_url = form.get("photo_url", "").strip() or None
    sp.email = form.get("email", "").strip() or None
    log_activity(db, category="admin", action="update", description=f"Updated speaker '{sp.name}'", request=request, user_id=admin.id, target_type="speaker", target_id=speaker_id)
    db.commit()
    flash(request, f"Speaker '{sp.name}' updated.", "success")
    return RedirectResponse("/admin/speakers", status_code=303)


@router.post("/speakers/{speaker_id}/delete")
def speaker_delete(request: Request, speaker_id: int, db: Session = Depends(get_db)):
    admin = _require_admin(request, db)
    if not admin:
        return RedirectResponse("/auth/login", status_code=303)
    sp = db.query(Speaker).get(speaker_id)
    if sp:
        log_activity(db, category="admin", action="delete", description=f"Deleted speaker '{sp.name}'", request=request, user_id=admin.id, target_type="speaker", target_id=speaker_id)
        db.delete(sp)
        db.commit()
        flash(request, f"Speaker '{sp.name}' deleted.", "success")
    return RedirectResponse("/admin/speakers", status_code=303)


@router.post("/speakers/{speaker_id}/invite")
def speaker_invite(request: Request, speaker_id: int, db: Session = Depends(get_db)):
    admin = _require_admin(request, db)
    if not admin:
        return RedirectResponse("/auth/login", status_code=303)
    sp = db.query(Speaker).get(speaker_id)
    if not sp:
        flash(request, "Speaker not found.", "danger")
        return RedirectResponse("/admin/speakers", status_code=303)
    if not sp.email:
        flash(request, "Speaker has no email address. Add an email first.", "danger")
        return RedirectResponse("/admin/speakers", status_code=303)
    if sp.user_id:
        flash(request, f"Speaker '{sp.name}' is already linked to a user account.", "warning")
        return RedirectResponse("/admin/speakers", status_code=303)

    import secrets
    sp.invite_token = secrets.token_hex(32)
    sp.invite_token_expires = now_ist() + timedelta(days=7)
    db.commit()

    base_url = str(request.base_url).rstrip("/")
    invite_url = f"{base_url}/auth/speaker-invite/{sp.invite_token}"

    from app.services.email import send_speaker_invite
    sent = send_speaker_invite(sp.email, sp.name, invite_url)

    if sent:
        log_activity(db, category="admin", action="invite_sent", description=f"Sent speaker invite to '{sp.name}' ({sp.email})", request=request, user_id=admin.id, target_type="speaker", target_id=speaker_id)
        db.commit()
        flash(request, f"Invite sent to {sp.email}.", "success")
    else:
        log_activity(db, category="system", action="email_failed", description=f"Speaker invite email to '{sp.name}' ({sp.email}) failed", request=request, user_id=admin.id, target_type="speaker", target_id=speaker_id)
        db.commit()
        flash(request, f"Invite token created but email to {sp.email} failed. Check SMTP settings or share the link manually: {invite_url}", "warning")
    return RedirectResponse("/admin/speakers", status_code=303)


# ─── Sessions ───

@router.get("/sessions")
def sessions_list(request: Request, db: Session = Depends(get_db)):
    admin = _require_supervisor_or_admin(request, db)
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
    speakers = db.query(Speaker).order_by(Speaker.name).all()
    cities = db.query(City).filter(City.is_active == True).order_by(City.name).all()
    return templates.TemplateResponse(
        "admin/session_form.html",
        _admin_ctx(request, active_page="sessions", lecture=None,
                   auditoriums=auditoriums, speakers=speakers, cities=cities,
                   agenda_items=[], session_speakers=[], speaker_roles=SPEAKER_ROLES),
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

    speaker_id_raw = form.get("speaker_id")
    speaker_id = int(speaker_id_raw) if speaker_id_raw and speaker_id_raw != "" else None

    session_obj = LectureSession(
        auditorium_id=int(form.get("auditorium_id")),
        speaker_id=speaker_id,
        title=form.get("title", "").strip(),
        speaker=form.get("speaker", "").strip(),
        description=form.get("description", "").strip(),
        banner_url=form.get("banner_url", "").strip() or None,
        start_time=start_time,
        duration_minutes=int(form.get("duration_minutes", 30)),
        price=float(form.get("price", 0)),
        price_vip=float(form["price_vip"]) if form.get("price_vip", "").strip() else None,
        price_accessible=float(form["price_accessible"]) if form.get("price_accessible", "").strip() else None,
        status=form.get("status", "draft"),
        cert_title=form.get("cert_title", "").strip() or None,
        cert_subtitle=form.get("cert_subtitle", "").strip() or None,
        cert_footer=form.get("cert_footer", "").strip() or None,
        cert_signer_name=form.get("cert_signer_name", "").strip() or None,
        cert_signer_designation=form.get("cert_signer_designation", "").strip() or None,
        cert_logo_url=form.get("cert_logo_url", "").strip() or None,
        cert_bg_url=form.get("cert_bg_url", "").strip() or None,
        cert_color_scheme=form.get("cert_color_scheme", "").strip() or None,
        recording_url=form.get("recording_url", "").strip() or None,
        is_recording_public="is_recording_public" in form,
    )
    db.add(session_obj)
    db.commit()
    db.refresh(session_obj)

    _save_agenda_items(db, form, session_obj.id)
    _save_session_speakers(db, form, session_obj.id)

    log_activity(db, category="admin", action="create", description=f"Created session '{session_obj.title}'", request=request, user_id=admin.id, target_type="session", target_id=session_obj.id)
    db.commit()
    flash(request, f"Session '{session_obj.title}' created.", "success")
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
    speakers = db.query(Speaker).order_by(Speaker.name).all()
    cities = db.query(City).filter(City.is_active == True).order_by(City.name).all()
    agenda_items = db.query(AgendaItem).filter(AgendaItem.session_id == sess_id).order_by(AgendaItem.order).all()
    session_speakers = db.query(SessionSpeaker).filter(SessionSpeaker.session_id == sess_id).all()
    return templates.TemplateResponse(
        "admin/session_form.html",
        _admin_ctx(request, active_page="sessions", lecture=lecture,
                   auditoriums=auditoriums, speakers=speakers, cities=cities,
                   agenda_items=agenda_items, session_speakers=session_speakers,
                   speaker_roles=SPEAKER_ROLES),
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

    speaker_id_raw = form.get("speaker_id")
    lecture.speaker_id = int(speaker_id_raw) if speaker_id_raw and speaker_id_raw != "" else None
    lecture.auditorium_id = int(form.get("auditorium_id", lecture.auditorium_id))
    lecture.title = form.get("title", lecture.title).strip()
    lecture.speaker = form.get("speaker", lecture.speaker).strip()
    lecture.description = form.get("description", "").strip()
    lecture.banner_url = form.get("banner_url", "").strip() or None
    lecture.start_time = start_time
    lecture.duration_minutes = int(form.get("duration_minutes", 30))
    lecture.price = float(form.get("price", 0))
    lecture.price_vip = float(form["price_vip"]) if form.get("price_vip", "").strip() else None
    lecture.price_accessible = float(form["price_accessible"]) if form.get("price_accessible", "").strip() else None
    lecture.status = form.get("status", lecture.status)
    lecture.cert_title = form.get("cert_title", "").strip() or None
    lecture.cert_subtitle = form.get("cert_subtitle", "").strip() or None
    lecture.cert_footer = form.get("cert_footer", "").strip() or None
    lecture.cert_signer_name = form.get("cert_signer_name", "").strip() or None
    lecture.cert_signer_designation = form.get("cert_signer_designation", "").strip() or None
    lecture.cert_logo_url = form.get("cert_logo_url", "").strip() or None
    lecture.cert_bg_url = form.get("cert_bg_url", "").strip() or None
    lecture.cert_color_scheme = form.get("cert_color_scheme", "").strip() or None
    lecture.recording_url = form.get("recording_url", "").strip() or None
    lecture.is_recording_public = "is_recording_public" in form

    _save_agenda_items(db, form, sess_id)
    _save_session_speakers(db, form, sess_id)

    log_activity(db, category="admin", action="update", description=f"Updated session '{lecture.title}'", request=request, user_id=admin.id, target_type="session", target_id=sess_id)
    db.commit()
    flash(request, f"Session '{lecture.title}' updated.", "success")
    return RedirectResponse("/admin/sessions", status_code=303)


def _save_agenda_items(db: Session, form, session_id: int):
    db.query(AgendaItem).filter(AgendaItem.session_id == session_id).delete()
    idx = 0
    while True:
        title = form.get(f"agenda_title_{idx}")
        if title is None:
            break
        title = title.strip()
        if title:
            item = AgendaItem(
                session_id=session_id,
                order=idx,
                title=title,
                speaker_name=form.get(f"agenda_speaker_{idx}", "").strip() or None,
                duration_minutes=int(form.get(f"agenda_duration_{idx}", 20) or 20),
                description=form.get(f"agenda_desc_{idx}", "").strip() or None,
            )
            db.add(item)
        idx += 1
    db.commit()


def _save_session_speakers(db: Session, form, session_id: int):
    db.query(SessionSpeaker).filter(SessionSpeaker.session_id == session_id).delete()
    idx = 0
    while True:
        sp_id_raw = form.get(f"session_speaker_id_{idx}")
        if sp_id_raw is None:
            break
        sp_id_raw = sp_id_raw.strip()
        if sp_id_raw:
            role = form.get(f"session_speaker_role_{idx}", "Guest").strip()
            if role not in SPEAKER_ROLES:
                role = "Guest"
            ss = SessionSpeaker(
                session_id=session_id,
                speaker_id=int(sp_id_raw),
                role=role,
            )
            db.add(ss)
        idx += 1
    db.flush()


@router.post("/sessions/{sess_id}/recording-upload")
async def session_recording_upload(request: Request, sess_id: int, db: Session = Depends(get_db)):
    admin = _require_admin(request, db)
    if not admin:
        return RedirectResponse("/auth/login", status_code=303)
    lecture = db.query(LectureSession).get(sess_id)
    if not lecture:
        flash(request, "Session not found.", "danger")
        return RedirectResponse("/admin/sessions", status_code=303)

    form = await request.form()
    upload = form.get("recording_file")
    if upload and hasattr(upload, "filename") and upload.filename:
        RECORDINGS_DIR.mkdir(parents=True, exist_ok=True)
        safe_name = f"session_{sess_id}_{upload.filename.replace(' ', '_')}"
        dest = RECORDINGS_DIR / safe_name
        with open(dest, "wb") as f:
            content = await upload.read()
            f.write(content)
        lecture.recording_file = f"/static/recordings/{safe_name}"
        log_activity(db, category="admin", action="upload", description=f"Uploaded recording for '{lecture.title}'", request=request, user_id=admin.id, target_type="session", target_id=sess_id)
        db.commit()
        flash(request, "Recording file uploaded.", "success")
    else:
        flash(request, "No file selected.", "warning")
    return RedirectResponse(f"/admin/sessions/{sess_id}/edit", status_code=303)


@router.post("/sessions/{sess_id}/delete")
def session_delete(request: Request, sess_id: int, db: Session = Depends(get_db)):
    admin = _require_admin(request, db)
    if not admin:
        return RedirectResponse("/auth/login", status_code=303)
    lecture = db.query(LectureSession).get(sess_id)
    if lecture:
        log_activity(db, category="admin", action="delete", description=f"Deleted session '{lecture.title}'", request=request, user_id=admin.id, target_type="session", target_id=sess_id)
        db.delete(lecture)
        db.commit()
        flash(request, f"Session '{lecture.title}' deleted.", "success")
    return RedirectResponse("/admin/sessions", status_code=303)


# ─── Bookings ───

@router.get("/bookings")
def bookings_list(
    request: Request,
    db: Session = Depends(get_db),
    q: str = Query("", alias="q"),
    status_filter: str = Query("", alias="status"),
    session_filter: str = Query("", alias="session_id"),
):
    admin = _require_supervisor_or_admin(request, db)
    if not admin:
        return RedirectResponse("/auth/login", status_code=303)

    query = db.query(Booking)
    if status_filter:
        query = query.filter(Booking.payment_status == status_filter)
    else:
        query = query.filter(Booking.payment_status.in_(["paid", "hold", "refunded"]))

    if session_filter:
        try:
            query = query.filter(Booking.session_id == int(session_filter))
        except ValueError:
            pass

    bookings = query.order_by(Booking.booked_at.desc()).all()

    enriched = []
    for b in bookings:
        u = db.query(User).get(b.user_id)
        s = db.query(LectureSession).get(b.session_id)
        seat = db.query(Seat).get(b.seat_id)
        if q:
            search = q.lower()
            match = (
                (u and (search in u.username.lower() or search in u.email.lower() or (u.full_name and search in u.full_name.lower())))
                or (s and search in s.title.lower())
                or (b.booking_ref and search in b.booking_ref.lower())
                or (b.ticket_id and search in b.ticket_id.lower())
            )
            if not match:
                continue
        enriched.append({"booking": b, "user": u, "session": s, "seat": seat})

    all_sessions = db.query(LectureSession).order_by(LectureSession.title).all()

    return templates.TemplateResponse(
        "admin/bookings.html",
        _admin_ctx(request, active_page="bookings", bookings=enriched,
                   q=q, status_filter=status_filter, session_filter=session_filter,
                   all_sessions=all_sessions),
    )


@router.get("/bookings/export")
def bookings_csv(
    request: Request,
    db: Session = Depends(get_db),
    q: str = Query("", alias="q"),
    status_filter: str = Query("", alias="status"),
    session_filter: str = Query("", alias="session_id"),
):
    admin = _require_supervisor_or_admin(request, db)
    if not admin:
        return RedirectResponse("/auth/login", status_code=303)

    query = db.query(Booking)
    if status_filter:
        query = query.filter(Booking.payment_status == status_filter)
    else:
        query = query.filter(Booking.payment_status.in_(["paid", "hold", "refunded"]))

    if session_filter:
        try:
            query = query.filter(Booking.session_id == int(session_filter))
        except ValueError:
            pass

    bookings = query.order_by(Booking.booked_at.desc()).all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Booking Ref", "Ticket ID", "User", "Email", "Session", "Seat", "Status", "Amount Paid", "Refund", "Booked At", "Checked In"])
    for b in bookings:
        u = db.query(User).get(b.user_id)
        s = db.query(LectureSession).get(b.session_id)
        seat = db.query(Seat).get(b.seat_id)
        if q:
            search = q.lower()
            match = (
                (u and (search in u.username.lower() or search in u.email.lower() or (u.full_name and search in u.full_name.lower())))
                or (s and search in s.title.lower())
                or (b.booking_ref and search in b.booking_ref.lower())
                or (b.ticket_id and search in b.ticket_id.lower())
            )
            if not match:
                continue
        writer.writerow([
            b.booking_ref,
            b.ticket_id or "",
            u.username if u else "",
            u.email if u else "",
            s.title if s else "",
            seat.label if seat else "",
            b.payment_status,
            b.amount_paid or "",
            b.refund_amount or "",
            b.booked_at.strftime("%Y-%m-%d %H:%M") if b.booked_at else "",
            "Yes" if b.checked_in else "No",
        ])

    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=techtrek_bookings.csv"},
    )


@router.post("/bookings/{booking_id}/cancel")
def booking_cancel(request: Request, booking_id: int, db: Session = Depends(get_db)):
    admin = _require_admin(request, db)
    if not admin:
        return RedirectResponse("/auth/login", status_code=303)
    b = db.query(Booking).get(booking_id)
    if b:
        b.payment_status = "cancelled"
        log_activity(db, category="admin", action="cancel", description=f"Admin cancelled booking {b.booking_ref}", request=request, user_id=admin.id, target_type="booking", target_id=booking_id)
        db.commit()
        flash(request, f"Booking {b.booking_ref} cancelled.", "success")
    return RedirectResponse("/admin/bookings", status_code=303)


@router.get("/bookings/{booking_id}/invoice")
def admin_booking_invoice(request: Request, booking_id: int, db: Session = Depends(get_db)):
    admin = _require_admin(request, db)
    if not admin:
        return RedirectResponse("/auth/login", status_code=303)

    booking = db.query(Booking).get(booking_id)
    if not booking:
        flash(request, "Booking not found.", "danger")
        return RedirectResponse("/admin/bookings", status_code=303)

    group_bookings = (
        db.query(Booking)
        .filter(
            Booking.booking_group == booking.booking_group,
            Booking.payment_status.in_(["paid", "refunded"]),
        )
        .all()
    ) if booking.booking_group else [booking]
    if not group_bookings:
        group_bookings = [booking]

    user = db.query(User).get(booking.user_id)
    lecture = db.query(LectureSession).get(booking.session_id)
    auditorium = db.query(Auditorium).get(lecture.auditorium_id) if lecture else None
    if not user or not lecture or not auditorium:
        flash(request, "Related data not found.", "danger")
        return RedirectResponse("/admin/bookings", status_code=303)

    seats = [db.query(Seat).get(b.seat_id) for b in group_bookings]
    custom_types_map = {f"custom_{st.id}": st for st in db.query(SeatType).filter(SeatType.is_custom == True).all()}
    pdf_bytes = generate_invoice_pdf(group_bookings, user, lecture, auditorium, seats, custom_types_map)
    ref = booking.booking_ref or "invoice"
    return StreamingResponse(
        io.BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="invoice-{ref}.pdf"'},
    )


@router.post("/bookings/{booking_id}/refund")
def booking_refund(request: Request, booking_id: int, db: Session = Depends(get_db)):
    admin = _require_admin(request, db)
    if not admin:
        return RedirectResponse("/auth/login", status_code=303)
    b = db.query(Booking).get(booking_id)
    can_refund = b and b.payment_status in ("paid", "refunded") and (
        b.payment_status == "paid" or b.refund_status == "failed"
    )
    if can_refund:
        price = b.amount_paid or 0
        refund_amount = float(price)

        rz_ok = True
        rz_result = None
        if b.razorpay_payment_id and refund_amount > 0:
            rz_result = rz_process_refund(b.razorpay_payment_id, int(refund_amount * 100))
            rz_ok = rz_result is not None

        b.payment_status = "refunded"
        b.refund_amount = refund_amount
        if rz_result and isinstance(rz_result, dict):
            b.refund_id = rz_result.get("id")
            b.refund_status = "initiated"
        elif rz_ok:
            b.refund_status = "completed"
            b.refund_processed_at = now_ist()
        else:
            b.refund_status = "failed"

        log_activity(db, category="admin", action="refund", description=f"Admin refunded booking {b.booking_ref} (₹{refund_amount:.0f})", request=request, user_id=admin.id, target_type="booking", target_id=booking_id)
        db.commit()

        if rz_ok:
            flash(request, f"Booking {b.booking_ref} refunded (₹{refund_amount:.0f}).", "success")
        else:
            flash(request, f"Booking {b.booking_ref} marked refunded but Razorpay API call failed — process the ₹{refund_amount:.0f} refund manually.", "warning")
    elif b and b.payment_status != "paid":
        flash(request, f"Booking {b.booking_ref} is not in 'paid' status — cannot refund.", "danger")
    return RedirectResponse("/admin/bookings", status_code=303)


# ─── Check-in ───

@router.get("/checkin")
def checkin_page(request: Request, db: Session = Depends(get_db)):
    admin = _require_supervisor_or_admin(request, db)
    if not admin:
        return RedirectResponse("/auth/login", status_code=303)
    sessions = (
        db.query(LectureSession)
        .filter(LectureSession.status.in_(["published", "completed"]))
        .order_by(LectureSession.start_time.desc())
        .all()
    )
    return templates.TemplateResponse(
        "admin/checkin.html",
        _admin_ctx(request, active_page="checkin", sessions=sessions, result=None),
    )


@router.post("/checkin")
async def checkin_verify(request: Request, db: Session = Depends(get_db)):
    admin = _require_supervisor_or_admin(request, db)
    if not admin:
        return RedirectResponse("/auth/login", status_code=303)

    form = await _form(request)
    ticket_id = form.get("ticket_id", "").strip()
    session_id_raw = form.get("session_id", "")

    sessions = (
        db.query(LectureSession)
        .filter(LectureSession.status.in_(["published", "completed"]))
        .order_by(LectureSession.start_time.desc())
        .all()
    )

    if not ticket_id:
        return templates.TemplateResponse(
            "admin/checkin.html",
            _admin_ctx(request, active_page="checkin", sessions=sessions, result={"status": "error", "msg": "Please enter a ticket ID."}),
        )

    is_group = ticket_id.startswith("GROUP-")

    if is_group:
        group_id = ticket_id[6:]
        group_query = db.query(Booking).filter(
            Booking.booking_group == group_id,
            Booking.payment_status == "paid",
        )
        if session_id_raw:
            try:
                group_query = group_query.filter(Booking.session_id == int(session_id_raw))
            except ValueError:
                pass
        group_bookings = group_query.all()

        if not group_bookings:
            result = {"status": "error", "msg": f"Group '{group_id}' not found or no valid tickets."}
        else:
            now = now_ist()
            newly_checked = []
            already_checked = []
            for gb in group_bookings:
                if gb.checked_in:
                    seat = db.query(Seat).get(gb.seat_id)
                    already_checked.append(seat.label if seat else gb.ticket_id)
                else:
                    gb.checked_in = True
                    gb.checked_in_at = now
                    seat = db.query(Seat).get(gb.seat_id)
                    newly_checked.append(seat.label if seat else gb.ticket_id)
            db.commit()

            user = db.query(User).get(group_bookings[0].user_id)
            lecture = db.query(LectureSession).get(group_bookings[0].session_id)

            if newly_checked and not already_checked:
                msg = f"Group check-in successful! {len(newly_checked)} ticket(s) checked in."
                status = "success"
                log_activity(db, category="admin", action="checkin", description=f"Group check-in: {len(newly_checked)} ticket(s) for '{lecture.title if lecture else 'unknown'}'", request=request, user_id=admin.id, target_type="booking", target_id=group_bookings[0].id)
            elif newly_checked and already_checked:
                msg = f"Checked in {len(newly_checked)} ticket(s). {len(already_checked)} already checked in."
                status = "success"
                log_activity(db, category="admin", action="checkin", description=f"Partial group check-in: {len(newly_checked)} new for '{lecture.title if lecture else 'unknown'}'", request=request, user_id=admin.id, target_type="booking", target_id=group_bookings[0].id)
            else:
                msg = f"All {len(already_checked)} ticket(s) in this group were already checked in."
                status = "warning"

            result = {
                "status": status,
                "msg": msg,
                "is_group": True,
                "user_name": user.full_name or user.username if user else "Unknown",
                "user_email": user.email if user else "",
                "session_title": lecture.title if lecture else "",
                "newly_checked": newly_checked,
                "already_checked": already_checked,
            }
    else:
        query = db.query(Booking).filter(Booking.ticket_id == ticket_id, Booking.payment_status == "paid")
        if session_id_raw:
            try:
                query = query.filter(Booking.session_id == int(session_id_raw))
            except ValueError:
                pass
        booking = query.first()

        if not booking:
            result = {"status": "error", "msg": f"Ticket '{ticket_id}' not found or not valid."}
        elif booking.checked_in:
            result = {"status": "warning", "msg": f"Ticket '{ticket_id}' was already checked in at {booking.checked_in_at.strftime('%I:%M %p') if booking.checked_in_at else 'earlier'}."}
        else:
            booking.checked_in = True
            booking.checked_in_at = now_ist()
            user = db.query(User).get(booking.user_id)
            seat = db.query(Seat).get(booking.seat_id)
            lecture = db.query(LectureSession).get(booking.session_id)
            log_activity(db, category="admin", action="checkin", description=f"Checked in ticket '{ticket_id}' (seat {seat.label if seat else '?'}) for '{lecture.title if lecture else 'unknown'}'", request=request, user_id=admin.id, target_type="booking", target_id=booking.id)
            db.commit()
            result = {
                "status": "success",
                "msg": "Check-in successful!",
                "user_name": user.full_name or user.username if user else "Unknown",
                "user_email": user.email if user else "",
                "seat_label": seat.label if seat else "",
                "session_title": lecture.title if lecture else "",
                "ticket_id": ticket_id,
            }

    # Live stats for the selected session
    stats = None
    if session_id_raw:
        try:
            sid = int(session_id_raw)
            total_booked = db.query(func.count(Booking.id)).filter(Booking.session_id == sid, Booking.payment_status == "paid").scalar()
            checked_in_count = db.query(func.count(Booking.id)).filter(Booking.session_id == sid, Booking.payment_status == "paid", Booking.checked_in == True).scalar()
            stats = {"total": total_booked, "checked_in": checked_in_count}
        except ValueError:
            pass

    return templates.TemplateResponse(
        "admin/checkin.html",
        _admin_ctx(request, active_page="checkin", sessions=sessions, result=result, stats=stats, selected_session=session_id_raw),
    )


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
    now = now_ist()
    expires = now + timedelta(hours=settings.priority_window_hours)

    for e in entries:
        e.priority_session_id = target_session_id
        e.priority_expires_at = expires
        e.notified = True

    log_activity(db, category="admin", action="grant_priority", description=f"Granted priority to {len(entries)} waitlisted user(s) for session #{target_session_id}", request=request, user_id=admin.id, target_type="waitlist", target_id=source_session_id)
    db.commit()
    flash(request, f"Priority granted to {len(entries)} waitlisted user(s).", "success")
    return RedirectResponse("/admin/waitlist", status_code=303)


# ─── Users ───

@router.get("/users")
def users_list(request: Request, db: Session = Depends(get_db)):
    admin = _require_supervisor_or_admin(request, db)
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
        status = "admin" if u.is_admin else "regular user"
        log_activity(db, category="admin", action="role_change", description=f"Changed {u.username} role to {status}", request=request, user_id=admin.id, target_type="user", target_id=user_id)
        db.commit()
        flash(request, f"{u.username} is now a {status}.", "success")
    return RedirectResponse("/admin/users", status_code=303)


@router.post("/users/{user_id}/toggle-supervisor")
def toggle_supervisor(request: Request, user_id: int, db: Session = Depends(get_db)):
    admin = _require_admin(request, db)
    if not admin:
        return RedirectResponse("/auth/login", status_code=303)
    u = db.query(User).get(user_id)
    if u and u.id != admin.id:
        u.is_supervisor = not u.is_supervisor
        status = "supervisor" if u.is_supervisor else "regular user"
        log_activity(db, category="admin", action="role_change", description=f"Changed {u.username} role to {status}", request=request, user_id=admin.id, target_type="user", target_id=user_id)
        db.commit()
        flash(request, f"{u.username} is now a {status}.", "success")
    return RedirectResponse("/admin/users", status_code=303)


# ─── Schedule (Admin) ───

@router.get("/schedule")
def admin_schedule(
    request: Request,
    db: Session = Depends(get_db),
    college_id: str = Query("", alias="college_id"),
    auditorium_id: str = Query("", alias="auditorium_id"),
):
    admin = _require_supervisor_or_admin(request, db)
    if not admin:
        return RedirectResponse("/auth/login", status_code=303)

    query = db.query(LectureSession).filter(
        LectureSession.status.in_(["published", "completed"])
    )
    if auditorium_id:
        try:
            query = query.filter(LectureSession.auditorium_id == int(auditorium_id))
        except ValueError:
            pass
    elif college_id:
        try:
            aud_ids = [a.id for a in db.query(Auditorium.id).filter(Auditorium.college_id == int(college_id)).all()]
            if aud_ids:
                query = query.filter(LectureSession.auditorium_id.in_(aud_ids))
            else:
                query = query.filter(False)
        except ValueError:
            pass

    sessions = query.order_by(LectureSession.start_time).all()

    grouped = defaultdict(list)
    for s in sessions:
        aud = db.query(Auditorium).get(s.auditorium_id)
        date_key = s.start_time.strftime("%Y-%m-%d")
        grouped[date_key].append({"session": s, "auditorium": aud})

    colleges = db.query(College).order_by(College.name).all()
    auditoriums = db.query(Auditorium).order_by(Auditorium.name).all()

    return templates.TemplateResponse(
        "admin/schedule_admin.html",
        _admin_ctx(
            request, active_page="schedule",
            grouped=dict(sorted(grouped.items())),
            colleges=colleges, auditoriums=auditoriums,
            college_id=college_id, auditorium_id=auditorium_id,
        ),
    )


# ─── Activity Log ───

ACTIVITY_LOG_PAGE_SIZE = 50

@router.get("/activity-log")
def activity_log_page(
    request: Request,
    db: Session = Depends(get_db),
    category: str = Query("", alias="category"),
    q: str = Query("", alias="q"),
    date_from: str = Query("", alias="date_from"),
    date_to: str = Query("", alias="date_to"),
    page: int = Query(1, alias="page", ge=1),
):
    admin = _require_admin(request, db)
    if not admin:
        return RedirectResponse("/auth/login", status_code=303)

    query = db.query(ActivityLog)

    if category:
        query = query.filter(ActivityLog.category == category)
    if q:
        search = f"%{q}%"
        query = query.filter(
            ActivityLog.description.ilike(search)
            | ActivityLog.action.ilike(search)
        )
    if date_from:
        try:
            dt_from = datetime.fromisoformat(date_from)
            query = query.filter(ActivityLog.timestamp >= dt_from)
        except ValueError:
            pass
    if date_to:
        try:
            dt_to = datetime.fromisoformat(date_to)
            dt_to = dt_to.replace(hour=23, minute=59, second=59)
            query = query.filter(ActivityLog.timestamp <= dt_to)
        except ValueError:
            pass

    total = query.count()
    total_pages = max(1, (total + ACTIVITY_LOG_PAGE_SIZE - 1) // ACTIVITY_LOG_PAGE_SIZE)
    page = min(page, total_pages)

    logs = (
        query.order_by(ActivityLog.timestamp.desc())
        .offset((page - 1) * ACTIVITY_LOG_PAGE_SIZE)
        .limit(ACTIVITY_LOG_PAGE_SIZE)
        .all()
    )

    return templates.TemplateResponse(
        "admin/activity_log.html",
        _admin_ctx(
            request,
            active_page="activity_log",
            logs=logs,
            total=total,
            page=page,
            total_pages=total_pages,
            filter_category=category,
            filter_q=q,
            filter_date_from=date_from,
            filter_date_to=date_to,
        ),
    )
