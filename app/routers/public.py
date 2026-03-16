import io
import re
from collections import defaultdict
from datetime import datetime, date, time, timedelta
from urllib.parse import urlparse, parse_qs

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import RedirectResponse, StreamingResponse, JSONResponse
from sqlalchemy import func
from sqlalchemy.orm import Session as DbSession

from app.csrf import csrf_protection
from app.dependencies import flash, get_db, now_ist, template_ctx, templates
from app.services.booking import _generate_qr_base64
from app.models.auditorium import Auditorium
from app.models.booking import Booking
from app.models.city import City
from app.models.college import College
from app.models.seat import Seat
from app.models.session import Session
from app.models.speaker import Speaker
from app.models.testimonial import Testimonial, NewsletterSubscriber
from app.models.session_recording import SessionRecording
from app.models.seat_type import SeatType
from app.models.event import Event
from app.models.feedback import Feedback
from app.models.user import User

router = APIRouter(tags=["public"], dependencies=[Depends(csrf_protection)])


def _build_embed_url(recording_url: str | None) -> str | None:
    """Convert a supported hosted-video URL into its embeddable iframe src."""
    if not recording_url:
        return None
    parsed = urlparse(recording_url)
    host = (parsed.hostname or "").lower()

    if host in ("youtube.com", "www.youtube.com"):
        qs = parse_qs(parsed.query)
        vid = qs.get("v", [None])[0]
        if vid:
            return f"https://www.youtube.com/embed/{vid}"
    if host == "youtu.be":
        vid = parsed.path.lstrip("/").split("/")[0]
        if vid:
            return f"https://www.youtube.com/embed/{vid}"
    if host in ("vimeo.com", "player.vimeo.com"):
        parts = [p for p in parsed.path.split("/") if p]
        vid = parts[-1] if parts else None
        if vid and vid.isdigit():
            return f"https://player.vimeo.com/video/{vid}"
    if host in ("dailymotion.com", "www.dailymotion.com"):
        m = re.search(r"/video/([a-zA-Z0-9]+)", parsed.path)
        if m:
            return f"https://www.dailymotion.com/embed/video/{m.group(1)}"
    if host == "dai.ly":
        vid = parsed.path.lstrip("/").split("/")[0]
        if vid:
            return f"https://www.dailymotion.com/embed/video/{vid}"
    if host in ("twitch.tv", "www.twitch.tv"):
        parts = [p for p in parsed.path.split("/") if p]
        if len(parts) >= 2 and parts[0] == "videos":
            return f"https://player.twitch.tv/?video={parts[1]}&parent=localhost"
        if parts:
            return f"https://player.twitch.tv/?channel={parts[0]}&parent=localhost"
    if host == "clips.twitch.tv":
        slug = parsed.path.lstrip("/").split("/")[0]
        if slug:
            return f"https://clips.twitch.tv/embed?clip={slug}&parent=localhost"
    if host in ("facebook.com", "www.facebook.com", "fb.watch"):
        from urllib.parse import quote_plus
        return f"https://www.facebook.com/plugins/video.php?href={quote_plus(recording_url)}"
    if host == "streamable.com":
        vid = parsed.path.lstrip("/").split("/")[0]
        if vid:
            return f"https://streamable.com/e/{vid}"
    if host in ("wistia.com", "fast.wistia.com"):
        parts = [p for p in parsed.path.split("/") if p]
        if "medias" in parts:
            idx = parts.index("medias")
            if idx + 1 < len(parts):
                return f"https://fast.wistia.com/embed/medias/{parts[idx + 1]}"
    if host in ("loom.com", "www.loom.com"):
        m = re.search(r"/share/([a-f0-9]+)", parsed.path)
        if m:
            return f"https://www.loom.com/embed/{m.group(1)}"
    if host == "drive.google.com":
        m = re.search(r"/d/([a-zA-Z0-9_-]+)", parsed.path)
        if m:
            return f"https://drive.google.com/file/d/{m.group(1)}/preview"
    return None


def _event_seat_stats(db: DbSession, event_id: int, auditorium_id: int):
    total = (
        db.query(func.count(Seat.id))
        .filter(Seat.auditorium_id == auditorium_id, Seat.is_active == True, Seat.seat_type.notin_(["aisle", "reserved"]))
        .scalar()
    )
    now = now_ist()
    booked = (
        db.query(func.count(Booking.id))
        .filter(
            Booking.event_id == event_id,
            Booking.payment_status.in_(["paid", "hold"]),
        )
        .filter(
            (Booking.payment_status == "paid")
            | ((Booking.payment_status == "hold") & (Booking.held_until > now))
        )
        .scalar()
    )
    available = max(0, total - booked)
    return {"total": total, "booked": booked, "available": available}


def _availability_label(stats):
    if stats["available"] == 0:
        return "sold-out"
    if stats["available"] <= stats["total"] * 0.2:
        return "filling-up"
    return "available"


def _public_event_status(event, stats):
    if event.status == "completed":
        return "completed"
    if stats["available"] == 0:
        return "sold-out"
    return "open"


@router.get("/")
def home(request: Request, db: DbSession = Depends(get_db)):
    now = now_ist()
    today = now.date()

    upcoming_events = (
        db.query(Event)
        .filter(Event.status == "published", Event.start_date >= today)
        .order_by(Event.start_date)
        .limit(6)
        .all()
    )
    events_with_info = []
    for ev in upcoming_events:
        auditorium = db.query(Auditorium).get(ev.auditorium_id) if ev.auditorium_id else None
        stats = _event_seat_stats(db, ev.id, ev.auditorium_id) if ev.auditorium_id else {"total": 0, "booked": 0, "available": 0}
        session_count = db.query(func.count(Session.id)).filter(Session.event_id == ev.id).scalar()
        city = ev.college.city if ev.college else None
        delta = datetime.combine(ev.start_date, time.min) - now.replace(tzinfo=None)
        days_until = max(0, delta.days)
        hours_until = max(0, int(delta.total_seconds() // 3600) % 24)
        events_with_info.append({
            "event": ev,
            "auditorium": auditorium,
            "stats": stats,
            "availability": _availability_label(stats),
            "event_status": _public_event_status(ev, stats),
            "session_count": session_count,
            "city": city,
            "days_until": days_until,
            "hours_until": hours_until,
        })

    featured = events_with_info[0] if events_with_info else {}

    testimonials = db.query(Testimonial).filter(Testimonial.is_active == True).all()
    featured_feedback_rows = (
        db.query(Feedback)
        .filter(Feedback.allow_public == True, Feedback.is_featured == True, Feedback.rating != None)
        .order_by(Feedback.created_at.desc())
        .limit(10)
        .all()
    )
    featured_feedback = []
    for fb in featured_feedback_rows:
        user = db.query(User).get(fb.user_id)
        event = db.query(Event).get(fb.event_id) if fb.event_id else None
        if user and event:
            featured_feedback.append({
                "rating": fb.rating,
                "comment": fb.comment,
                "user_name": user.full_name or user.username,
                "college": user.college or "",
                "event_name": event.name,
            })

    total_attendees = db.query(func.count(func.distinct(Booking.user_id))).filter(Booking.payment_status == "paid").scalar() or 0
    total_speakers = db.query(func.count(Speaker.id)).scalar() or 0
    total_events = db.query(func.count(Event.id)).filter(Event.status == "published").scalar() or 0

    featured_sessions = (
        db.query(Session)
        .join(Event, Session.event_id == Event.id)
        .filter(Event.status == "published", Event.start_date >= today)
        .order_by(Session.start_time)
        .limit(10)
        .all()
    )
    sessions_with_info = []
    for sess in featured_sessions:
        ev = sess.event
        speaker = db.query(Speaker).get(sess.speaker_id) if sess.speaker_id else None
        sessions_with_info.append({
            "session": sess,
            "event": ev,
            "speaker_obj": speaker,
        })

    return templates.TemplateResponse(
        "public/home.html",
        template_ctx(
            request,
            events=events_with_info,
            featured=featured,
            sessions=sessions_with_info,
            testimonials=testimonials,
            featured_feedback=featured_feedback,
            total_attendees=total_attendees,
            total_speakers=total_speakers,
            total_events=total_events,
        ),
    )


@router.post("/newsletter")
async def newsletter_subscribe(request: Request, db: DbSession = Depends(get_db)):
    form = await request.form()
    email = form.get("email", "").strip()
    if not email or "@" not in email:
        flash(request, "Please enter a valid email.", "danger")
        return RedirectResponse("/", status_code=303)

    existing = db.query(NewsletterSubscriber).filter(NewsletterSubscriber.email == email).first()
    if existing:
        flash(request, "You're already subscribed!", "info")
    else:
        sub = NewsletterSubscriber(email=email)
        db.add(sub)
        db.commit()
        flash(request, "Subscribed to the newsletter!", "success")
    return RedirectResponse("/", status_code=303)


@router.get("/sessions")
def sessions_list(
    request: Request,
    db: DbSession = Depends(get_db),
    q: str = Query("", alias="q"),
    sort: str = Query("date", alias="sort"),
):
    query = (
        db.query(Session)
        .join(Event, Session.event_id == Event.id)
        .filter(Event.status == "published")
    )
    if q:
        query = query.filter(
            Session.title.ilike(f"%{q}%")
            | Session.speaker_name.ilike(f"%{q}%")
        )
    if sort == "title":
        query = query.order_by(Session.title)
    else:
        query = query.order_by(Session.start_time)

    all_sessions = query.all()
    sessions_with_info = []
    for sess in all_sessions:
        event = sess.event
        speaker = db.query(Speaker).get(sess.speaker_id) if sess.speaker_id else None
        sessions_with_info.append({
            "session": sess,
            "event": event,
            "speaker_obj": speaker,
        })

    return templates.TemplateResponse(
        "public/sessions.html",
        template_ctx(
            request,
            sessions=sessions_with_info,
            q=q,
            sort=sort,
        ),
    )


@router.get("/sessions/{session_id}")
def session_detail(request: Request, session_id: int, db: DbSession = Depends(get_db)):
    session_obj = db.query(Session).filter(Session.id == session_id).first()
    if not session_obj:
        return templates.TemplateResponse(
            "errors/404.html", template_ctx(request), status_code=404
        )

    event = session_obj.event
    auditorium = db.query(Auditorium).get(event.auditorium_id) if event and event.auditorium_id else None

    stats = (
        _event_seat_stats(db, event.id, event.auditorium_id)
        if event and event.auditorium_id
        else {"total": 0, "booked": 0, "available": 0}
    )
    availability = _availability_label(stats)
    event_status = _public_event_status(event, stats) if event else "open"

    sibling_sessions = []
    if event:
        siblings = (
            db.query(Session)
            .filter(Session.event_id == event.id, Session.id != session_id)
            .order_by(Session.order, Session.start_time)
            .all()
        )
        for s in siblings:
            speaker = db.query(Speaker).get(s.speaker_id) if s.speaker_id else None
            sibling_sessions.append({"session": s, "speaker_obj": speaker})

    public_recordings = (
        db.query(SessionRecording)
        .filter(SessionRecording.session_id == session_id, SessionRecording.is_public == True)
        .order_by(SessionRecording.order)
        .all()
    )
    enriched_recordings = [{"rec": r, "embed_url": _build_embed_url(r.url)} for r in public_recordings]

    return templates.TemplateResponse(
        "public/session_detail.html",
        template_ctx(
            request,
            lecture=session_obj,
            session=session_obj,
            event=event,
            auditorium=auditorium,
            recordings=enriched_recordings,
            stats=stats,
            availability=availability,
            event_status=event_status,
            sibling_sessions=sibling_sessions,
            total_sessions=(len(sibling_sessions) + 1) if event else 1,
        ),
    )


@router.get("/events")
def events_list(
    request: Request,
    db: DbSession = Depends(get_db),
    q: str = Query("", alias="q"),
    sort: str = Query("date", alias="sort"),
    city_id: str | None = Query(None, alias="city_id"),
):
    now = now_ist()
    city_id_int = int(city_id) if city_id else None

    query = (
        db.query(Event)
        .filter(Event.status == "published")
        .outerjoin(College, Event.college_id == College.id)
        .outerjoin(City, College.city_id == City.id)
    )
    if q:
        query = query.filter(
            Event.name.ilike(f"%{q}%")
            | College.name.ilike(f"%{q}%")
            | City.name.ilike(f"%{q}%")
        )
    if city_id_int:
        query = query.filter(College.city_id == city_id_int)

    events = query.all()
    cities = db.query(City).filter(City.is_active == True).order_by(City.name).all()

    events_info = []
    for ev in events:
        session_count = db.query(func.count(Session.id)).filter(Session.event_id == ev.id).scalar()
        auditorium = db.query(Auditorium).get(ev.auditorium_id) if ev.auditorium_id else None
        stats = _event_seat_stats(db, ev.id, ev.auditorium_id) if ev.auditorium_id else {"total": 0, "booked": 0, "available": 0}
        city = ev.college.city if ev.college else None
        events_info.append({
            "event": ev,
            "session_count": session_count,
            "college": ev.college,
            "city": city,
            "auditorium": auditorium,
            "stats": stats,
            "availability": _availability_label(stats),
            "price": float(ev.price) if ev.price else 0,
        })

    if sort == "name":
        events_info.sort(key=lambda x: x["event"].name.lower())
    elif sort == "price":
        events_info.sort(key=lambda x: x["price"])
    else:
        events_info.sort(key=lambda x: (x["event"].start_date is None, x["event"].start_date))

    week_end = now + timedelta(days=7)
    two_weeks_end = now + timedelta(days=14)

    return templates.TemplateResponse(
        "public/events.html",
        template_ctx(request,
            events=events_info,
            cities=cities,
            q=q,
            sort=sort,
            city_id=city_id_int,
            now=now,
            week_end=week_end,
            two_weeks_end=two_weeks_end,
        ),
    )


@router.get("/events/{event_id}")
def event_detail(request: Request, event_id: int, db: DbSession = Depends(get_db)):
    ev = db.query(Event).filter(Event.id == event_id, Event.status == "published").first()
    if not ev:
        return templates.TemplateResponse(
            "errors/404.html", template_ctx(request), status_code=404
        )

    auditorium = db.query(Auditorium).get(ev.auditorium_id) if ev.auditorium_id else None
    stats = _event_seat_stats(db, ev.id, ev.auditorium_id) if ev.auditorium_id else {"total": 0, "booked": 0, "available": 0}
    availability = _availability_label(stats)

    sessions = (
        db.query(Session)
        .filter(Session.event_id == event_id)
        .order_by(Session.order, Session.start_time)
        .all()
    )
    sessions_info = []
    for sess in sessions:
        speaker = db.query(Speaker).get(sess.speaker_id) if sess.speaker_id else None
        sessions_info.append({
            "session": sess,
            "speaker_obj": speaker,
        })

    user_id = request.session.get("user_id")
    on_waitlist = False
    if user_id:
        from app.models.waitlist import Waitlist
        on_waitlist = (
            db.query(Waitlist)
            .filter(Waitlist.event_id == event_id, Waitlist.user_id == user_id)
            .first()
            is not None
        )

    return templates.TemplateResponse(
        "public/event_detail.html",
        template_ctx(
            request,
            event=ev,
            auditorium=auditorium,
            sessions=sessions_info,
            stats=stats,
            availability=availability,
            event_status=_public_event_status(ev, stats),
            on_waitlist=on_waitlist,
        ),
    )


@router.get("/recordings")
def recordings_page(request: Request, db: DbSession = Depends(get_db)):
    user_id = request.session.get("user_id")
    if not user_id:
        flash(request, "Sign in to view recordings for your booked sessions.", "info")
        return RedirectResponse("/auth/login?next=/recordings", status_code=303)

    session_ids_with_recordings = {
        r[0] for r in db.query(SessionRecording.session_id)
        .filter(SessionRecording.is_public == True)
        .distinct()
        .all()
    }

    paid_event_ids = {
        row[0] for row in db.query(Booking.event_id)
        .filter(
            Booking.user_id == user_id,
            Booking.payment_status == "paid",
            Booking.event_id != None,
        )
        .distinct()
        .all()
    }

    paid_session_ids = set()
    if paid_event_ids:
        paid_session_ids = {
            row[0] for row in db.query(Session.id)
            .filter(Session.event_id.in_(paid_event_ids))
            .all()
        }

    session_ids = list(session_ids_with_recordings & paid_session_ids)
    sessions = (
        db.query(Session)
        .filter(Session.id.in_(session_ids))
        .all()
    ) if session_ids else []

    enriched = []
    for s in sessions:
        event = s.event
        auditorium = db.query(Auditorium).get(event.auditorium_id) if event and event.auditorium_id else None
        enriched.append({"session": s, "event": event, "auditorium": auditorium})
    return templates.TemplateResponse(
        "public/recordings.html",
        template_ctx(request, sessions=enriched),
    )


@router.get("/schedule")
def schedule_page(
    request: Request,
    db: DbSession = Depends(get_db),
    college_id: str = Query("", alias="college_id"),
    auditorium_id: str = Query("", alias="auditorium_id"),
):
    query = db.query(Event).filter(Event.status.in_(["published", "completed"]))
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
        if not ev.start_date:
            continue
        date_key = ev.start_date.strftime("%Y-%m-%d")
        auditorium = db.query(Auditorium).get(ev.auditorium_id) if ev.auditorium_id else None
        sessions = (
            db.query(Session)
            .filter(Session.event_id == ev.id)
            .order_by(Session.order, Session.start_time)
            .all()
        )
        grouped[date_key].append({"event": ev, "auditorium": auditorium, "sessions": sessions})

    colleges = db.query(College).order_by(College.name).all()
    auditoriums = db.query(Auditorium).order_by(Auditorium.name).all()

    return templates.TemplateResponse(
        "public/schedule.html",
        template_ctx(
            request,
            grouped=dict(sorted(grouped.items())),
            colleges=colleges, auditoriums=auditoriums,
            college_id=college_id, auditorium_id=auditorium_id,
        ),
    )


@router.get("/api/schedule")
def api_schedule(
    db: DbSession = Depends(get_db),
    college_id: str = Query("", alias="college_id"),
    auditorium_id: str = Query("", alias="auditorium_id"),
):
    query = db.query(Event).filter(Event.status.in_(["published", "completed"]))
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
        except ValueError:
            pass

    events = query.order_by(Event.start_date).all()
    result = defaultdict(list)
    for ev in events:
        if not ev.start_date:
            continue
        date_key = ev.start_date.strftime("%Y-%m-%d")
        aud = db.query(Auditorium).get(ev.auditorium_id) if ev.auditorium_id else None
        sessions = db.query(Session).filter(Session.event_id == ev.id).order_by(Session.order, Session.start_time).all()
        result[date_key].append({
            "id": ev.id,
            "name": ev.name,
            "start_date": ev.start_date.isoformat(),
            "venue": aud.name if aud else "",
            "location": aud.location if aud else "",
            "status": ev.status,
            "sessions": [
                {
                    "title": s.title,
                    "speaker": s.speaker_name,
                    "start_time": s.start_time.isoformat() if s.start_time else None,
                    "duration_minutes": s.duration_minutes,
                }
                for s in sessions
            ],
        })
    return JSONResponse(content=dict(sorted(result.items())))


@router.get("/schedule/export-pdf")
def schedule_export_pdf(
    db: DbSession = Depends(get_db),
    college_id: str = Query("", alias="college_id"),
    auditorium_id: str = Query("", alias="auditorium_id"),
):
    from reportlab.lib.pagesizes import A4
    from reportlab.lib import colors
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
    from reportlab.lib.styles import getSampleStyleSheet

    query = db.query(Event).filter(Event.status.in_(["published", "completed"]))
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
        except ValueError:
            pass

    events = query.order_by(Event.start_date).all()
    grouped = defaultdict(list)
    for ev in events:
        if not ev.start_date:
            continue
        date_key = ev.start_date.strftime("%Y-%m-%d")
        aud = db.query(Auditorium).get(ev.auditorium_id) if ev.auditorium_id else None
        sessions = db.query(Session).filter(Session.event_id == ev.id).order_by(Session.order, Session.start_time).all()
        grouped[date_key].append({"event": ev, "auditorium": aud, "sessions": sessions})

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4)
    styles = getSampleStyleSheet()
    elements = []

    elements.append(Paragraph("TechTrek Schedule", styles["Title"]))
    elements.append(Spacer(1, 12))

    for date_key in sorted(grouped.keys()):
        dt = datetime.strptime(date_key, "%Y-%m-%d")
        elements.append(Paragraph(dt.strftime("%A, %B %d, %Y"), styles["Heading2"]))
        for item in grouped[date_key]:
            ev = item["event"]
            aud = item["auditorium"]
            elements.append(Paragraph(f"{ev.name} — {aud.name if aud else 'TBA'}", styles["Heading3"]))
            data = [["Time", "Session", "Speaker", "Duration"]]
            for sess in item["sessions"]:
                data.append([
                    sess.start_time.strftime("%I:%M %p") if sess.start_time else "",
                    sess.title,
                    sess.speaker_name,
                    f"{sess.duration_minutes} min" if sess.duration_minutes else "",
                ])
            t = Table(data, colWidths=[70, 200, 120, 80])
            t.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1a1a2e")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ]))
            elements.append(t)
            elements.append(Spacer(1, 8))
        elements.append(Spacer(1, 16))

    doc.build(elements)
    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/pdf",
        headers={"Content-Disposition": 'attachment; filename="techtrek_schedule.pdf"'},
    )


@router.get("/ticket/{ticket_id}")
def public_ticket(request: Request, ticket_id: str, db: DbSession = Depends(get_db)):
    viewer_id = request.session.get("user_id")
    if not viewer_id:
        flash(request, "Please log in to view your ticket.", "info")
        return RedirectResponse(f"/auth/login?next=/ticket/{ticket_id}", status_code=303)

    booking = (
        db.query(Booking)
        .filter(Booking.ticket_id == ticket_id, Booking.payment_status == "paid")
        .first()
    )
    if not booking:
        return templates.TemplateResponse(
            "errors/404.html", template_ctx(request), status_code=404
        )

    viewer = db.query(User).filter(User.id == viewer_id).first()
    is_privileged = viewer and viewer.is_admin
    if not is_privileged and viewer and viewer.is_supervisor and viewer.supervisor_college_id:
        event = db.query(Event).get(booking.event_id) if booking.event_id else None
        if event and event.auditorium_id:
            aud = db.query(Auditorium).get(event.auditorium_id)
            if aud and aud.college_id == viewer.supervisor_college_id:
                is_privileged = True
    if booking.user_id != viewer_id and not is_privileged:
        return templates.TemplateResponse(
            "errors/404.html", template_ctx(request), status_code=404
        )

    event = db.query(Event).get(booking.event_id) if booking.event_id else None
    auditorium = db.query(Auditorium).get(event.auditorium_id) if event and event.auditorium_id else None
    seat = db.query(Seat).get(booking.seat_id)
    user = db.query(User).get(booking.user_id)

    group_bookings = []
    if booking.booking_group:
        group_bookings = (
            db.query(Booking)
            .filter(
                Booking.booking_group == booking.booking_group,
                Booking.payment_status == "paid",
            )
            .all()
        )

    return templates.TemplateResponse(
        "public/ticket.html",
        template_ctx(
            request,
            booking=booking,
            event=event,
            auditorium=auditorium,
            seat=seat,
            ticket_user=user,
            group_bookings=group_bookings,
        ),
    )


@router.get("/tickets/group/{group_id}")
def public_ticket_group(request: Request, group_id: str, db: DbSession = Depends(get_db)):
    viewer_id = request.session.get("user_id")
    if not viewer_id:
        flash(request, "Please log in to view your tickets.", "info")
        return RedirectResponse(f"/auth/login?next=/tickets/group/{group_id}", status_code=303)

    bookings = (
        db.query(Booking)
        .filter(
            Booking.booking_group == group_id,
            Booking.payment_status == "paid",
        )
        .all()
    )
    if not bookings:
        return templates.TemplateResponse(
            "errors/404.html", template_ctx(request), status_code=404
        )

    viewer = db.query(User).filter(User.id == viewer_id).first()
    is_privileged = viewer and viewer.is_admin
    if not is_privileged and viewer and viewer.is_supervisor and viewer.supervisor_college_id:
        event = db.query(Event).get(bookings[0].event_id) if bookings[0].event_id else None
        if event and event.auditorium_id:
            aud = db.query(Auditorium).get(event.auditorium_id)
            if aud and aud.college_id == viewer.supervisor_college_id:
                is_privileged = True
    if bookings[0].user_id != viewer_id and not is_privileged:
        return templates.TemplateResponse(
            "errors/404.html", template_ctx(request), status_code=404
        )

    event = db.query(Event).get(bookings[0].event_id) if bookings[0].event_id else None
    auditorium = db.query(Auditorium).get(event.auditorium_id) if event and event.auditorium_id else None
    user = db.query(User).get(bookings[0].user_id)
    seats = [db.query(Seat).get(b.seat_id) for b in bookings]
    group_qr_data = _generate_qr_base64(f"GROUP-{group_id}") if len(bookings) > 1 else None

    return templates.TemplateResponse(
        "public/ticket_group.html",
        template_ctx(
            request,
            bookings=bookings,
            event=event,
            auditorium=auditorium,
            seats=seats,
            ticket_user=user,
            group_id=group_id,
            group_qr_data=group_qr_data,
        ),
    )


@router.get("/terms")
def terms_page(request: Request):
    return templates.TemplateResponse("public/terms.html", template_ctx(request))


# --- Feedback (event-centric) ---

@router.get("/feedback/{event_id}")
def feedback_form(request: Request, event_id: int, db: DbSession = Depends(get_db)):
    user_id = request.session.get("user_id")
    if not user_id:
        return RedirectResponse(f"/auth/login?next=/feedback/{event_id}", status_code=303)

    event = db.query(Event).get(event_id)
    if not event:
        return templates.TemplateResponse("errors/404.html", template_ctx(request), status_code=404)

    auditorium = db.query(Auditorium).get(event.auditorium_id) if event.auditorium_id else None

    existing = db.query(Feedback).filter(
        Feedback.user_id == user_id, Feedback.event_id == event_id
    ).first()
    if existing and existing.rating is not None:
        flash(request, "You have already submitted feedback for this event.", "info")
        return RedirectResponse("/booking/my", status_code=303)

    return templates.TemplateResponse(
        "public/feedback_form.html",
        template_ctx(
            request,
            event=event,
            auditorium=auditorium,
            existing=existing,
        ),
    )


@router.post("/feedback/{event_id}")
async def feedback_submit(request: Request, event_id: int, db: DbSession = Depends(get_db)):
    user_id = request.session.get("user_id")
    if not user_id:
        return RedirectResponse(f"/auth/login?next=/feedback/{event_id}", status_code=303)

    event = db.query(Event).get(event_id)
    if not event:
        return templates.TemplateResponse("errors/404.html", template_ctx(request), status_code=404)

    form = await request.form()
    rating_raw = form.get("rating", "")
    comment = form.get("comment", "").strip()
    allow_public = "allow_public" in form

    try:
        rating = int(rating_raw)
        if rating < 1 or rating > 5:
            rating = None
    except (ValueError, TypeError):
        rating = None

    if not rating:
        flash(request, "Please select a rating.", "danger")
        return RedirectResponse(f"/feedback/{event_id}", status_code=303)

    existing = db.query(Feedback).filter(
        Feedback.user_id == user_id, Feedback.event_id == event_id
    ).first()

    if existing:
        existing.rating = rating
        existing.comment = comment or None
        existing.allow_public = allow_public
        existing.dismissed = False
    else:
        fb = Feedback(
            user_id=user_id,
            event_id=event_id,
            rating=rating,
            comment=comment or None,
            allow_public=allow_public,
        )
        db.add(fb)

    db.commit()
    flash(request, "Thank you for your feedback!", "success")
    return RedirectResponse("/booking/my", status_code=303)


@router.post("/feedback/{event_id}/dismiss")
async def feedback_dismiss(request: Request, event_id: int, db: DbSession = Depends(get_db)):
    user_id = request.session.get("user_id")
    if not user_id:
        return JSONResponse({"ok": False}, status_code=401)

    existing = db.query(Feedback).filter(
        Feedback.user_id == user_id, Feedback.event_id == event_id
    ).first()

    form = await request.form()
    dont_ask = form.get("dont_ask") == "1"

    if existing:
        existing.dismissed = True if dont_ask else existing.dismissed
    else:
        fb = Feedback(
            user_id=user_id,
            event_id=event_id,
            dismissed=dont_ask,
        )
        db.add(fb)

    db.commit()
    return JSONResponse({"ok": True})


# --- Newsletter Unsubscribe ---

@router.get("/newsletter/unsubscribe/{token}")
def newsletter_unsubscribe(request: Request, token: str, db: DbSession = Depends(get_db)):
    sub = db.query(NewsletterSubscriber).filter(NewsletterSubscriber.unsubscribe_token == token).first()
    if sub:
        db.delete(sub)
        db.commit()
    return templates.TemplateResponse(
        "public/newsletter_unsubscribed.html",
        template_ctx(request, found=sub is not None),
    )
