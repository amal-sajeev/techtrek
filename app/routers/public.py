import io
import re
from collections import defaultdict
from datetime import datetime, date, time
from urllib.parse import urlparse, parse_qs

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import RedirectResponse, StreamingResponse, JSONResponse
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.dependencies import flash, get_db, now_ist, template_ctx, templates
from app.models.auditorium import Auditorium
from app.models.booking import Booking
from app.models.city import City
from app.models.college import College
from app.models.seat import Seat
from app.models.session import LectureSession
from app.models.speaker import Speaker
from app.models.testimonial import Testimonial, NewsletterSubscriber
from app.models.session_recording import SessionRecording
from app.models.user import User

router = APIRouter(tags=["public"])


def _build_embed_url(recording_url: str | None) -> str | None:
    """Convert a supported hosted-video URL into its embeddable iframe src."""
    if not recording_url:
        return None
    parsed = urlparse(recording_url)
    host = (parsed.hostname or "").lower()

    # YouTube
    if host in ("youtube.com", "www.youtube.com"):
        qs = parse_qs(parsed.query)
        vid = qs.get("v", [None])[0]
        if vid:
            return f"https://www.youtube.com/embed/{vid}"
    if host == "youtu.be":
        vid = parsed.path.lstrip("/").split("/")[0]
        if vid:
            return f"https://www.youtube.com/embed/{vid}"

    # Vimeo
    if host in ("vimeo.com", "player.vimeo.com"):
        parts = [p for p in parsed.path.split("/") if p]
        vid = parts[-1] if parts else None
        if vid and vid.isdigit():
            return f"https://player.vimeo.com/video/{vid}"

    # Dailymotion
    if host in ("dailymotion.com", "www.dailymotion.com"):
        m = re.search(r"/video/([a-zA-Z0-9]+)", parsed.path)
        if m:
            return f"https://www.dailymotion.com/embed/video/{m.group(1)}"
    if host == "dai.ly":
        vid = parsed.path.lstrip("/").split("/")[0]
        if vid:
            return f"https://www.dailymotion.com/embed/video/{vid}"

    # Twitch
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

    # Facebook Video
    if host in ("facebook.com", "www.facebook.com", "fb.watch"):
        from urllib.parse import quote_plus
        return f"https://www.facebook.com/plugins/video.php?href={quote_plus(recording_url)}"

    # Streamable
    if host == "streamable.com":
        vid = parsed.path.lstrip("/").split("/")[0]
        if vid:
            return f"https://streamable.com/e/{vid}"

    # Wistia
    if host in ("wistia.com", "fast.wistia.com"):
        parts = [p for p in parsed.path.split("/") if p]
        if "medias" in parts:
            idx = parts.index("medias")
            if idx + 1 < len(parts):
                return f"https://fast.wistia.com/embed/medias/{parts[idx + 1]}"

    # Loom
    if host in ("loom.com", "www.loom.com"):
        m = re.search(r"/share/([a-f0-9]+)", parsed.path)
        if m:
            return f"https://www.loom.com/embed/{m.group(1)}"

    # Google Drive
    if host == "drive.google.com":
        m = re.search(r"/d/([a-zA-Z0-9_-]+)", parsed.path)
        if m:
            return f"https://drive.google.com/file/d/{m.group(1)}/preview"

    return None


def _seat_stats(db: Session, session_id: int, auditorium_id: int):
    total = (
        db.query(func.count(Seat.id))
        .filter(Seat.auditorium_id == auditorium_id, Seat.is_active == True, Seat.seat_type.notin_(["aisle", "reserved"]))
        .scalar()
    )
    now = now_ist()
    booked = (
        db.query(func.count(Booking.id))
        .filter(
            Booking.session_id == session_id,
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


def _public_status_label(session, stats):
    if session.status == "completed":
        return "completed"
    if stats["available"] == 0:
        return "sold-out"
    return "open"


@router.get("/")
def home(request: Request, db: Session = Depends(get_db)):
    now = now_ist()
    upcoming = (
        db.query(LectureSession)
        .filter(LectureSession.status == "published", LectureSession.start_time > now)
        .order_by(LectureSession.start_time)
        .limit(6)
        .all()
    )
    sessions_with_info = []
    for s in upcoming:
        stats = _seat_stats(db, s.id, s.auditorium_id)
        speaker = db.query(Speaker).get(s.speaker_id) if s.speaker_id else None
        delta = s.start_time - now
        days_until = max(0, delta.days)
        hours_until = max(0, int(delta.total_seconds() // 3600) % 24)
        sessions_with_info.append({
            "session": s,
            "auditorium": db.query(Auditorium).get(s.auditorium_id),
            "speaker_obj": speaker,
            "stats": stats,
            "availability": _availability_label(stats),
            "event_status": _public_status_label(s, stats),
            "days_until": days_until,
            "hours_until": hours_until,
        })

    featured = sessions_with_info[0] if sessions_with_info else None

    testimonials = db.query(Testimonial).filter(Testimonial.is_active == True).all()

    total_attendees = db.query(func.count(func.distinct(Booking.user_id))).filter(Booking.payment_status == "paid").scalar() or 0
    total_speakers = db.query(func.count(Speaker.id)).scalar() or 0
    total_sessions = db.query(func.count(LectureSession.id)).filter(LectureSession.status == "published").scalar() or 0

    return templates.TemplateResponse(
        "public/home.html",
        template_ctx(
            request,
            sessions=sessions_with_info,
            featured=featured,
            testimonials=testimonials,
            total_attendees=total_attendees,
            total_speakers=total_speakers,
            total_sessions=total_sessions,
        ),
    )


@router.post("/newsletter")
async def newsletter_subscribe(request: Request, db: Session = Depends(get_db)):
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
    db: Session = Depends(get_db),
    q: str = Query("", alias="q"),
    sort: str = Query("date", alias="sort"),
    date_filter: str | None = Query(None, alias="date"),
    city_id: int | None = Query(None, alias="city_id"),
    college_id: int | None = Query(None, alias="college_id"),
):
    now = now_ist()
    query = (
        db.query(LectureSession)
        .filter(
            LectureSession.status == "published",
            LectureSession.start_time > now,
        )
        .join(Auditorium)
        .outerjoin(College)
    )
    if q:
        query = query.filter(
            LectureSession.title.ilike(f"%{q}%")
            | LectureSession.speaker.ilike(f"%{q}%")
        )
    if date_filter:
        try:
            d = date.fromisoformat(date_filter)
            start_of_day = datetime.combine(d, time.min)
            end_of_day = datetime.combine(d, time.max)
            query = query.filter(
                LectureSession.start_time >= start_of_day,
                LectureSession.start_time <= end_of_day,
            )
        except ValueError:
            pass
    # Normalize: if college is set, force city to match that college
    selected_college = None
    if college_id is not None:
        selected_college = db.query(College).get(college_id)
        if selected_college and selected_college.city_id:
            city_id = selected_college.city_id

    if college_id is not None:
        query = query.filter(Auditorium.college_id == college_id)
    if city_id is not None:
        query = query.filter(College.city_id == city_id)
    if sort == "price":
        query = query.order_by(LectureSession.price)
    elif sort == "title":
        query = query.order_by(LectureSession.title)
    else:
        query = query.order_by(LectureSession.start_time)

    all_sessions = query.all()
    sessions_with_info = []
    for s in all_sessions:
        stats = _seat_stats(db, s.id, s.auditorium_id)
        sessions_with_info.append({
            "session": s,
            "auditorium": db.query(Auditorium).get(s.auditorium_id),
            "stats": stats,
            "availability": _availability_label(stats),
            "event_status": _public_status_label(s, stats),
        })

    # Constrain dropdown options: city limits colleges, college limits cities
    if city_id is not None:
        colleges = db.query(College).filter(College.is_active == True, College.city_id == city_id).order_by(College.name).all()
    else:
        colleges = db.query(College).filter(College.is_active == True).order_by(College.name).all()

    if selected_college and selected_college.city_id:
        cities = db.query(City).filter(City.is_active == True, City.id == selected_college.city_id).order_by(City.name).all()
    else:
        cities = db.query(City).filter(City.is_active == True).order_by(City.name).all()

    return templates.TemplateResponse(
        "public/sessions.html",
        template_ctx(
            request,
            sessions=sessions_with_info,
            q=q,
            sort=sort,
            date_filter=date_filter or "",
            city_id=city_id,
            college_id=college_id,
            cities=cities,
            colleges=colleges,
        ),
    )


@router.get("/sessions/{session_id}")
def session_detail(request: Request, session_id: int, db: Session = Depends(get_db)):
    lecture = db.query(LectureSession).filter(LectureSession.id == session_id).first()
    if not lecture:
        return templates.TemplateResponse(
            "errors/404.html", template_ctx(request), status_code=404
        )
    auditorium = db.query(Auditorium).get(lecture.auditorium_id)
    stats = _seat_stats(db, lecture.id, lecture.auditorium_id)
    availability = _availability_label(stats)

    user_id = request.session.get("user_id")
    on_waitlist = False
    if user_id:
        from app.models.waitlist import Waitlist
        on_waitlist = (
            db.query(Waitlist)
            .filter(Waitlist.session_id == session_id, Waitlist.user_id == user_id)
            .first()
            is not None
        )

    has_priority = False
    if user_id and availability != "sold-out":
        from app.models.waitlist import Waitlist
        now = now_ist()
        priority_entry = (
            db.query(Waitlist)
            .filter(
                Waitlist.priority_session_id == session_id,
                Waitlist.user_id == user_id,
                Waitlist.priority_expires_at > now,
            )
            .first()
        )
        has_priority = priority_entry is not None

        any_priority = (
            db.query(Waitlist)
            .filter(
                Waitlist.priority_session_id == session_id,
                Waitlist.priority_expires_at > now,
            )
            .count()
        )
        if any_priority > 0 and not has_priority:
            availability = "priority-only"

    event_status = _public_status_label(lecture, stats)

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
            lecture=lecture,
            auditorium=auditorium,
            stats=stats,
            availability=availability,
            event_status=event_status,
            on_waitlist=on_waitlist,
            has_priority=has_priority,
            recordings=enriched_recordings,
        ),
    )


@router.get("/recordings")
def recordings_page(request: Request, db: Session = Depends(get_db)):
    # Find sessions with at least one public SessionRecording
    session_ids_with_recordings = (
        db.query(SessionRecording.session_id)
        .filter(SessionRecording.is_public == True)
        .distinct()
        .all()
    )
    ids = [r[0] for r in session_ids_with_recordings]
    sessions = (
        db.query(LectureSession)
        .filter(LectureSession.id.in_(ids))
        .order_by(LectureSession.start_time.desc())
        .all()
    ) if ids else []
    enriched = []
    for s in sessions:
        aud = db.query(Auditorium).get(s.auditorium_id)
        enriched.append({"session": s, "auditorium": aud})
    return templates.TemplateResponse(
        "public/recordings.html",
        template_ctx(request, sessions=enriched),
    )


def _schedule_query(db: Session, college_id: str = "", auditorium_id: str = ""):
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
    return query.order_by(LectureSession.start_time).all()


@router.get("/schedule")
def schedule_page(
    request: Request,
    db: Session = Depends(get_db),
    college_id: str = Query("", alias="college_id"),
    auditorium_id: str = Query("", alias="auditorium_id"),
):
    sessions = _schedule_query(db, college_id, auditorium_id)
    grouped = defaultdict(list)
    for s in sessions:
        aud = db.query(Auditorium).get(s.auditorium_id)
        date_key = s.start_time.strftime("%Y-%m-%d")
        grouped[date_key].append({"session": s, "auditorium": aud})

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
    db: Session = Depends(get_db),
    college_id: str = Query("", alias="college_id"),
    auditorium_id: str = Query("", alias="auditorium_id"),
):
    sessions = _schedule_query(db, college_id, auditorium_id)
    result = defaultdict(list)
    for s in sessions:
        aud = db.query(Auditorium).get(s.auditorium_id)
        date_key = s.start_time.strftime("%Y-%m-%d")
        result[date_key].append({
            "id": s.id,
            "title": s.title,
            "speaker": s.speaker,
            "start_time": s.start_time.isoformat(),
            "duration_minutes": s.duration_minutes,
            "venue": aud.name if aud else "",
            "location": aud.location if aud else "",
            "status": s.status,
        })
    return JSONResponse(content=dict(sorted(result.items())))


@router.get("/schedule/export-pdf")
def schedule_export_pdf(
    db: Session = Depends(get_db),
    college_id: str = Query("", alias="college_id"),
    auditorium_id: str = Query("", alias="auditorium_id"),
):
    from reportlab.lib.pagesizes import A4
    from reportlab.lib import colors
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
    from reportlab.lib.styles import getSampleStyleSheet

    sessions = _schedule_query(db, college_id, auditorium_id)
    grouped = defaultdict(list)
    for s in sessions:
        aud = db.query(Auditorium).get(s.auditorium_id)
        date_key = s.start_time.strftime("%Y-%m-%d")
        grouped[date_key].append({"session": s, "auditorium": aud})

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4)
    styles = getSampleStyleSheet()
    elements = []

    elements.append(Paragraph("TechTrek Schedule", styles["Title"]))
    elements.append(Spacer(1, 12))

    for date_key in sorted(grouped.keys()):
        dt = datetime.strptime(date_key, "%Y-%m-%d")
        elements.append(Paragraph(dt.strftime("%A, %B %d, %Y"), styles["Heading2"]))
        data = [["Time", "Title", "Speaker", "Venue"]]
        for item in grouped[date_key]:
            s = item["session"]
            aud = item["auditorium"]
            data.append([
                s.start_time.strftime("%I:%M %p"),
                s.title,
                s.speaker,
                f"{aud.name}, {aud.location}" if aud else "",
            ])
        t = Table(data, colWidths=[70, 200, 120, 140])
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1a1a2e")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ]))
        elements.append(t)
        elements.append(Spacer(1, 16))

    doc.build(elements)
    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/pdf",
        headers={"Content-Disposition": 'attachment; filename="techtrek_schedule.pdf"'},
    )


@router.get("/ticket/{ticket_id}")
def public_ticket(request: Request, ticket_id: str, db: Session = Depends(get_db)):
    booking = (
        db.query(Booking)
        .filter(Booking.ticket_id == ticket_id, Booking.payment_status == "paid")
        .first()
    )
    if not booking:
        return templates.TemplateResponse(
            "errors/404.html", template_ctx(request), status_code=404
        )
    lecture = db.query(LectureSession).get(booking.session_id)
    auditorium = db.query(Auditorium).get(lecture.auditorium_id) if lecture else None
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
            lecture=lecture,
            auditorium=auditorium,
            seat=seat,
            ticket_user=user,
            group_bookings=group_bookings,
        ),
    )


@router.get("/tickets/group/{group_id}")
def public_ticket_group(request: Request, group_id: str, db: Session = Depends(get_db)):
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
    lecture = db.query(LectureSession).get(bookings[0].session_id)
    auditorium = db.query(Auditorium).get(lecture.auditorium_id) if lecture else None
    user = db.query(User).get(bookings[0].user_id)
    seats = [db.query(Seat).get(b.seat_id) for b in bookings]

    return templates.TemplateResponse(
        "public/ticket_group.html",
        template_ctx(
            request,
            bookings=bookings,
            lecture=lecture,
            auditorium=auditorium,
            seats=seats,
            ticket_user=user,
            group_id=group_id,
        ),
    )
