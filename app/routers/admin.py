import csv
import io
import json
from collections import defaultdict
from datetime import date, datetime, timedelta
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse, RedirectResponse, StreamingResponse
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.csrf import csrf_protection
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
from app.models.session import Session as SessionModel
from app.models.session_speaker import SessionSpeaker, SPEAKER_ROLES
from app.models.speaker import Speaker
from app.models.agenda import AgendaItem
from app.models.session_recording import SessionRecording
from app.models.event import Event
from app.models.coupon import Coupon
from app.models.feedback import Feedback
from app.models.testimonial import Testimonial
from app.models.user import User
from app.services.razorpay import process_refund as rz_process_refund
from app.models.waitlist import Waitlist
from app.models.site_setting import SiteSetting
from app.models.newsletter import Newsletter
from app.models.testimonial import NewsletterSubscriber
from app.config import settings


RECORDING_ALLOWED_HOSTS = {
    "youtube.com", "www.youtube.com", "youtu.be",
    "vimeo.com", "player.vimeo.com",
    "dailymotion.com", "www.dailymotion.com", "dai.ly",
    "twitch.tv", "www.twitch.tv", "clips.twitch.tv",
    "facebook.com", "www.facebook.com", "fb.watch",
    "streamable.com",
    "wistia.com", "fast.wistia.com",
    "loom.com", "www.loom.com",
    "drive.google.com",
}


def _validate_recording_url(url: str | None) -> str | None:
    """Return an error message if the URL is invalid, or None if it's acceptable."""
    if not url:
        return None
    parsed = urlparse(url)
    if parsed.scheme != "https":
        return "Recording URL must use HTTPS."
    host = parsed.hostname or ""
    if host not in RECORDING_ALLOWED_HOSTS:
        return (
            f"Unsupported recording host '{host}'. "
            "Supported: YouTube, Vimeo, Dailymotion, Twitch, Facebook, "
            "Streamable, Wistia, Loom, Google Drive."
        )
    return None


router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(csrf_protection)])


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
    total_revenue = db.query(func.sum(Booking.amount_paid)).filter(Booking.payment_status == "paid").scalar() or 0

    now = now_ist()
    today = now.date()
    upcoming_count = db.query(func.count(Event.id)).filter(
        Event.status == "published", Event.start_date >= today
    ).scalar()

    total_checked_in = db.query(func.count(Booking.id)).filter(Booking.checked_in == True).scalar()
    total_refunded = db.query(func.count(Booking.id)).filter(Booking.payment_status == "refunded").scalar()

    status_counts = (
        db.query(Event.status, func.count(Event.id))
        .group_by(Event.status)
        .all()
    )
    event_statuses = {s: c for s, c in status_counts}

    top_cities = []
    city_rows = (
        db.query(City.name, func.count(Booking.id))
        .select_from(Booking)
        .join(Event, Booking.event_id == Event.id)
        .join(College, Event.college_id == College.id)
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
        event = db.query(Event).get(b.event_id) if b.event_id else None
        seat = db.query(Seat).get(b.seat_id)
        enriched_bookings.append({"booking": b, "user": u, "event": event, "seat": seat})

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
        price=float(form["price"]) if form.get("price", "").strip() else None,
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
    st.price = float(form["price"]) if form.get("price", "").strip() else None
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
            seat_data=seat_data,
            custom_types=custom_types_data,
            row_gaps=json.loads(aud.row_gaps) if aud.row_gaps else [],
            col_gaps=json.loads(aud.col_gaps) if aud.col_gaps else [],
            entry_exit_config=aud.entry_exit_config or [],
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


@router.get("/speakers/{speaker_id}/delete-check")
def speaker_delete_check(request: Request, speaker_id: int, db: Session = Depends(get_db)):
    admin = _require_admin(request, db)
    if not admin:
        return JSONResponse({"error": "unauthorized"}, status_code=403)
    sp = db.query(Speaker).get(speaker_id)
    if not sp:
        return JSONResponse({"error": "not_found"}, status_code=404)
    now = now_ist()
    primary_sessions = (
        db.query(SessionModel)
        .join(Event, SessionModel.event_id == Event.id)
        .filter(SessionModel.speaker_id == speaker_id, Event.start_date >= now.date())
        .all()
    )
    agenda_sessions = (
        db.query(SessionModel)
        .join(AgendaItem, AgendaItem.session_id == SessionModel.id)
        .join(Event, SessionModel.event_id == Event.id)
        .filter(AgendaItem.speaker_id == speaker_id, Event.start_date >= now.date())
        .all()
    )
    seen = set()
    sessions_list = []
    for s in primary_sessions:
        if s.id not in seen:
            seen.add(s.id)
            ev = s.event
            date_str = ev.start_date.strftime("%b %d, %Y") if ev and ev.start_date else ""
            sessions_list.append({"id": s.id, "title": s.title, "date": date_str, "role": "Primary Speaker"})
    for s in agenda_sessions:
        if s.id not in seen:
            seen.add(s.id)
            ev = s.event
            date_str = ev.start_date.strftime("%b %d, %Y") if ev and ev.start_date else ""
            sessions_list.append({"id": s.id, "title": s.title, "date": date_str, "role": "Agenda Item"})
    return JSONResponse({"speaker_name": sp.name, "has_sessions": len(sessions_list) > 0, "sessions": sessions_list})


@router.post("/speakers/{speaker_id}/delete")
async def speaker_delete(request: Request, speaker_id: int, db: Session = Depends(get_db)):
    admin = _require_admin(request, db)
    if not admin:
        return RedirectResponse("/auth/login", status_code=303)
    sp = db.query(Speaker).get(speaker_id)
    if not sp:
        return RedirectResponse("/admin/speakers", status_code=303)
    form = await _form(request)
    session_action = form.get("session_action", "draft")
    linked_primary = db.query(SessionModel).filter(SessionModel.speaker_id == speaker_id).all()
    linked_agenda = db.query(AgendaItem).filter(AgendaItem.speaker_id == speaker_id).all()
    if session_action == "delete":
        for s in linked_primary:
            db.delete(s)
    else:
        for s in linked_primary:
            s.speaker_id = None
    for ai in linked_agenda:
        ai.speaker_id = None
        ai.speaker_name = None
    db.flush()
    log_activity(db, category="admin", action="delete", description=f"Deleted speaker '{sp.name}' (sessions: {session_action})", request=request, user_id=admin.id, target_type="speaker", target_id=speaker_id)
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
    admin = _require_admin(request, db)
    if not admin:
        return RedirectResponse("/auth/login", status_code=303)
    all_sessions = db.query(SessionModel).order_by(SessionModel.created_at.desc()).all()
    enriched = []
    for s in all_sessions:
        event = s.event
        total_bookings = (
            db.query(func.count(Booking.id)).filter(
                Booking.event_id == event.id, Booking.payment_status == "paid"
            ).scalar() or 0
        ) if event else 0
        enriched.append({"session": s, "event": event, "bookings": total_bookings})
    return templates.TemplateResponse(
        "admin/sessions.html",
        _admin_ctx(request, active_page="sessions", sessions=enriched),
    )


@router.get("/sessions/new")
def session_new(request: Request, event_id: int | None = None, db: Session = Depends(get_db)):
    admin = _require_admin(request, db)
    if not admin:
        return RedirectResponse("/auth/login", status_code=303)
    speakers = db.query(Speaker).order_by(Speaker.name).all()
    events = db.query(Event).order_by(Event.name).all()
    return templates.TemplateResponse(
        "admin/session_form.html",
        _admin_ctx(request, active_page="sessions", lecture=None,
                   events=events, speakers=speakers,
                   preselect_event_id=event_id,
                   agenda_items=[], session_speakers=[], speaker_roles=SPEAKER_ROLES),
    )


@router.post("/sessions/new")
async def session_create(request: Request, db: Session = Depends(get_db)):
    admin = _require_admin(request, db)
    if not admin:
        return RedirectResponse("/auth/login", status_code=303)

    form = await _form(request)
    event_id_raw = form.get("event_id", "")
    event_id = int(event_id_raw) if event_id_raw and event_id_raw.strip().isdigit() else None

    start_str = form.get("start_time", "")
    start_time = None
    if start_str:
        try:
            start_time = datetime.fromisoformat(start_str)
        except ValueError:
            pass

    speaker_id_raw = form.get("speaker_id")
    speaker_id = int(speaker_id_raw) if speaker_id_raw and speaker_id_raw != "" else None

    session_obj = SessionModel(
        event_id=event_id,
        speaker_id=speaker_id,
        title=form.get("title", "").strip(),
        speaker_name=form.get("speaker_name", "").strip() or form.get("speaker", "").strip(),
        description=form.get("description", "").strip(),
        banner_url=form.get("banner_url", "").strip() or None,
        duration_minutes=int(form.get("duration_minutes", 30)),
        start_time=start_time,
        order=int(form.get("order", 0) or 0),
    )

    db.add(session_obj)
    db.flush()

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
    lecture = db.query(SessionModel).get(sess_id)
    if not lecture:
        flash(request, "Session not found.", "danger")
        return RedirectResponse("/admin/sessions", status_code=303)
    speakers = db.query(Speaker).order_by(Speaker.name).all()
    events = db.query(Event).order_by(Event.name).all()
    agenda_items = db.query(AgendaItem).filter(AgendaItem.session_id == sess_id).order_by(AgendaItem.order).all()
    session_speakers = db.query(SessionSpeaker).filter(SessionSpeaker.session_id == sess_id).all()
    return templates.TemplateResponse(
        "admin/session_form.html",
        _admin_ctx(request, active_page="sessions", lecture=lecture,
                   events=events, speakers=speakers,
                   agenda_items=agenda_items, session_speakers=session_speakers,
                   speaker_roles=SPEAKER_ROLES),
    )


@router.post("/sessions/{sess_id}/edit")
async def session_update(request: Request, sess_id: int, db: Session = Depends(get_db)):
    admin = _require_admin(request, db)
    if not admin:
        return RedirectResponse("/auth/login", status_code=303)

    lecture = db.query(SessionModel).get(sess_id)
    if not lecture:
        return RedirectResponse("/admin/sessions", status_code=303)

    form = await _form(request)

    speaker_id_raw = form.get("speaker_id")
    lecture.speaker_id = int(speaker_id_raw) if speaker_id_raw and speaker_id_raw != "" else None
    event_id_raw = form.get("event_id", "")
    lecture.event_id = int(event_id_raw) if event_id_raw and event_id_raw.strip().isdigit() else lecture.event_id
    lecture.title = form.get("title", lecture.title).strip()
    lecture.speaker_name = form.get("speaker_name", "").strip() or form.get("speaker", lecture.speaker_name).strip()
    lecture.description = form.get("description", "").strip()
    lecture.banner_url = form.get("banner_url", "").strip() or None
    lecture.duration_minutes = int(form.get("duration_minutes", 30))
    start_str = form.get("start_time", "")
    if start_str:
        try:
            lecture.start_time = datetime.fromisoformat(start_str)
        except ValueError:
            pass
    lecture.order = int(form.get("order", lecture.order or 0) or 0)

    _save_agenda_items(db, form, sess_id)
    _save_session_speakers(db, form, sess_id)

    log_activity(db, category="admin", action="update", description=f"Updated session '{lecture.title}'", request=request, user_id=admin.id, target_type="session", target_id=sess_id)
    db.commit()
    flash(request, f"Session '{lecture.title}' updated.", "success")
    return RedirectResponse(f"/admin/sessions/{sess_id}/edit", status_code=303)


def _collect_speaker_ids_from_form(form) -> list[int]:
    ids = []
    idx = 0
    while True:
        raw = form.get(f"session_speaker_id_{idx}")
        if raw is None:
            break
        raw = raw.strip()
        if raw:
            ids.append(int(raw))
        idx += 1
    return ids


def _save_agenda_items(db: Session, form, session_id: int):
    db.query(AgendaItem).filter(AgendaItem.session_id == session_id).delete()
    idx = 0
    while True:
        title = form.get(f"agenda_title_{idx}")
        if title is None:
            break
        title = title.strip()
        if title:
            sp_id_raw = form.get(f"agenda_speaker_id_{idx}", "").strip()
            sp_id = int(sp_id_raw) if sp_id_raw else None
            sp_name = None
            if sp_id:
                sp_obj = db.query(Speaker).get(sp_id)
                sp_name = sp_obj.name if sp_obj else None
            item = AgendaItem(
                session_id=session_id,
                order=idx,
                title=title,
                speaker_id=sp_id,
                speaker_name=sp_name,
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



@router.post("/sessions/{sess_id}/delete")
def session_delete(request: Request, sess_id: int, db: Session = Depends(get_db)):
    admin = _require_admin(request, db)
    if not admin:
        return RedirectResponse("/auth/login", status_code=303)
    lecture = db.query(SessionModel).get(sess_id)
    if lecture:
        log_activity(db, category="admin", action="delete", description=f"Deleted session '{lecture.title}'", request=request, user_id=admin.id, target_type="session", target_id=sess_id)
        db.delete(lecture)
        db.commit()
        flash(request, f"Session '{lecture.title}' deleted.", "success")
    return RedirectResponse("/admin/sessions", status_code=303)




# ─── Certificate Preview (Event-level) ───

@router.get("/events/{event_id}/certificate/preview")
def event_certificate_preview(
    request: Request, event_id: int, db: Session = Depends(get_db)
):
    import io as _io
    from types import SimpleNamespace
    from app.services.certificate import generate_certificate_pdf

    admin = _require_admin(request, db)
    if not admin:
        return RedirectResponse("/auth/login", status_code=303)

    event = db.query(Event).get(event_id)
    if not event:
        flash(request, "Event not found.", "danger")
        return RedirectResponse("/admin/events", status_code=303)

    auditorium = db.query(Auditorium).get(event.auditorium_id) if event.auditorium_id else None

    dummy_booking = SimpleNamespace(
        booking_ref="PREVIEW",
        qr_code_data="CERT-PREVIEW-SAMPLE",
    )
    dummy_user = SimpleNamespace(
        full_name="Sample Attendee",
        username="sample_attendee",
    )

    pdf_bytes = generate_certificate_pdf(dummy_booking, dummy_user, event, event, auditorium)

    return StreamingResponse(
        _io.BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={
            "Content-Disposition": 'inline; filename="certificate-preview.pdf"',
            "Cache-Control": "no-store",
        },
    )


@router.post("/events/{event_id}/certificate/save")
async def event_certificate_save(
    request: Request, event_id: int, db: Session = Depends(get_db)
):
    """Save only certificate template fields on the event."""
    admin = _require_admin(request, db)
    if not admin:
        return RedirectResponse("/auth/login", status_code=303)

    event = db.query(Event).get(event_id)
    if not event:
        flash(request, "Event not found.", "danger")
        return RedirectResponse("/admin/events", status_code=303)

    form = await request.form()
    event.cert_title = form.get("cert_title", "").strip() or None
    event.cert_subtitle = form.get("cert_subtitle", "").strip() or None
    event.cert_footer = form.get("cert_footer", "").strip() or None
    event.cert_signer_name = form.get("cert_signer_name", "").strip() or None
    event.cert_signer_designation = form.get("cert_signer_designation", "").strip() or None
    event.cert_signature_url = form.get("cert_signature_url", "").strip() or None
    event.cert_logo_url = form.get("cert_logo_url", "").strip() or None
    event.cert_bg_url = form.get("cert_bg_url", "").strip() or None
    event.cert_color_scheme = form.get("cert_color_scheme", "").strip() or None
    event.cert_style = form.get("cert_style", "").strip() or None
    db.commit()

    flash(request, "Certificate template saved.", "success")
    return RedirectResponse(f"/admin/events/{event_id}/edit", status_code=303)


@router.post("/events/certificate/preview-image")
async def event_certificate_preview_image(
    request: Request, db: Session = Depends(get_db)
):
    """Generate a PNG thumbnail of the certificate from live form values."""
    import io as _io
    from types import SimpleNamespace
    import pypdfium2
    from app.services.certificate import generate_certificate_pdf
    from fastapi.responses import Response

    admin = _require_admin(request, db)
    if not admin:
        return Response(status_code=403)

    form = await request.form()

    aud_id = form.get("auditorium_id", "")
    auditorium = None
    if aud_id and aud_id.strip().isdigit():
        auditorium = db.query(Auditorium).get(int(aud_id))

    draft_event = SimpleNamespace(
        name=form.get("name", "").strip() or "Event Title",
        start_date=date.today(),
        cert_title=form.get("cert_title", "").strip() or None,
        cert_subtitle=form.get("cert_subtitle", "").strip() or None,
        cert_footer=form.get("cert_footer", "").strip() or None,
        cert_signer_name=form.get("cert_signer_name", "").strip() or None,
        cert_signer_designation=form.get("cert_signer_designation", "").strip() or None,
        cert_signature_url=form.get("cert_signature_url", "").strip() or None,
        cert_logo_url=form.get("cert_logo_url", "").strip() or None,
        cert_bg_url=form.get("cert_bg_url", "").strip() or None,
        cert_color_scheme=form.get("cert_color_scheme", "").strip() or None,
        cert_style=form.get("cert_style", "").strip() or None,
    )
    dummy_booking = SimpleNamespace(
        booking_ref="PREVIEW",
        qr_code_data="CERT-PREVIEW-SAMPLE",
    )
    dummy_user = SimpleNamespace(
        full_name="Sample Attendee",
        username="sample_attendee",
    )

    pdf_bytes = generate_certificate_pdf(dummy_booking, dummy_user, draft_event, draft_event, auditorium)

    pdf_doc = pypdfium2.PdfDocument(pdf_bytes)
    page = pdf_doc[0]
    scale = 1.5
    bitmap = page.render(scale=scale)
    pil_image = bitmap.to_pil()
    png_buf = _io.BytesIO()
    pil_image.save(png_buf, format="PNG", optimize=True)
    page.close()
    pdf_doc.close()

    return Response(
        content=png_buf.getvalue(),
        media_type="image/png",
        headers={"Cache-Control": "no-store"},
    )


# ─── Session Recordings ───

@router.get("/sessions/{sess_id}/recordings")
def session_recordings(request: Request, sess_id: int, db: Session = Depends(get_db)):
    from app.routers.public import _build_embed_url
    admin = _require_admin(request, db)
    if not admin:
        return RedirectResponse("/auth/login", status_code=303)
    lecture = db.query(SessionModel).get(sess_id)
    if not lecture:
        flash(request, "Session not found.", "danger")
        return RedirectResponse("/admin/sessions", status_code=303)
    recordings = (
        db.query(SessionRecording)
        .filter(SessionRecording.session_id == sess_id)
        .order_by(SessionRecording.order)
        .all()
    )
    enriched = [{"rec": r, "embed_url": _build_embed_url(r.url)} for r in recordings]
    return templates.TemplateResponse(
        "admin/session_recordings.html",
        _admin_ctx(request, active_page="sessions", lecture=lecture, recordings=enriched),
    )


@router.post("/sessions/{sess_id}/recordings")
async def session_recording_add(request: Request, sess_id: int, db: Session = Depends(get_db)):
    admin = _require_admin(request, db)
    if not admin:
        return RedirectResponse("/auth/login", status_code=303)
    lecture = db.query(SessionModel).get(sess_id)
    if not lecture:
        flash(request, "Session not found.", "danger")
        return RedirectResponse("/admin/sessions", status_code=303)
    form = await request.form()
    url = form.get("url", "").strip()
    err = _validate_recording_url(url)
    if err:
        flash(request, err, "danger")
        return RedirectResponse(f"/admin/sessions/{sess_id}/recordings", status_code=303)
    title = form.get("title", "").strip() or None
    is_public = "is_public" in form
    max_order = db.query(func.coalesce(func.max(SessionRecording.order), -1)).filter(
        SessionRecording.session_id == sess_id
    ).scalar()
    rec = SessionRecording(
        session_id=sess_id,
        url=url,
        title=title,
        order=max_order + 1,
        is_public=is_public,
    )
    db.add(rec)
    db.commit()
    flash(request, "Recording added.", "success")
    return RedirectResponse(f"/admin/sessions/{sess_id}/recordings", status_code=303)


@router.post("/sessions/{sess_id}/recordings/{rec_id}/update")
async def session_recording_update(request: Request, sess_id: int, rec_id: int, db: Session = Depends(get_db)):
    admin = _require_admin(request, db)
    if not admin:
        return RedirectResponse("/auth/login", status_code=303)
    rec = db.query(SessionRecording).filter(
        SessionRecording.id == rec_id, SessionRecording.session_id == sess_id
    ).first()
    if not rec:
        flash(request, "Recording not found.", "danger")
        return RedirectResponse(f"/admin/sessions/{sess_id}/recordings", status_code=303)
    form = await request.form()
    rec.title = form.get("title", "").strip() or None
    db.commit()
    flash(request, "Recording title updated.", "success")
    return RedirectResponse(f"/admin/sessions/{sess_id}/recordings", status_code=303)


@router.post("/sessions/{sess_id}/recordings/{rec_id}/toggle")
def session_recording_toggle(request: Request, sess_id: int, rec_id: int, db: Session = Depends(get_db)):
    admin = _require_admin(request, db)
    if not admin:
        return RedirectResponse("/auth/login", status_code=303)
    rec = db.query(SessionRecording).filter(
        SessionRecording.id == rec_id, SessionRecording.session_id == sess_id
    ).first()
    if rec:
        rec.is_public = not rec.is_public
        db.commit()
    return RedirectResponse(f"/admin/sessions/{sess_id}/recordings", status_code=303)


@router.post("/sessions/{sess_id}/recordings/{rec_id}/delete")
def session_recording_delete(request: Request, sess_id: int, rec_id: int, db: Session = Depends(get_db)):
    admin = _require_admin(request, db)
    if not admin:
        return RedirectResponse("/auth/login", status_code=303)
    rec = db.query(SessionRecording).filter(
        SessionRecording.id == rec_id, SessionRecording.session_id == sess_id
    ).first()
    if rec:
        db.delete(rec)
        db.commit()
        flash(request, "Recording removed.", "success")
    return RedirectResponse(f"/admin/sessions/{sess_id}/recordings", status_code=303)


# ─── Bookings ───

@router.get("/bookings")
def bookings_list(
    request: Request,
    db: Session = Depends(get_db),
    q: str = Query("", alias="q"),
    status_filter: str = Query("", alias="status"),
    event_filter: str = Query("", alias="event_id"),
):
    admin = _require_admin(request, db)
    if not admin:
        return RedirectResponse("/auth/login", status_code=303)

    query = db.query(Booking)
    if status_filter:
        query = query.filter(Booking.payment_status == status_filter)
    else:
        query = query.filter(Booking.payment_status.in_(["paid", "hold", "refunded"]))

    if event_filter:
        try:
            query = query.filter(Booking.event_id == int(event_filter))
        except ValueError:
            pass

    bookings = query.order_by(Booking.booked_at.desc()).all()

    enriched = []
    for b in bookings:
        u = db.query(User).get(b.user_id)
        event = db.query(Event).get(b.event_id) if b.event_id else None
        seat = db.query(Seat).get(b.seat_id)
        if q:
            search = q.lower()
            match = (
                (u and (search in u.username.lower() or search in u.email.lower() or (u.full_name and search in u.full_name.lower())))
                or (event and search in event.name.lower())
                or (b.booking_ref and search in b.booking_ref.lower())
                or (b.ticket_id and search in b.ticket_id.lower())
            )
            if not match:
                continue
        enriched.append({"booking": b, "user": u, "event": event, "seat": seat})

    all_events = db.query(Event).order_by(Event.name).all()

    return templates.TemplateResponse(
        "admin/bookings.html",
        _admin_ctx(request, active_page="bookings", bookings=enriched,
                   q=q, status_filter=status_filter, session_filter=event_filter,
                   all_events=all_events),
    )


@router.get("/bookings/export")
def bookings_csv(
    request: Request,
    db: Session = Depends(get_db),
    q: str = Query("", alias="q"),
    status_filter: str = Query("", alias="status"),
    event_filter: str = Query("", alias="event_id"),
):
    admin = _require_admin(request, db)
    if not admin:
        return RedirectResponse("/auth/login", status_code=303)

    query = db.query(Booking)
    if status_filter:
        query = query.filter(Booking.payment_status == status_filter)
    else:
        query = query.filter(Booking.payment_status.in_(["paid", "hold", "refunded"]))

    if event_filter:
        try:
            query = query.filter(Booking.event_id == int(event_filter))
        except ValueError:
            pass

    bookings = query.order_by(Booking.booked_at.desc()).all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Booking Ref", "Ticket ID", "User", "Email", "Event", "Seat", "Status", "Amount Paid", "Refund", "Booked At", "Checked In"])
    for b in bookings:
        u = db.query(User).get(b.user_id)
        event = db.query(Event).get(b.event_id) if b.event_id else None
        seat = db.query(Seat).get(b.seat_id)
        if q:
            search = q.lower()
            match = (
                (u and (search in u.username.lower() or search in u.email.lower() or (u.full_name and search in u.full_name.lower())))
                or (event and search in event.name.lower())
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
            event.name if event else "",
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
    event = db.query(Event).get(booking.event_id) if booking.event_id else None
    auditorium = db.query(Auditorium).get(event.auditorium_id) if event and event.auditorium_id else None
    if not user or not event or not auditorium:
        flash(request, "Related data not found.", "danger")
        return RedirectResponse("/admin/bookings", status_code=303)

    seats = [db.query(Seat).get(b.seat_id) for b in group_bookings]
    custom_types_map = {f"custom_{st.id}": st for st in db.query(SeatType).filter(SeatType.is_custom == True).all()}
    pdf_bytes = generate_invoice_pdf(group_bookings, user, event, auditorium, seats, custom_types_map, db=db)
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
    admin = _require_admin(request, db)
    if not admin:
        return RedirectResponse("/auth/login", status_code=303)
    events_list = (
        db.query(Event)
        .filter(Event.status.in_(["published", "completed"]))
        .order_by(Event.start_date.desc())
        .all()
    )
    return templates.TemplateResponse(
        "admin/checkin.html",
        _admin_ctx(request, active_page="checkin", events_list=events_list, result=None),
    )


@router.post("/checkin")
async def checkin_verify(request: Request, db: Session = Depends(get_db)):
    admin = _require_admin(request, db)
    if not admin:
        return RedirectResponse("/auth/login", status_code=303)

    form = await _form(request)
    ticket_id = form.get("ticket_id", "").strip()
    event_id_raw = form.get("event_id", "")

    events_list = (
        db.query(Event)
        .filter(Event.status.in_(["published", "completed"]))
        .order_by(Event.start_date.desc())
        .all()
    )

    if not ticket_id:
        return templates.TemplateResponse(
            "admin/checkin.html",
            _admin_ctx(request, active_page="checkin", events_list=events_list, result={"status": "error", "msg": "Please enter a ticket ID."}),
        )

    is_group = ticket_id.startswith("GROUP-")

    if is_group:
        group_id = ticket_id[6:]
        all_group_any_status = db.query(Booking).filter(
            Booking.booking_group == group_id,
        ).all()
        all_group = [b for b in all_group_any_status if b.payment_status == "paid"]
        refunded_count = sum(1 for b in all_group_any_status if b.payment_status in ("refunded", "cancelled"))

        result = None
        group_bookings = []

        if not all_group_any_status:
            result = {"status": "error", "msg": f"Group '{group_id}' not found."}
        elif not all_group:
            result = {"status": "error", "msg": f"No valid (paid) tickets in this group — {refunded_count} ticket(s) are refunded/cancelled."}
        elif event_id_raw:
            try:
                group_bookings = [b for b in all_group if b.event_id == int(event_id_raw)]
            except ValueError:
                group_bookings = all_group
            if not group_bookings:
                result = {"status": "error", "msg": f"No tickets in this group match the selected event."}
        else:
            group_bookings = all_group

        if group_bookings:
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
            event = db.query(Event).get(group_bookings[0].event_id) if group_bookings[0].event_id else None
            event_name = event.name if event else "unknown"
            refunded_note = f" ({refunded_count} ticket(s) in this group are refunded/cancelled.)" if refunded_count else ""

            if newly_checked and not already_checked:
                msg = f"Check-in successful! {len(newly_checked)} ticket(s) for '{event_name}'.{refunded_note}"
                status = "success"
                log_activity(db, category="admin", action="checkin", description=f"Group check-in: {len(newly_checked)} ticket(s) for '{event_name}'", request=request, user_id=admin.id, target_type="booking", target_id=group_bookings[0].id)
            elif newly_checked and already_checked:
                msg = f"Checked in {len(newly_checked)} ticket(s). {len(already_checked)} already checked in.{refunded_note}"
                status = "success"
                log_activity(db, category="admin", action="checkin", description=f"Partial group check-in: {len(newly_checked)} new for '{event_name}'", request=request, user_id=admin.id, target_type="booking", target_id=group_bookings[0].id)
            else:
                msg = f"Re-entry — all {len(already_checked)} ticket(s) already checked in. Ticket is valid.{refunded_note}"
                status = "reentry"

            result = {
                "status": status,
                "msg": msg,
                "is_group": True,
                "user_name": user.full_name or user.username if user else "Unknown",
                "user_email": user.email if user else "",
                "event_name": event_name,
                "newly_checked": newly_checked,
                "already_checked": already_checked,
                "refunded_count": refunded_count,
            }
    else:
        query = db.query(Booking).filter(Booking.ticket_id == ticket_id, Booking.payment_status == "paid")
        if event_id_raw:
            try:
                query = query.filter(Booking.event_id == int(event_id_raw))
            except ValueError:
                pass
        booking = query.first()

        if not booking:
            result = {"status": "error", "msg": f"Ticket '{ticket_id}' not found or not valid."}
        elif booking.checked_in:
            user = db.query(User).get(booking.user_id)
            seat = db.query(Seat).get(booking.seat_id)
            event = db.query(Event).get(booking.event_id) if booking.event_id else None
            time_str = booking.checked_in_at.strftime('%I:%M %p') if booking.checked_in_at else 'earlier'
            result = {
                "status": "reentry",
                "msg": f"Re-entry — ticket valid. Originally checked in at {time_str}.",
                "user_name": user.full_name or user.username if user else "Unknown",
                "user_email": user.email if user else "",
                "seat_label": seat.label if seat else "",
                "event_name": event.name if event else "",
                "ticket_id": ticket_id,
            }
        else:
            booking.checked_in = True
            booking.checked_in_at = now_ist()
            user = db.query(User).get(booking.user_id)
            seat = db.query(Seat).get(booking.seat_id)
            event = db.query(Event).get(booking.event_id) if booking.event_id else None
            event_name = event.name if event else "unknown"
            log_activity(db, category="admin", action="checkin", description=f"Checked in ticket '{ticket_id}' (seat {seat.label if seat else '?'}) for '{event_name}'", request=request, user_id=admin.id, target_type="booking", target_id=booking.id)
            db.commit()
            result = {
                "status": "success",
                "msg": "Check-in successful!",
                "user_name": user.full_name or user.username if user else "Unknown",
                "user_email": user.email if user else "",
                "seat_label": seat.label if seat else "",
                "event_name": event_name,
                "ticket_id": ticket_id,
            }

    stats = None
    if event_id_raw:
        try:
            eid = int(event_id_raw)
            total_booked = db.query(func.count(Booking.id)).filter(Booking.event_id == eid, Booking.payment_status == "paid").scalar()
            checked_in_count = db.query(func.count(Booking.id)).filter(Booking.event_id == eid, Booking.payment_status == "paid", Booking.checked_in == True).scalar()
            stats = {"total": total_booked, "checked_in": checked_in_count}
        except ValueError:
            pass

    return templates.TemplateResponse(
        "admin/checkin.html",
        _admin_ctx(request, active_page="checkin", events_list=events_list, result=result, stats=stats, selected_event=event_id_raw),
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
        event = db.query(Event).get(w.event_id) if w.event_id else None
        enriched.append({"entry": w, "user": u, "event": event})

    return templates.TemplateResponse(
        "admin/waitlist.html",
        _admin_ctx(
            request,
            active_page="waitlist",
            entries=enriched,
        ),
    )


@router.post("/waitlist/{entry_id}/delete")
def waitlist_delete(request: Request, entry_id: int, db: Session = Depends(get_db)):
    admin = _require_admin(request, db)
    if not admin:
        return RedirectResponse("/auth/login", status_code=303)
    entry = db.query(Waitlist).get(entry_id)
    if entry:
        log_activity(db, category="admin", action="delete", description=f"Removed waitlist entry #{entry_id}", request=request, user_id=admin.id, target_type="waitlist", target_id=entry_id)
        db.delete(entry)
        db.commit()
        flash(request, "Waitlist entry removed.", "success")
    return RedirectResponse("/admin/waitlist", status_code=303)


# ─── Users ───

@router.get("/users")
def users_list(request: Request, db: Session = Depends(get_db), q: str = Query("", alias="q")):
    admin = _require_admin(request, db)
    if not admin:
        return RedirectResponse("/auth/login", status_code=303)
    query = db.query(User)
    if q.strip():
        like = f"%{q.strip()}%"
        query = query.filter(
            User.username.ilike(like)
            | User.email.ilike(like)
            | User.full_name.ilike(like)
            | User.college.ilike(like)
        )
    users = query.order_by(User.created_at.desc()).all()
    colleges = db.query(College).filter(College.is_active == True).order_by(College.name).all()
    return templates.TemplateResponse(
        "admin/users.html",
        _admin_ctx(request, active_page="users", users=users, q=q, colleges=colleges),
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
async def toggle_supervisor(request: Request, user_id: int, db: Session = Depends(get_db)):
    admin = _require_admin(request, db)
    if not admin:
        return RedirectResponse("/auth/login", status_code=303)
    u = db.query(User).get(user_id)
    if not u or u.id == admin.id:
        return RedirectResponse("/admin/users", status_code=303)

    if u.is_supervisor:
        u.is_supervisor = False
        u.supervisor_college_id = None
        log_activity(db, category="admin", action="role_change", description=f"Removed supervisor role from {u.username}", request=request, user_id=admin.id, target_type="user", target_id=user_id)
        db.commit()
        flash(request, f"{u.username} is no longer a supervisor.", "success")
    else:
        form = await request.form()
        college_id_raw = form.get("college_id", "")
        if not college_id_raw:
            flash(request, "Please select a college to assign the supervisor to.", "danger")
            return RedirectResponse("/admin/users", status_code=303)
        try:
            cid = int(college_id_raw)
        except ValueError:
            flash(request, "Invalid college selection.", "danger")
            return RedirectResponse("/admin/users", status_code=303)
        college = db.query(College).get(cid)
        if not college:
            flash(request, "Selected college not found.", "danger")
            return RedirectResponse("/admin/users", status_code=303)
        u.is_supervisor = True
        u.supervisor_college_id = cid
        log_activity(db, category="admin", action="role_change", description=f"Made {u.username} supervisor at {college.name}", request=request, user_id=admin.id, target_type="user", target_id=user_id)
        db.commit()
        flash(request, f"{u.username} is now a supervisor at {college.name}.", "success")
    return RedirectResponse("/admin/users", status_code=303)


# ─── Schedule (Admin) ───

@router.get("/schedule")
def admin_schedule(
    request: Request,
    db: Session = Depends(get_db),
    college_id: str = Query("", alias="college_id"),
    auditorium_id: str = Query("", alias="auditorium_id"),
):
    admin = _require_admin(request, db)
    if not admin:
        return RedirectResponse("/auth/login", status_code=303)

    query = db.query(Event).filter(
        Event.status.in_(["published", "completed"])
    )
    if auditorium_id:
        try:
            query = query.filter(Event.auditorium_id == int(auditorium_id))
        except ValueError:
            pass
    elif college_id:
        try:
            aud_ids = [a.id for a in db.query(Auditorium.id).filter(Auditorium.college_id == int(college_id)).all()]
            if aud_ids:
                query = query.filter(Event.auditorium_id.in_(aud_ids))
            else:
                query = query.filter(False)
        except ValueError:
            pass

    events = query.order_by(Event.start_date).all()

    grouped = defaultdict(list)
    for ev in events:
        aud = db.query(Auditorium).get(ev.auditorium_id) if ev.auditorium_id else None
        date_key = ev.start_date.strftime("%Y-%m-%d") if ev.start_date else "TBD"
        grouped[date_key].append({"event": ev, "auditorium": aud})

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


# ---------------------------------------------------------------------------
# Platform Settings
# ---------------------------------------------------------------------------

_SETTING_KEYS = [
    "platform_logo_url", "company_name", "company_address",
    "company_email", "company_phone", "company_gstin", "company_pan", "gst_rate",
]


def _load_settings(db: Session) -> dict:
    from app.config import settings as cfg
    defaults = {
        "platform_logo_url": "",
        "company_name": cfg.company_name,
        "company_address": cfg.company_address,
        "company_email": cfg.company_email,
        "company_phone": cfg.company_phone,
        "company_gstin": cfg.company_gstin,
        "company_pan": cfg.company_pan,
        "gst_rate": str(cfg.gst_rate),
    }
    rows = db.query(SiteSetting).all()
    for row in rows:
        defaults[row.key] = row.value or ""
    return defaults


class _SettingsProxy:
    def __init__(self, d: dict):
        self._d = d

    def __getattr__(self, key):
        return self._d.get(key, "")


@router.get("/settings")
def settings_page(request: Request, db: Session = Depends(get_db)):
    admin = _require_admin(request, db)
    if not admin:
        return RedirectResponse("/auth/login?next=/admin/settings", status_code=303)
    s = _SettingsProxy(_load_settings(db))
    return templates.TemplateResponse(
        "admin/settings.html",
        _admin_ctx(request, active_page="settings", s=s),
    )


@router.post("/settings")
async def settings_update(request: Request, db: Session = Depends(get_db)):
    admin = _require_admin(request, db)
    if not admin:
        return RedirectResponse("/auth/login?next=/admin/settings", status_code=303)
    form = await request.form()
    for key in _SETTING_KEYS:
        val = form.get(key, "").strip()
        row = db.query(SiteSetting).filter(SiteSetting.key == key).first()
        if row:
            row.value = val
        else:
            db.add(SiteSetting(key=key, value=val))
    db.commit()
    flash(request, "Settings saved.", "success")
    return RedirectResponse("/admin/settings", status_code=303)


# ---------------------------------------------------------------------------
# Events
# ---------------------------------------------------------------------------

@router.get("/events")
def events_list(request: Request, db: Session = Depends(get_db)):
    admin = _require_admin(request, db)
    if not admin:
        return RedirectResponse("/auth/login", status_code=303)
    events = db.query(Event).order_by(Event.created_at.desc()).all()
    enriched = []
    for ev in events:
        session_count = len(ev.sessions) if ev.sessions else 0
        booking_count = db.query(func.count(Booking.id)).filter(
            Booking.event_id == ev.id, Booking.payment_status == "paid"
        ).scalar() or 0
        aud = db.query(Auditorium).get(ev.auditorium_id) if ev.auditorium_id else None
        enriched.append({"event": ev, "session_count": session_count, "bookings": booking_count, "auditorium": aud})
    return templates.TemplateResponse(
        "admin/events.html",
        _admin_ctx(request, active_page="events", events=enriched),
    )


@router.get("/events/new")
def event_new_form(request: Request, db: Session = Depends(get_db)):
    admin = _require_admin(request, db)
    if not admin:
        return RedirectResponse("/auth/login", status_code=303)
    colleges = db.query(College).order_by(College.name).all()
    auditoriums = db.query(Auditorium).order_by(Auditorium.name).all()
    return templates.TemplateResponse(
        "admin/event_form.html",
        _admin_ctx(request, active_page="events", event=None, colleges=colleges, auditoriums=auditoriums),
    )


@router.post("/events/new")
async def event_create(request: Request, db: Session = Depends(get_db)):
    admin = _require_admin(request, db)
    if not admin:
        return RedirectResponse("/auth/login", status_code=303)
    form = await _form(request)
    aud_raw = form.get("auditorium_id", "")
    start_date_raw = form.get("start_date", "")
    end_date_raw = form.get("end_date", "")
    ev = Event(
        name=form.get("name", "").strip(),
        description=form.get("description", "").strip() or None,
        banner_url=form.get("banner_url", "").strip() or None,
        college_id=int(form.get("college_id")) if form.get("college_id") else None,
        auditorium_id=int(aud_raw) if aud_raw and aud_raw.strip().isdigit() else None,
        start_date=date.fromisoformat(start_date_raw) if start_date_raw else None,
        end_date=date.fromisoformat(end_date_raw) if end_date_raw else None,
        price=float(form.get("price", 0) or 0),
        price_vip=float(form["price_vip"]) if form.get("price_vip", "").strip() else None,
        price_accessible=float(form["price_accessible"]) if form.get("price_accessible", "").strip() else None,
        processing_fee_pct=float(form["processing_fee_pct"]) if form.get("processing_fee_pct", "").strip() else None,
        status=form.get("status", "draft"),
    )
    db.add(ev)
    db.flush()

    sess_indices = form.getlist("sess_idx")
    for idx in sess_indices:
        title = form.get(f"sess_title_{idx}", "").strip()
        if not title:
            continue
        start_str = form.get(f"sess_start_{idx}", "")
        start_time = None
        if start_str:
            try:
                start_time = datetime.fromisoformat(start_str)
            except ValueError:
                pass
        sess = SessionModel(
            event_id=ev.id,
            title=title,
            speaker_name=form.get(f"sess_speaker_{idx}", "").strip(),
            description=form.get(f"sess_desc_{idx}", "").strip() or None,
            duration_minutes=int(form.get(f"sess_duration_{idx}", 30) or 30),
            start_time=start_time,
            order=int(form.get(f"sess_order_{idx}", 0) or 0),
        )
        db.add(sess)

    log_activity(db, category="admin", action="create", description=f"Created event '{ev.name}'", request=request, user_id=admin.id, target_type="event", target_id=ev.id)
    db.commit()
    sess_count = len([i for i in sess_indices if form.get(f"sess_title_{i}", "").strip()])
    msg = f"Event '{ev.name}' created"
    if sess_count:
        msg += f" with {sess_count} session(s)"
    flash(request, msg + ".", "success")
    return RedirectResponse("/admin/events", status_code=303)


@router.get("/events/{event_id}/edit")
def event_edit_form(request: Request, event_id: int, db: Session = Depends(get_db)):
    admin = _require_admin(request, db)
    if not admin:
        return RedirectResponse("/auth/login", status_code=303)
    ev = db.query(Event).get(event_id)
    if not ev:
        flash(request, "Event not found.", "danger")
        return RedirectResponse("/admin/events", status_code=303)
    colleges = db.query(College).order_by(College.name).all()
    auditoriums = db.query(Auditorium).order_by(Auditorium.name).all()
    sessions = db.query(SessionModel).filter(SessionModel.event_id == event_id).order_by(SessionModel.order, SessionModel.start_time).all()
    coupons = db.query(Coupon).filter(Coupon.event_id == event_id).order_by(Coupon.created_at.desc()).all()
    return templates.TemplateResponse(
        "admin/event_form.html",
        _admin_ctx(request, active_page="events", event=ev, colleges=colleges, auditoriums=auditoriums,
                   event_sessions=sessions, event_coupons=coupons),
    )


@router.post("/events/{event_id}/edit")
async def event_update(request: Request, event_id: int, db: Session = Depends(get_db)):
    admin = _require_admin(request, db)
    if not admin:
        return RedirectResponse("/auth/login", status_code=303)
    ev = db.query(Event).get(event_id)
    if not ev:
        flash(request, "Event not found.", "danger")
        return RedirectResponse("/admin/events", status_code=303)
    form = await _form(request)
    aud_raw = form.get("auditorium_id", "")
    start_date_raw = form.get("start_date", "")
    end_date_raw = form.get("end_date", "")
    ev.name = form.get("name", "").strip()
    ev.description = form.get("description", "").strip() or None
    ev.banner_url = form.get("banner_url", "").strip() or None
    ev.college_id = int(form.get("college_id")) if form.get("college_id") else None
    ev.auditorium_id = int(aud_raw) if aud_raw and aud_raw.strip().isdigit() else ev.auditorium_id
    if start_date_raw:
        ev.start_date = date.fromisoformat(start_date_raw)
    if end_date_raw:
        ev.end_date = date.fromisoformat(end_date_raw)
    else:
        ev.end_date = None
    ev.price = float(form.get("price", ev.price or 0) or 0)
    ev.price_vip = float(form["price_vip"]) if form.get("price_vip", "").strip() else None
    ev.price_accessible = float(form["price_accessible"]) if form.get("price_accessible", "").strip() else None
    ev.processing_fee_pct = float(form["processing_fee_pct"]) if form.get("processing_fee_pct", "").strip() else None
    ev.status = form.get("status", "draft")

    ev.cert_title = form.get("cert_title", "").strip() or ev.cert_title
    ev.cert_subtitle = form.get("cert_subtitle", "").strip() or ev.cert_subtitle
    ev.cert_footer = form.get("cert_footer", "").strip() or ev.cert_footer
    ev.cert_signer_name = form.get("cert_signer_name", "").strip() or ev.cert_signer_name
    ev.cert_signer_designation = form.get("cert_signer_designation", "").strip() or ev.cert_signer_designation
    ev.cert_signature_url = form.get("cert_signature_url", "").strip() or ev.cert_signature_url
    ev.cert_logo_url = form.get("cert_logo_url", "").strip() or ev.cert_logo_url
    ev.cert_bg_url = form.get("cert_bg_url", "").strip() or ev.cert_bg_url
    ev.cert_color_scheme = form.get("cert_color_scheme", "").strip() or ev.cert_color_scheme
    ev.cert_style = form.get("cert_style", "").strip() or ev.cert_style

    sess_indices = form.getlist("sess_idx")
    new_sess = 0
    for idx in sess_indices:
        title = form.get(f"sess_title_{idx}", "").strip()
        if not title:
            continue
        start_str = form.get(f"sess_start_{idx}", "")
        start_time = None
        if start_str:
            try:
                start_time = datetime.fromisoformat(start_str)
            except ValueError:
                pass
        sess = SessionModel(
            event_id=ev.id,
            title=title,
            speaker_name=form.get(f"sess_speaker_{idx}", "").strip(),
            description=form.get(f"sess_desc_{idx}", "").strip() or None,
            duration_minutes=int(form.get(f"sess_duration_{idx}", 30) or 30),
            start_time=start_time,
            order=int(form.get(f"sess_order_{idx}", 0) or 0),
        )
        db.add(sess)
        new_sess += 1

    log_activity(db, category="admin", action="update", description=f"Updated event '{ev.name}'", request=request, user_id=admin.id, target_type="event", target_id=ev.id)
    db.commit()
    msg = f"Event '{ev.name}' updated"
    if new_sess:
        msg += f" — {new_sess} new session(s) added"
    flash(request, msg + ".", "success")
    return RedirectResponse(f"/admin/events/{ev.id}/edit", status_code=303)


@router.post("/events/{event_id}/delete")
def event_delete(request: Request, event_id: int, db: Session = Depends(get_db)):
    admin = _require_admin(request, db)
    if not admin:
        return RedirectResponse("/auth/login", status_code=303)
    ev = db.query(Event).get(event_id)
    if ev:
        paid_count = db.query(func.count(Booking.id)).filter(
            Booking.event_id == ev.id, Booking.payment_status == "paid"
        ).scalar()
        if paid_count > 0:
            flash(request, f"Cannot delete — this event has {paid_count} paid booking(s). Cancel or refund them first.", "danger")
            return RedirectResponse("/admin/events", status_code=303)
        log_activity(db, category="admin", action="delete", description=f"Deleted event '{ev.name}'", request=request, user_id=admin.id, target_type="event", target_id=ev.id)
        db.delete(ev)
        db.commit()
        flash(request, f"Event '{ev.name}' deleted.", "success")
    return RedirectResponse("/admin/events", status_code=303)


# ---------------------------------------------------------------------------
# Coupon CRUD (event-level)
# ---------------------------------------------------------------------------

@router.get("/events/{event_id}/coupons/new")
def coupon_new_form(request: Request, event_id: int, db: Session = Depends(get_db)):
    admin = _require_admin(request, db)
    if not admin:
        return RedirectResponse("/auth/login", status_code=303)
    ev = db.query(Event).get(event_id)
    if not ev:
        flash(request, "Event not found.", "danger")
        return RedirectResponse("/admin/events", status_code=303)
    return templates.TemplateResponse(
        "admin/coupon_form.html",
        _admin_ctx(request, active_page="events", event=ev, coupon=None),
    )


@router.post("/events/{event_id}/coupons/new")
async def coupon_create(request: Request, event_id: int, db: Session = Depends(get_db)):
    admin = _require_admin(request, db)
    if not admin:
        return RedirectResponse("/auth/login", status_code=303)
    form = await _form(request)
    code = form.get("code", "").strip().upper()
    if not code:
        flash(request, "Coupon code is required.", "danger")
        return RedirectResponse(f"/admin/events/{event_id}/coupons/new", status_code=303)
    existing = db.query(Coupon).filter(Coupon.code == code).first()
    if existing:
        flash(request, f"Coupon code '{code}' already exists.", "danger")
        return RedirectResponse(f"/admin/events/{event_id}/coupons/new", status_code=303)
    valid_from_raw = form.get("valid_from", "")
    valid_until_raw = form.get("valid_until", "")
    coupon = Coupon(
        code=code,
        event_id=event_id,
        discount_pct=float(form["discount_pct"]) if form.get("discount_pct", "").strip() else None,
        discount_amount=float(form["discount_amount"]) if form.get("discount_amount", "").strip() else None,
        max_uses=int(form["max_uses"]) if form.get("max_uses", "").strip() else None,
        valid_from=datetime.fromisoformat(valid_from_raw) if valid_from_raw else None,
        valid_until=datetime.fromisoformat(valid_until_raw) if valid_until_raw else None,
        is_active=form.get("is_active") == "on",
    )
    db.add(coupon)
    log_activity(db, category="admin", action="create", description=f"Created coupon '{code}' for event #{event_id}", request=request, user_id=admin.id, target_type="coupon", target_id=coupon.id)
    db.commit()
    flash(request, f"Coupon '{code}' created.", "success")
    return RedirectResponse(f"/admin/events/{event_id}/edit", status_code=303)


@router.get("/events/{event_id}/coupons/{coupon_id}/edit")
def coupon_edit_form(request: Request, event_id: int, coupon_id: int, db: Session = Depends(get_db)):
    admin = _require_admin(request, db)
    if not admin:
        return RedirectResponse("/auth/login", status_code=303)
    ev = db.query(Event).get(event_id)
    coupon = db.query(Coupon).get(coupon_id)
    if not ev or not coupon:
        flash(request, "Not found.", "danger")
        return RedirectResponse("/admin/events", status_code=303)
    return templates.TemplateResponse(
        "admin/coupon_form.html",
        _admin_ctx(request, active_page="events", event=ev, coupon=coupon),
    )


@router.post("/events/{event_id}/coupons/{coupon_id}/edit")
async def coupon_update(request: Request, event_id: int, coupon_id: int, db: Session = Depends(get_db)):
    admin = _require_admin(request, db)
    if not admin:
        return RedirectResponse("/auth/login", status_code=303)
    coupon = db.query(Coupon).get(coupon_id)
    if not coupon:
        flash(request, "Coupon not found.", "danger")
        return RedirectResponse(f"/admin/events/{event_id}/edit", status_code=303)
    form = await _form(request)
    code = form.get("code", "").strip().upper()
    if code and code != coupon.code:
        dup = db.query(Coupon).filter(Coupon.code == code, Coupon.id != coupon_id).first()
        if dup:
            flash(request, f"Coupon code '{code}' already exists.", "danger")
            return RedirectResponse(f"/admin/events/{event_id}/coupons/{coupon_id}/edit", status_code=303)
        coupon.code = code
    coupon.discount_pct = float(form["discount_pct"]) if form.get("discount_pct", "").strip() else None
    coupon.discount_amount = float(form["discount_amount"]) if form.get("discount_amount", "").strip() else None
    coupon.max_uses = int(form["max_uses"]) if form.get("max_uses", "").strip() else None
    valid_from_raw = form.get("valid_from", "")
    valid_until_raw = form.get("valid_until", "")
    coupon.valid_from = datetime.fromisoformat(valid_from_raw) if valid_from_raw else None
    coupon.valid_until = datetime.fromisoformat(valid_until_raw) if valid_until_raw else None
    coupon.is_active = form.get("is_active") == "on"
    log_activity(db, category="admin", action="update", description=f"Updated coupon '{coupon.code}'", request=request, user_id=admin.id, target_type="coupon", target_id=coupon.id)
    db.commit()
    flash(request, f"Coupon '{coupon.code}' updated.", "success")
    return RedirectResponse(f"/admin/events/{event_id}/edit", status_code=303)


@router.post("/events/{event_id}/coupons/{coupon_id}/delete")
def coupon_delete(request: Request, event_id: int, coupon_id: int, db: Session = Depends(get_db)):
    admin = _require_admin(request, db)
    if not admin:
        return RedirectResponse("/auth/login", status_code=303)
    coupon = db.query(Coupon).get(coupon_id)
    if coupon:
        log_activity(db, category="admin", action="delete", description=f"Deleted coupon '{coupon.code}'", request=request, user_id=admin.id, target_type="coupon", target_id=coupon.id)
        db.delete(coupon)
        db.commit()
        flash(request, "Coupon deleted.", "success")
    return RedirectResponse(f"/admin/events/{event_id}/edit", status_code=303)


# ---------------------------------------------------------------------------
# Feedback Management
# ---------------------------------------------------------------------------

@router.get("/feedback")
def feedback_list(
    request: Request,
    db: Session = Depends(get_db),
    rating_filter: str = Query("", alias="rating"),
    featured_filter: str = Query("", alias="featured"),
):
    admin = _require_admin(request, db)
    if not admin:
        return RedirectResponse("/auth/login", status_code=303)

    query = db.query(Feedback)
    if rating_filter:
        try:
            query = query.filter(Feedback.rating == int(rating_filter))
        except ValueError:
            pass
    if featured_filter == "yes":
        query = query.filter(Feedback.is_featured == True)
    elif featured_filter == "no":
        query = query.filter(Feedback.is_featured == False)

    feedback_items = query.order_by(Feedback.created_at.desc()).all()
    enriched = []
    for fb in feedback_items:
        user = db.query(User).get(fb.user_id)
        event = db.query(Event).get(fb.event_id) if fb.event_id else None
        enriched.append({"feedback": fb, "user": user, "event": event})

    return templates.TemplateResponse(
        "admin/feedback.html",
        _admin_ctx(
            request, active_page="feedback",
            feedback_items=enriched,
            rating_filter=rating_filter,
            featured_filter=featured_filter,
        ),
    )


@router.post("/feedback/{feedback_id}/toggle-featured")
def feedback_toggle_featured(request: Request, feedback_id: int, db: Session = Depends(get_db)):
    admin = _require_admin(request, db)
    if not admin:
        return RedirectResponse("/auth/login", status_code=303)
    fb = db.query(Feedback).get(feedback_id)
    if fb:
        fb.is_featured = not fb.is_featured
        status = "featured" if fb.is_featured else "unfeatured"
        log_activity(db, category="admin", action="update", description=f"Toggled feedback #{fb.id} to {status}", request=request, user_id=admin.id, target_type="feedback", target_id=fb.id)
        db.commit()
        flash(request, f"Feedback #{fb.id} is now {status}.", "success")
    return RedirectResponse("/admin/feedback", status_code=303)


# ─── Newsletter Campaigns ───


@router.get("/newsletters")
def newsletter_list(request: Request, db: Session = Depends(get_db)):
    admin = _require_admin(request, db)
    if not admin:
        return RedirectResponse("/auth/login", status_code=303)
    campaigns = db.query(Newsletter).order_by(Newsletter.created_at.desc()).all()
    subscriber_count = db.query(func.count(NewsletterSubscriber.id)).scalar() or 0
    return templates.TemplateResponse(
        "admin/newsletters.html",
        _admin_ctx(request, active_page="newsletters", campaigns=campaigns, subscriber_count=subscriber_count),
    )


@router.get("/newsletters/new")
def newsletter_new_form(request: Request, db: Session = Depends(get_db)):
    admin = _require_admin(request, db)
    if not admin:
        return RedirectResponse("/auth/login", status_code=303)
    subscriber_count = db.query(func.count(NewsletterSubscriber.id)).scalar() or 0
    return templates.TemplateResponse(
        "admin/newsletter_compose.html",
        _admin_ctx(request, active_page="newsletters", newsletter=None, subscriber_count=subscriber_count),
    )


@router.post("/newsletters/new")
async def newsletter_new_save(request: Request, db: Session = Depends(get_db)):
    admin = _require_admin(request, db)
    if not admin:
        return RedirectResponse("/auth/login", status_code=303)
    form = await _form(request)
    nl = Newsletter(
        subject=form.get("subject", "").strip(),
        body_html=form.get("body_html", ""),
        status="draft",
    )
    db.add(nl)
    db.flush()
    log_activity(db, category="admin", action="create", description=f"Created newsletter draft '{nl.subject}'", request=request, user_id=admin.id, target_type="newsletter", target_id=nl.id)
    db.commit()
    flash(request, "Newsletter draft saved.", "success")
    return RedirectResponse(f"/admin/newsletters/{nl.id}/edit", status_code=303)


@router.get("/newsletters/{newsletter_id}/edit")
def newsletter_edit_form(request: Request, newsletter_id: int, db: Session = Depends(get_db)):
    admin = _require_admin(request, db)
    if not admin:
        return RedirectResponse("/auth/login", status_code=303)
    nl = db.query(Newsletter).get(newsletter_id)
    if not nl:
        flash(request, "Newsletter not found.", "danger")
        return RedirectResponse("/admin/newsletters", status_code=303)
    subscriber_count = db.query(func.count(NewsletterSubscriber.id)).scalar() or 0
    return templates.TemplateResponse(
        "admin/newsletter_compose.html",
        _admin_ctx(request, active_page="newsletters", newsletter=nl, subscriber_count=subscriber_count),
    )


@router.post("/newsletters/{newsletter_id}/edit")
async def newsletter_edit_save(request: Request, newsletter_id: int, db: Session = Depends(get_db)):
    admin = _require_admin(request, db)
    if not admin:
        return RedirectResponse("/auth/login", status_code=303)
    nl = db.query(Newsletter).get(newsletter_id)
    if not nl:
        flash(request, "Newsletter not found.", "danger")
        return RedirectResponse("/admin/newsletters", status_code=303)
    if nl.status != "draft":
        flash(request, "Only draft newsletters can be edited.", "warning")
        return RedirectResponse("/admin/newsletters", status_code=303)
    form = await _form(request)
    nl.subject = form.get("subject", "").strip()
    nl.body_html = form.get("body_html", "")
    log_activity(db, category="admin", action="update", description=f"Updated newsletter draft '{nl.subject}'", request=request, user_id=admin.id, target_type="newsletter", target_id=nl.id)
    db.commit()
    flash(request, "Newsletter draft updated.", "success")
    return RedirectResponse(f"/admin/newsletters/{nl.id}/edit", status_code=303)


@router.post("/newsletters/{newsletter_id}/delete")
def newsletter_delete(request: Request, newsletter_id: int, db: Session = Depends(get_db)):
    admin = _require_admin(request, db)
    if not admin:
        return RedirectResponse("/auth/login", status_code=303)
    nl = db.query(Newsletter).get(newsletter_id)
    if not nl:
        flash(request, "Newsletter not found.", "danger")
        return RedirectResponse("/admin/newsletters", status_code=303)
    if nl.status != "draft":
        flash(request, "Only draft newsletters can be deleted.", "warning")
        return RedirectResponse("/admin/newsletters", status_code=303)
    log_activity(db, category="admin", action="delete", description=f"Deleted newsletter draft '{nl.subject}'", request=request, user_id=admin.id, target_type="newsletter", target_id=nl.id)
    db.delete(nl)
    db.commit()
    flash(request, "Newsletter draft deleted.", "success")
    return RedirectResponse("/admin/newsletters", status_code=303)


@router.post("/newsletters/{newsletter_id}/send")
def newsletter_send(request: Request, newsletter_id: int, db: Session = Depends(get_db)):
    admin = _require_admin(request, db)
    if not admin:
        return RedirectResponse("/auth/login", status_code=303)
    nl = db.query(Newsletter).get(newsletter_id)
    if not nl:
        flash(request, "Newsletter not found.", "danger")
        return RedirectResponse("/admin/newsletters", status_code=303)
    if nl.status != "draft":
        flash(request, "This newsletter has already been sent or is currently sending.", "warning")
        return RedirectResponse("/admin/newsletters", status_code=303)
    subscriber_count = db.query(func.count(NewsletterSubscriber.id)).scalar() or 0
    if subscriber_count == 0:
        flash(request, "No subscribers to send to.", "warning")
        return RedirectResponse(f"/admin/newsletters/{nl.id}/edit", status_code=303)
    nl.status = "sending"
    nl.total_recipients = subscriber_count
    nl.sent_count = 0
    nl.failed_count = 0
    db.commit()

    from app.services.email import send_newsletter_campaign
    send_newsletter_campaign(nl.id)

    log_activity(db, category="admin", action="send", description=f"Started sending newsletter '{nl.subject}' to {subscriber_count} subscribers", request=request, user_id=admin.id, target_type="newsletter", target_id=nl.id)
    db.commit()
    flash(request, f"Newsletter is being sent to {subscriber_count} subscriber(s).", "success")
    return RedirectResponse("/admin/newsletters", status_code=303)


@router.get("/newsletters/{newsletter_id}/status")
def newsletter_status(request: Request, newsletter_id: int, db: Session = Depends(get_db)):
    admin = _require_admin(request, db)
    if not admin:
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    nl = db.query(Newsletter).get(newsletter_id)
    if not nl:
        return JSONResponse({"error": "not found"}, status_code=404)
    return JSONResponse({
        "status": nl.status,
        "total_recipients": nl.total_recipients,
        "sent_count": nl.sent_count,
        "failed_count": nl.failed_count,
    })


@router.post("/newsletters/preview")
async def newsletter_preview(request: Request, db: Session = Depends(get_db)):
    admin = _require_admin(request, db)
    if not admin:
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    form = await _form(request)
    body_html = form.get("body_html", "")
    from app.services.email import wrap_newsletter_html
    full_html = wrap_newsletter_html(body_html, "#")
    from fastapi.responses import HTMLResponse
    return HTMLResponse(content=full_html)


@router.post("/newsletters/upload-image")
async def newsletter_upload_image(request: Request, db: Session = Depends(get_db)):
    import os
    import uuid
    admin = _require_admin(request, db)
    if not admin:
        return JSONResponse({"error": "unauthorized"}, status_code=401)

    form = await request.form()
    file = form.get("image")
    if not file or not hasattr(file, "filename"):
        return JSONResponse({"error": "No file uploaded"}, status_code=400)

    allowed = {"image/jpeg", "image/png", "image/gif", "image/webp"}
    if file.content_type not in allowed:
        return JSONResponse({"error": "Invalid file type. Allowed: JPEG, PNG, GIF, WebP"}, status_code=400)

    content = await file.read()
    if len(content) > 5 * 1024 * 1024:
        return JSONResponse({"error": "File too large (max 5MB)"}, status_code=400)

    ext_map = {"image/jpeg": ".jpg", "image/png": ".png", "image/gif": ".gif", "image/webp": ".webp"}
    ext = ext_map.get(file.content_type, ".jpg")
    filename = f"{uuid.uuid4().hex}{ext}"

    upload_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static", "uploads", "newsletters")
    os.makedirs(upload_dir, exist_ok=True)
    filepath = os.path.join(upload_dir, filename)

    with open(filepath, "wb") as f:
        f.write(content)

    url = f"/static/uploads/newsletters/{filename}"
    return JSONResponse({"url": url})
