import calendar as _calendar
from collections import defaultdict
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.csrf import csrf_protection
from app.dependencies import AuthRedirect, flash, get_db, now_ist, template_ctx, templates
from app.services.activity_log import log_activity
from app.models.agenda import AgendaItem
from app.models.auditorium import Auditorium
from app.models.booking import Booking
from app.models.session import Session
from app.models.showing import Showing
from app.models.session_speaker import SessionSpeaker
from app.models.speaker import Speaker
from app.models.user import User

router = APIRouter(prefix="/speaker", tags=["speaker"], dependencies=[Depends(csrf_protection)])


def _require_speaker(request: Request, db: Session):
    user_id = request.session.get("user_id")
    if not user_id:
        raise AuthRedirect(f"/auth/login?next={request.url.path}")
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise AuthRedirect("/auth/login")
    speaker = db.query(Speaker).filter(Speaker.user_id == user.id).first()
    if not speaker:
        raise AuthRedirect("/")
    return user, speaker


def _speaker_ctx(request: Request, **kwargs):
    ctx = template_ctx(request)
    ctx.update(kwargs)
    return ctx


def _speaker_sessions(speaker, db):
    """Return all sessions linked to this speaker and computed stats."""
    session_ids_via_assignment = db.query(SessionSpeaker.session_id).filter(
        SessionSpeaker.speaker_id == speaker.id
    )
    session_ids_via_agenda = db.query(AgendaItem.session_id).filter(
        AgendaItem.speaker_id == speaker.id
    )
    sessions = (
        db.query(Session)
        .filter(
            or_(
                Session.speaker_id == speaker.id,
                Session.id.in_(session_ids_via_assignment),
                Session.id.in_(session_ids_via_agenda),
            )
        )
        .all()
    )
    now = now_ist()
    enriched = []
    for s in sessions:
        showing_ids = [sh.id for sh in s.showings]
        booking_count = (
            db.query(func.count(Booking.id)).filter(
                Booking.showing_id.in_(showing_ids), Booking.payment_status == "paid"
            ).scalar()
            if showing_ids else 0
        )
        next_showing = None
        for sh in sorted(s.showings, key=lambda x: x.start_time or now):
            if sh.start_time and sh.start_time > now:
                next_showing = sh
                break
        if not next_showing and s.showings:
            next_showing = max(s.showings, key=lambda x: x.start_time or now)
        enriched.append({
            "session": s,
            "bookings": booking_count,
            "showing": next_showing,
            "showings_count": len(s.showings),
        })

    total = len(sessions)
    upcoming = sum(
        1 for s in sessions
        if any(sh.start_time and sh.start_time > now and sh.status == "published" for sh in s.showings)
    )
    completed = sum(
        1 for s in sessions
        if any(sh.status == "completed" for sh in s.showings)
    )
    return sessions, enriched, total, upcoming, completed


@router.get("/")
def dashboard(request: Request, db: Session = Depends(get_db)):
    user, speaker = _require_speaker(request, db)
    _sessions, _enriched, total, upcoming, completed = _speaker_sessions(speaker, db)
    return templates.TemplateResponse(
        "speaker/dashboard.html",
        _speaker_ctx(
            request,
            speaker=speaker,
            total=total,
            upcoming=upcoming,
            completed=completed,
        ),
    )


@router.get("/sessions")
def sessions_list(request: Request, db: Session = Depends(get_db)):
    user, speaker = _require_speaker(request, db)
    _sessions, enriched, total, upcoming, completed = _speaker_sessions(speaker, db)
    return templates.TemplateResponse(
        "speaker/sessions.html",
        _speaker_ctx(
            request,
            speaker=speaker,
            sessions=enriched,
            total=total,
            upcoming=upcoming,
            completed=completed,
        ),
    )


@router.get("/schedule")
def schedule(
    request: Request,
    db: Session = Depends(get_db),
    view: str = Query("month", alias="view"),
    year: int | None = Query(None, alias="year"),
    month: int | None = Query(None, alias="month"),
    week: int | None = Query(None, alias="week"),
):
    user, speaker = _require_speaker(request, db)
    raw_sessions, _enriched, _t, _u, _c = _speaker_sessions(speaker, db)

    now = now_ist()
    if year is None:
        year = now.year
    if month is None:
        month = now.month
    if view not in ("month", "week"):
        view = "month"

    # Collect all showings across speaker's sessions
    all_showings = []
    for s in raw_sessions:
        for sh in s.showings:
            aud = db.query(Auditorium).get(sh.auditorium_id) if sh.auditorium_id else None
            college = aud.college if aud else None
            city = college.city if college else None
            showing_ids_for_count = [sh.id]
            bcount = (
                db.query(func.count(Booking.id))
                .filter(Booking.showing_id.in_(showing_ids_for_count), Booking.payment_status == "paid")
                .scalar()
            )
            duration = sh.duration_minutes or s.duration_minutes or 30
            end_time = sh.start_time + timedelta(minutes=duration) if sh.start_time else None
            all_showings.append({
                "id": sh.id,
                "session_id": s.id,
                "session_title": s.title,
                "start_time": sh.start_time,
                "end_time": end_time,
                "duration": duration,
                "status": sh.status,
                "auditorium": aud.name if aud else "TBD",
                "location": aud.location if aud else "",
                "college": college.name if college else "",
                "city": city.name if city else "",
                "price": float(sh.price),
                "bookings": bcount,
            })

    # Build calendar grid
    if view == "month":
        cal = _calendar.Calendar(firstweekday=0)  # Monday first
        month_days = cal.monthdatescalendar(year, month)

        # Map showings by date
        showings_by_date = defaultdict(list)
        for ev in all_showings:
            if ev["start_time"]:
                showings_by_date[ev["start_time"].date()].append(ev)

        weeks = []
        for week_dates in month_days:
            week_row = []
            for d in week_dates:
                week_row.append({
                    "date": d,
                    "day": d.day,
                    "is_today": d == now.date(),
                    "is_other_month": d.month != month,
                    "events": showings_by_date.get(d, []),
                })
            weeks.append(week_row)

        # Prev / next month
        if month == 1:
            prev_year, prev_month = year - 1, 12
        else:
            prev_year, prev_month = year, month - 1
        if month == 12:
            next_year, next_month = year + 1, 1
        else:
            next_year, next_month = year, month + 1

        month_label = datetime(year, month, 1).strftime("%B %Y")

        return templates.TemplateResponse(
            "speaker/schedule.html",
            _speaker_ctx(
                request,
                speaker=speaker,
                view=view,
                weeks=weeks,
                month_label=month_label,
                year=year,
                month_num=month,
                prev_year=prev_year,
                prev_month=prev_month,
                next_year=next_year,
                next_month=next_month,
                today=now.date(),
            ),
        )
    else:
        # Week view
        if week is not None:
            # week = ISO week number
            jan4 = datetime(year, 1, 4).date()
            start_of_year_week1 = jan4 - timedelta(days=jan4.weekday())
            week_start = start_of_year_week1 + timedelta(weeks=week - 1)
        else:
            week_start = now.date() - timedelta(days=now.weekday())
            week = week_start.isocalendar()[1]

        week_end = week_start + timedelta(days=6)
        week_dates = [week_start + timedelta(days=i) for i in range(7)]

        # Filter showings to this week
        showings_by_date = defaultdict(list)
        for ev in all_showings:
            if ev["start_time"]:
                d = ev["start_time"].date()
                if week_start <= d <= week_end:
                    showings_by_date[d].append(ev)

        days = []
        for d in week_dates:
            days.append({
                "date": d,
                "day": d.day,
                "weekday": d.strftime("%a"),
                "is_today": d == now.date(),
                "events": showings_by_date.get(d, []),
            })

        prev_week_start = week_start - timedelta(weeks=1)
        next_week_start = week_start + timedelta(weeks=1)
        prev_iso = prev_week_start.isocalendar()
        next_iso = next_week_start.isocalendar()

        week_label = f"{week_start.strftime('%b %d')} – {week_end.strftime('%b %d, %Y')}"

        return templates.TemplateResponse(
            "speaker/schedule.html",
            _speaker_ctx(
                request,
                speaker=speaker,
                view=view,
                days=days,
                week_label=week_label,
                week_num=week,
                year=year,
                prev_week=prev_iso[1],
                prev_week_year=prev_iso[0],
                next_week=next_iso[1],
                next_week_year=next_iso[0],
                today=now.date(),
            ),
        )


def _speaker_can_access_session(speaker, session_obj, db) -> bool:
    """Return True if speaker has any relation to this session."""
    if session_obj.speaker_id == speaker.id:
        return True
    in_assignments = db.query(SessionSpeaker).filter(
        SessionSpeaker.session_id == session_obj.id,
        SessionSpeaker.speaker_id == speaker.id,
    ).first()
    if in_assignments:
        return True
    in_agenda = db.query(AgendaItem).filter(
        AgendaItem.session_id == session_obj.id,
        AgendaItem.speaker_id == speaker.id,
    ).first()
    return in_agenda is not None


@router.get("/sessions/{session_id}/edit")
def session_edit(request: Request, session_id: int, db: Session = Depends(get_db)):
    user, speaker = _require_speaker(request, db)
    session_obj = db.query(Session).get(session_id)
    if not session_obj or not _speaker_can_access_session(speaker, session_obj, db):
        flash(request, "Session not found or access denied.", "danger")
        return RedirectResponse("/speaker/", status_code=303)
    is_primary = session_obj.speaker_id == speaker.id
    agenda_items = (
        db.query(AgendaItem)
        .filter(AgendaItem.session_id == session_id)
        .order_by(AgendaItem.order)
        .all()
    )
    all_speakers = db.query(Speaker).order_by(Speaker.name).all()
    showings = session_obj.showings
    return templates.TemplateResponse(
        "speaker/session_edit.html",
        _speaker_ctx(request, speaker=speaker, lecture=session_obj, session=session_obj, showings=showings, agenda_items=agenda_items, is_primary=is_primary, all_speakers=all_speakers),
    )


@router.post("/sessions/{session_id}/edit")
async def session_update(request: Request, session_id: int, db: Session = Depends(get_db)):
    user, speaker = _require_speaker(request, db)
    session_obj = db.query(Session).get(session_id)
    if not session_obj or not _speaker_can_access_session(speaker, session_obj, db):
        flash(request, "Session not found or access denied.", "danger")
        return RedirectResponse("/speaker/", status_code=303)

    is_primary = session_obj.speaker_id == speaker.id
    form = await request.form()

    if is_primary:
        session_obj.title = form.get("title", session_obj.title).strip()
        session_obj.description = form.get("description", "").strip()
        session_obj.banner_url = form.get("banner_url", "").strip() or None
        session_obj.duration_minutes = int(form.get("duration_minutes", 30))

        # Update first showing if it exists (schedule fields are on Showing)
        first_showing = db.query(Showing).filter(Showing.session_id == session_id).first()
        if first_showing:
            start_str = form.get("start_time", "")
            if start_str:
                try:
                    first_showing.start_time = datetime.fromisoformat(start_str)
                except ValueError:
                    pass
            dur_override = form.get("duration_minutes", "")
            if dur_override and dur_override.isdigit():
                first_showing.duration_minutes = int(dur_override)
            status_val = form.get("status", "")
            if status_val:
                first_showing.status = status_val

        # Primary speaker replaces all agenda items
        db.query(AgendaItem).filter(AgendaItem.session_id == session_id).delete()
        idx = 0
        while True:
            title = form.get(f"agenda_title_{idx}")
            if title is None:
                break
            title = title.strip()
            if title:
                spk_id_raw = form.get(f"agenda_speaker_id_{idx}", "").strip()
                spk_id = int(spk_id_raw) if spk_id_raw.isdigit() else None
                spk_obj = db.query(Speaker).get(spk_id) if spk_id else None
                item = AgendaItem(
                    session_id=session_id,
                    order=idx,
                    title=title,
                    speaker_id=spk_obj.id if spk_obj else None,
                    speaker_name=spk_obj.name if spk_obj else None,
                    duration_minutes=int(form.get(f"agenda_duration_{idx}", 20) or 20),
                    description=form.get(f"agenda_desc_{idx}", "").strip() or None,
                )
                db.add(item)
            idx += 1
    else:
        # Non-primary: only update their own agenda items by speaker_id
        own_items = db.query(AgendaItem).filter(
            AgendaItem.session_id == session_id,
            AgendaItem.speaker_id == speaker.id,
        ).all()
        for item in own_items:
            idx = item.order
            new_title = form.get(f"agenda_title_{idx}", "").strip()
            if new_title:
                item.title = new_title
                item.duration_minutes = int(form.get(f"agenda_duration_{idx}", item.duration_minutes) or item.duration_minutes)
                item.description = form.get(f"agenda_desc_{idx}", "").strip() or None

    log_activity(db, category="speaker", action="update", description=f"Speaker '{speaker.name}' updated session '{session_obj.title}'", request=request, user_id=user.id, target_type="session", target_id=session_id)
    db.commit()
    flash(request, f"Session '{session_obj.title}' updated.", "success")
    return RedirectResponse("/speaker/sessions", status_code=303)


@router.get("/profile")
def profile_page(request: Request, db: Session = Depends(get_db)):
    user, speaker = _require_speaker(request, db)
    return templates.TemplateResponse(
        "speaker/profile.html",
        _speaker_ctx(request, speaker=speaker),
    )


@router.post("/profile")
async def profile_update(request: Request, db: Session = Depends(get_db)):
    user, speaker = _require_speaker(request, db)
    form = await request.form()

    speaker.name = form.get("name", speaker.name).strip()
    speaker.title = form.get("title", "").strip() or None
    speaker.bio = form.get("bio", "").strip() or None
    speaker.photo_url = form.get("photo_url", "").strip() or None
    db.commit()

    for s in speaker.sessions:
        s.speaker_name = speaker.name
    log_activity(db, category="speaker", action="profile_update", description=f"Speaker '{speaker.name}' updated their profile", request=request, user_id=user.id, target_type="speaker", target_id=speaker.id)
    db.commit()

    flash(request, "Speaker profile updated.", "success")
    return RedirectResponse("/speaker/profile", status_code=303)
