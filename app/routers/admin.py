import csv
import io
import json
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import RedirectResponse, StreamingResponse
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.dependencies import flash, get_db, template_ctx, templates
from app.models.auditorium import Auditorium
from app.models.booking import Booking
from app.models.city import City
from app.models.college import College
from app.models.seat import Seat
from app.models.session import LectureSession
from app.models.speaker import Speaker
from app.models.agenda import AgendaItem
from app.models.testimonial import Testimonial
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
    total_revenue = db.query(func.sum(Booking.amount_paid)).filter(Booking.payment_status == "paid").scalar() or 0

    now = datetime.now(timezone.utc)
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
        db.commit()
        status = "active" if city.is_active else "inactive"
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


# ─── Speakers ───

@router.get("/speakers")
def speakers_list(request: Request, db: Session = Depends(get_db)):
    admin = _require_admin(request, db)
    if not admin:
        return RedirectResponse("/auth/login", status_code=303)
    speakers = db.query(Speaker).order_by(Speaker.name).all()
    return templates.TemplateResponse(
        "admin/speakers.html",
        _admin_ctx(request, active_page="speakers", speakers=speakers),
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
        db.delete(sp)
        db.commit()
        flash(request, f"Speaker '{sp.name}' deleted.", "success")
    return RedirectResponse("/admin/speakers", status_code=303)


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
    speakers = db.query(Speaker).order_by(Speaker.name).all()
    cities = db.query(City).filter(City.is_active == True).order_by(City.name).all()
    return templates.TemplateResponse(
        "admin/session_form.html",
        _admin_ctx(request, active_page="sessions", lecture=None,
                   auditoriums=auditoriums, speakers=speakers, cities=cities, agenda_items=[]),
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
        status=form.get("status", "draft"),
    )
    db.add(session_obj)
    db.commit()
    db.refresh(session_obj)

    _save_agenda_items(db, form, session_obj.id)

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
    return templates.TemplateResponse(
        "admin/session_form.html",
        _admin_ctx(request, active_page="sessions", lecture=lecture,
                   auditoriums=auditoriums, speakers=speakers, cities=cities, agenda_items=agenda_items),
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
    lecture.status = form.get("status", lecture.status)

    _save_agenda_items(db, form, sess_id)

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
def bookings_list(
    request: Request,
    db: Session = Depends(get_db),
    q: str = Query("", alias="q"),
    status_filter: str = Query("", alias="status"),
    session_filter: str = Query("", alias="session_id"),
):
    admin = _require_admin(request, db)
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
def bookings_csv(request: Request, db: Session = Depends(get_db)):
    admin = _require_admin(request, db)
    if not admin:
        return RedirectResponse("/auth/login", status_code=303)

    bookings = db.query(Booking).filter(Booking.payment_status.in_(["paid", "hold", "refunded"])).order_by(Booking.booked_at.desc()).all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Booking Ref", "Ticket ID", "User", "Email", "Session", "Seat", "Status", "Amount Paid", "Refund", "Booked At", "Checked In"])
    for b in bookings:
        u = db.query(User).get(b.user_id)
        s = db.query(LectureSession).get(b.session_id)
        seat = db.query(Seat).get(b.seat_id)
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


# ─── Check-in ───

@router.get("/checkin")
def checkin_page(request: Request, db: Session = Depends(get_db)):
    admin = _require_admin(request, db)
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
    admin = _require_admin(request, db)
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
        booking.checked_in_at = datetime.now(timezone.utc)
        db.commit()
        user = db.query(User).get(booking.user_id)
        seat = db.query(Seat).get(booking.seat_id)
        lecture = db.query(LectureSession).get(booking.session_id)
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
