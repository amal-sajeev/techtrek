import io
import re
from collections import defaultdict
from datetime import datetime, date, time
from urllib.parse import urlparse, parse_qs

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import RedirectResponse, StreamingResponse, JSONResponse
from sqlalchemy import func
from sqlalchemy.orm import Session as DbSession

from app.csrf import csrf_protection
from app.dependencies import flash, get_db, now_ist, template_ctx, templates
from app.models.auditorium import Auditorium
from app.models.booking import Booking
from app.models.city import City
from app.models.college import College
from app.models.seat import Seat
from app.models.session import Session
from app.models.showing import Showing
from app.models.speaker import Speaker
from app.models.testimonial import Testimonial, NewsletterSubscriber
from app.models.session_recording import SessionRecording
from app.models.seat_type import SeatType
from app.models.event import Event
from app.models.event_showing import EventShowing
from app.models.feedback import Feedback
from app.models.user import User

router = APIRouter(tags=["public"], dependencies=[Depends(csrf_protection)])


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


def _seat_stats(db: DbSession, showing_id: int, auditorium_id: int):
    total = (
        db.query(func.count(Seat.id))
        .filter(Seat.auditorium_id == auditorium_id, Seat.is_active == True, Seat.seat_type.notin_(["aisle", "reserved"]))
        .scalar()
    )
    now = now_ist()
    booked = (
        db.query(func.count(Booking.id))
        .filter(
            Booking.showing_id == showing_id,
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


def _public_status_label(showing, stats):
    if showing.status == "completed":
        return "completed"
    if stats["available"] == 0:
        return "sold-out"
    return "open"


@router.get("/")
def home(request: Request, db: DbSession = Depends(get_db)):
    now = now_ist()
    upcoming = (
        db.query(Showing)
        .join(Session)
        .filter(Showing.status == "published", Showing.start_time > now)
        .order_by(Showing.start_time)
        .limit(6)
        .all()
    )
    sessions_with_info = []
    for sh in upcoming:
        stats = _seat_stats(db, sh.id, sh.auditorium_id)
        sess = sh.session
        speaker = db.query(Speaker).get(sess.speaker_id) if sess and sess.speaker_id else None
        delta = sh.start_time - now
        days_until = max(0, delta.days)
        hours_until = max(0, int(delta.total_seconds() // 3600) % 24)
        sessions_with_info.append({
            "session": sess,
            "showing": sh,
            "auditorium": db.query(Auditorium).get(sh.auditorium_id),
            "speaker_obj": speaker,
            "stats": stats,
            "availability": _availability_label(stats),
            "event_status": _public_status_label(sh, stats),
            "days_until": days_until,
            "hours_until": hours_until,
        })

    _feat = sessions_with_info[0] if sessions_with_info else {}
    featured_session = _feat.get("session")
    featured_showing = _feat.get("showing")
    featured_auditorium = _feat.get("auditorium")
    featured_speaker_obj = _feat.get("speaker_obj")
    featured_days_until = _feat.get("days_until", 0)
    featured_hours_until = _feat.get("hours_until", 0)

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
        showing = db.query(Showing).get(fb.showing_id)
        session_obj = showing.session if showing else None
        if user and session_obj:
            featured_feedback.append({
                "rating": fb.rating,
                "comment": fb.comment,
                "user_name": user.full_name or user.username,
                "college": user.college or "",
                "session_title": session_obj.title,
            })

    total_attendees = db.query(func.count(func.distinct(Booking.user_id))).filter(Booking.payment_status == "paid").scalar() or 0
    total_speakers = db.query(func.count(Speaker.id)).scalar() or 0
    total_sessions = db.query(func.count(Session.id)).scalar() or 0

    return templates.TemplateResponse(
        "public/home.html",
        template_ctx(
            request,
            sessions=sessions_with_info,
            featured_session=featured_session,
            featured_showing=featured_showing,
            featured_auditorium=featured_auditorium,
            featured_speaker_obj=featured_speaker_obj,
            featured_days_until=featured_days_until,
            featured_hours_until=featured_hours_until,
            testimonials=testimonials,
            featured_feedback=featured_feedback,
            total_attendees=total_attendees,
            total_speakers=total_speakers,
            total_sessions=total_sessions,
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
    date_filter: str | None = Query(None, alias="date"),
    city_id: int | None = Query(None, alias="city_id"),
    college_id: int | None = Query(None, alias="college_id"),
):
    now = now_ist()
    query = (
        db.query(Showing)
        .join(Session)
        .join(Auditorium)
        .outerjoin(College, Auditorium.college_id == College.id)
        .filter(
            Showing.status == "published",
            Showing.start_time > now,
        )
    )
    if q:
        query = query.filter(
            Session.title.ilike(f"%{q}%")
            | Session.speaker_name.ilike(f"%{q}%")
        )
    if date_filter:
        try:
            d = date.fromisoformat(date_filter)
            start_of_day = datetime.combine(d, time.min)
            end_of_day = datetime.combine(d, time.max)
            query = query.filter(
                Showing.start_time >= start_of_day,
                Showing.start_time <= end_of_day,
            )
        except ValueError:
            pass
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
        query = query.order_by(Showing.price)
    elif sort == "title":
        query = query.order_by(Session.title)
    else:
        query = query.order_by(Showing.start_time)

    all_showings = query.all()
    sessions_with_info = []
    for sh in all_showings:
        stats = _seat_stats(db, sh.id, sh.auditorium_id)
        sessions_with_info.append({
            "session": sh.session,
            "showing": sh,
            "auditorium": db.query(Auditorium).get(sh.auditorium_id),
            "speaker_obj": db.query(Speaker).get(sh.session.speaker_id) if sh.session and sh.session.speaker_id else None,
            "stats": stats,
            "availability": _availability_label(stats),
            "event_status": _public_status_label(sh, stats),
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
def session_detail(
    request: Request,
    session_id: int,
    db: DbSession = Depends(get_db),
):
    session_obj = db.query(Session).filter(Session.id == session_id).first()
    if not session_obj:
        return templates.TemplateResponse(
            "errors/404.html", template_ctx(request), status_code=404
        )
    showings = (
        db.query(Showing)
        .filter(Showing.session_id == session_id, Showing.status == "published")
        .order_by(Showing.start_time)
        .all()
    )
    total_showings = len(showings)

    # Pick cheapest showing as "primary" for the hero / pricing card
    primary_showing = None
    if showings:
        primary_showing = min(showings, key=lambda s: float(s.price))
    auditorium = db.query(Auditorium).get(primary_showing.auditorium_id) if primary_showing else None
    min_price = float(primary_showing.price) if primary_showing else 0

    # Stats for the primary showing only
    stats = _seat_stats(db, primary_showing.id, primary_showing.auditorium_id) if primary_showing else {"total": 0, "booked": 0, "available": 0}
    availability = _availability_label(stats)
    event_status = _public_status_label(primary_showing, stats) if primary_showing else "open"

    # Build deduplicated venues summary: {(college_name, city_name, city_state): count}
    venues = []
    if total_showings > 1:
        venue_map: dict[tuple, int] = {}
        for sh in showings:
            aud = db.query(Auditorium).get(sh.auditorium_id)
            college = aud.college if aud else None
            city = college.city if college else None
            key = (
                aud.name if aud else "Venue",
                college.name if college else "",
                city.name if city else "",
                city.state if city else "",
            )
            venue_map[key] = venue_map.get(key, 0) + 1
        for (aud_name, college_name, city_name, city_state), count in venue_map.items():
            venues.append({
                "auditorium": aud_name,
                "college": college_name,
                "city": city_name,
                "state": city_state,
                "count": count,
            })
        venues.sort(key=lambda v: (-v["count"], v["city"], v["college"]))

    user_id = request.session.get("user_id")
    on_waitlist = False
    if user_id:
        from app.models.waitlist import Waitlist
        on_waitlist = (
            db.query(Waitlist)
            .filter(Waitlist.showing_id.in_([sh.id for sh in showings]), Waitlist.user_id == user_id)
            .first()
            is not None
        )

    has_priority = False
    if user_id and availability != "sold-out":
        from app.models.waitlist import Waitlist
        now = now_ist()
        showing_ids = [sh.id for sh in showings]
        priority_entry = (
            db.query(Waitlist)
            .filter(
                Waitlist.priority_showing_id.in_(showing_ids),
                Waitlist.user_id == user_id,
                Waitlist.priority_expires_at > now,
            )
            .first()
        )
        has_priority = priority_entry is not None

        any_priority = (
            db.query(Waitlist)
            .filter(
                Waitlist.priority_showing_id.in_(showing_ids),
                Waitlist.priority_expires_at > now,
            )
            .count()
        )
        if any_priority > 0 and not has_priority:
            availability = "priority-only"

    public_recordings = (
        db.query(SessionRecording)
        .filter(SessionRecording.session_id == session_id, SessionRecording.is_public == True)
        .order_by(SessionRecording.order)
        .all()
    )
    enriched_recordings = [{"rec": r, "embed_url": _build_embed_url(r.url)} for r in public_recordings]

    custom_seat_type_ids = set()
    for sh in showings:
        for s in db.query(Seat).filter(
            Seat.auditorium_id == sh.auditorium_id,
            Seat.seat_type.like("custom_%"),
            Seat.is_active == True,
        ).all():
            if s.seat_type and s.seat_type.startswith("custom_"):
                try:
                    custom_seat_type_ids.add(int(s.seat_type.split("_", 1)[1]))
                except (ValueError, IndexError):
                    pass
    custom_seat_types = (
        db.query(SeatType).filter(SeatType.id.in_(custom_seat_type_ids)).all()
        if custom_seat_type_ids else []
    )

    return templates.TemplateResponse(
        "public/session_detail.html",
        template_ctx(
            request,
            lecture=session_obj,
            session=session_obj,
            primary_showing=primary_showing,
            auditorium=auditorium,
            stats=stats,
            availability=availability,
            event_status=event_status,
            min_price=min_price,
            total_showings=total_showings,
            venues=venues,
            on_waitlist=on_waitlist,
            has_priority=has_priority,
            recordings=enriched_recordings,
            custom_seat_types=custom_seat_types,
        ),
    )


@router.get("/sessions/{session_id}/showings")
def showings_browser(
    request: Request,
    session_id: int,
    db: DbSession = Depends(get_db),
    q: str = Query("", alias="q"),
    sort: str = Query("date", alias="sort"),
    date_filter: str | None = Query(None, alias="date"),
    city_id: int | None = Query(None, alias="city_id"),
    college_id: int | None = Query(None, alias="college_id"),
    avail_filter: str = Query("all", alias="availability"),
):
    session_obj = db.query(Session).filter(Session.id == session_id).first()
    if not session_obj:
        return templates.TemplateResponse(
            "errors/404.html", template_ctx(request), status_code=404
        )

    query = (
        db.query(Showing)
        .join(Auditorium, Showing.auditorium_id == Auditorium.id)
        .outerjoin(College, Auditorium.college_id == College.id)
        .outerjoin(City, College.city_id == City.id)
        .filter(
            Showing.session_id == session_id,
            Showing.status == "published",
        )
    )

    if q:
        like = f"%{q}%"
        query = query.filter(
            Auditorium.name.ilike(like)
            | Auditorium.location.ilike(like)
            | College.name.ilike(like)
            | City.name.ilike(like)
        )
    if date_filter:
        try:
            d = date.fromisoformat(date_filter)
            start_of_day = datetime.combine(d, time.min)
            end_of_day = datetime.combine(d, time.max)
            query = query.filter(
                Showing.start_time >= start_of_day,
                Showing.start_time <= end_of_day,
            )
        except ValueError:
            pass

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
        query = query.order_by(Showing.price)
    elif sort == "availability":
        query = query.order_by(Showing.start_time)
    else:
        query = query.order_by(Showing.start_time)

    all_showings = query.all()
    total_count = len(all_showings)

    showings_with_info = []
    for sh in all_showings:
        aud = db.query(Auditorium).get(sh.auditorium_id)
        college = aud.college if aud else None
        city_obj = college.city if college else None
        stats = _seat_stats(db, sh.id, sh.auditorium_id)
        avail = _availability_label(stats)

        if avail_filter == "available" and avail in ("sold-out",):
            continue
        if avail_filter == "filling-up" and avail != "filling-up":
            continue

        showings_with_info.append({
            "showing": sh,
            "auditorium": aud,
            "college": college,
            "city": city_obj,
            "stats": stats,
            "availability": avail,
            "event_status": _public_status_label(sh, stats),
        })

    # Sort by availability if requested (available first, then filling-up, then sold-out)
    if sort == "availability":
        avail_order = {"available": 0, "filling-up": 1, "sold-out": 2}
        showings_with_info.sort(key=lambda x: (avail_order.get(x["availability"], 3), x["showing"].start_time))

    filtered_count = len(showings_with_info)

    # Dropdown options (cascade city <-> college)
    aud_ids = [sh.auditorium_id for sh in all_showings]
    relevant_college_ids = set()
    for aid in aud_ids:
        a = db.query(Auditorium).get(aid)
        if a and a.college_id:
            relevant_college_ids.add(a.college_id)

    if city_id is not None:
        colleges = db.query(College).filter(College.is_active == True, College.city_id == city_id, College.id.in_(relevant_college_ids)).order_by(College.name).all()
    else:
        colleges = db.query(College).filter(College.is_active == True, College.id.in_(relevant_college_ids)).order_by(College.name).all()

    relevant_city_ids = {c.city_id for c in db.query(College).filter(College.id.in_(relevant_college_ids)).all()}
    if selected_college and selected_college.city_id:
        cities = db.query(City).filter(City.is_active == True, City.id == selected_college.city_id).order_by(City.name).all()
    else:
        cities = db.query(City).filter(City.is_active == True, City.id.in_(relevant_city_ids)).order_by(City.name).all()

    return templates.TemplateResponse(
        "public/showings_browser.html",
        template_ctx(
            request,
            session=session_obj,
            showings=showings_with_info,
            total_count=total_count,
            filtered_count=filtered_count,
            q=q,
            sort=sort,
            date_filter=date_filter or "",
            city_id=city_id,
            college_id=college_id,
            avail_filter=avail_filter,
            cities=cities,
            colleges=colleges,
        ),
    )


@router.get("/events")
def events_list(request: Request, db: DbSession = Depends(get_db)):
    events = (
        db.query(Event)
        .filter(Event.status == "published")
        .order_by(Event.created_at.desc())
        .all()
    )
    events_info = []
    for ev in events:
        session_count = len(ev.event_showings)
        events_info.append({
            "event": ev,
            "session_count": session_count,
            "college": ev.college,
        })
    return templates.TemplateResponse(
        "public/events.html",
        template_ctx(request, events=events_info),
    )


@router.get("/events/{event_id}")
def event_detail(request: Request, event_id: int, db: DbSession = Depends(get_db)):
    ev = db.query(Event).filter(Event.id == event_id, Event.status == "published").first()
    if not ev:
        return templates.TemplateResponse(
            "errors/404.html", template_ctx(request), status_code=404
        )
    sessions_info = []
    for es in ev.event_showings:
        sh = es.showing
        if not sh or sh.status != "published":
            continue
        sess = sh.session
        stats = _seat_stats(db, sh.id, sh.auditorium_id)
        sessions_info.append({
            "session": sess,
            "showing": sh,
            "auditorium": sh.auditorium,
            "stats": stats,
            "availability": _availability_label(stats),
        })
    return templates.TemplateResponse(
        "public/event_detail.html",
        template_ctx(request, event=ev, sessions=sessions_info),
    )


@router.get("/recordings")
def recordings_page(request: Request, db: DbSession = Depends(get_db)):
    user_id = request.session.get("user_id")
    if not user_id:
        flash(request, "Sign in to view recordings for your booked sessions.", "info")
        return RedirectResponse("/auth/login?next=/recordings", status_code=303)

    # Find sessions with at least one public SessionRecording
    session_ids_with_recordings = {
        r[0] for r in db.query(SessionRecording.session_id)
        .filter(SessionRecording.is_public == True)
        .distinct()
        .all()
    }

    # Filter to sessions where the user has a paid booking (via showing_id -> session_id)
    paid_session_ids = {
        row[0] for row in db.query(Showing.session_id)
        .join(Booking, Booking.showing_id == Showing.id)
        .filter(
            Booking.user_id == user_id,
            Booking.payment_status == "paid",
        )
        .distinct()
        .all()
    }

    session_ids = list(session_ids_with_recordings & paid_session_ids)
    sessions = (
        db.query(Session)
        .filter(Session.id.in_(session_ids))
        .all()
    ) if session_ids else []

    # Get most recent showing for each session for display (start_time, auditorium)
    enriched = []
    for s in sessions:
        latest_showing = (
            db.query(Showing)
            .filter(Showing.session_id == s.id)
            .order_by(Showing.start_time.desc())
            .first()
        )
        aud = db.query(Auditorium).get(latest_showing.auditorium_id) if latest_showing else None
        enriched.append({"session": s, "auditorium": aud, "showing": latest_showing})
    return templates.TemplateResponse(
        "public/recordings.html",
        template_ctx(request, sessions=enriched),
    )


def _schedule_query(db: DbSession, college_id: str = "", auditorium_id: str = ""):
    query = db.query(Showing).filter(
        Showing.status.in_(["published", "completed"])
    )
    if auditorium_id:
        try:
            query = query.filter(Showing.auditorium_id == int(auditorium_id))
        except ValueError:
            pass
    elif college_id:
        try:
            aud_ids = [a.id for a in db.query(Auditorium.id).filter(Auditorium.college_id == int(college_id)).all()]
            if aud_ids:
                query = query.filter(Showing.auditorium_id.in_(aud_ids))
            else:
                query = query.filter(False)
        except ValueError:
            pass
    return query.order_by(Showing.start_time).all()


@router.get("/schedule")
def schedule_page(
    request: Request,
    db: DbSession = Depends(get_db),
    college_id: str = Query("", alias="college_id"),
    auditorium_id: str = Query("", alias="auditorium_id"),
):
    showings = _schedule_query(db, college_id, auditorium_id)
    grouped = defaultdict(list)
    for sh in showings:
        aud = db.query(Auditorium).get(sh.auditorium_id)
        date_key = sh.start_time.strftime("%Y-%m-%d")
        grouped[date_key].append({"session": sh.session, "showing": sh, "auditorium": aud})

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
    showings = _schedule_query(db, college_id, auditorium_id)
    result = defaultdict(list)
    for sh in showings:
        aud = db.query(Auditorium).get(sh.auditorium_id)
        sess = sh.session
        date_key = sh.start_time.strftime("%Y-%m-%d")
        result[date_key].append({
            "id": sh.id,
            "title": sess.title if sess else "",
            "speaker": sess.speaker_name if sess else "",
            "start_time": sh.start_time.isoformat(),
            "duration_minutes": sh.effective_duration,
            "venue": aud.name if aud else "",
            "location": aud.location if aud else "",
            "status": sh.status,
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
            sess = item["session"]
            sh = item.get("showing")
            aud = item["auditorium"]
            start_time = sh.start_time if sh else None
            data.append([
                start_time.strftime("%I:%M %p") if start_time else "",
                sess.title if sess else "",
                sess.speaker_name if sess else "",
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
def public_ticket(request: Request, ticket_id: str, db: DbSession = Depends(get_db)):
    # Require authentication to prevent unauthenticated PII exposure.
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
        showing_check = db.query(Showing).get(booking.showing_id)
        if showing_check:
            aud = db.query(Auditorium).get(showing_check.auditorium_id)
            if aud and aud.college_id == viewer.supervisor_college_id:
                is_privileged = True
    if booking.user_id != viewer_id and not is_privileged:
        return templates.TemplateResponse(
            "errors/404.html", template_ctx(request), status_code=404
        )

    showing = db.query(Showing).get(booking.showing_id)
    session_obj = showing.session if showing else None
    auditorium = db.query(Auditorium).get(showing.auditorium_id) if showing else None
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
            lecture=session_obj,
            showing=showing,
            auditorium=auditorium,
            seat=seat,
            ticket_user=user,
            group_bookings=group_bookings,
        ),
    )


@router.get("/tickets/group/{group_id}")
def public_ticket_group(request: Request, group_id: str, db: DbSession = Depends(get_db)):
    # Require authentication to prevent unauthenticated PII exposure.
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
        showing_check = db.query(Showing).get(bookings[0].showing_id)
        if showing_check:
            aud = db.query(Auditorium).get(showing_check.auditorium_id)
            if aud and aud.college_id == viewer.supervisor_college_id:
                is_privileged = True
    if bookings[0].user_id != viewer_id and not is_privileged:
        return templates.TemplateResponse(
            "errors/404.html", template_ctx(request), status_code=404
        )

    showing = db.query(Showing).get(bookings[0].showing_id)
    session_obj = showing.session if showing else None
    auditorium = db.query(Auditorium).get(showing.auditorium_id) if showing else None
    user = db.query(User).get(bookings[0].user_id)
    seats = [db.query(Seat).get(b.seat_id) for b in bookings]

    return templates.TemplateResponse(
        "public/ticket_group.html",
        template_ctx(
            request,
            bookings=bookings,
            lecture=session_obj,
            showing=showing,
            auditorium=auditorium,
            seats=seats,
            ticket_user=user,
            group_id=group_id,
        ),
    )


@router.get("/terms")
def terms_page(request: Request):
    return templates.TemplateResponse("public/terms.html", template_ctx(request))


# ─── Feedback ───

@router.get("/feedback/{showing_id}")
def feedback_form(request: Request, showing_id: int, db: DbSession = Depends(get_db)):
    user_id = request.session.get("user_id")
    if not user_id:
        return RedirectResponse(f"/auth/login?next=/feedback/{showing_id}", status_code=303)

    showing = db.query(Showing).get(showing_id)
    if not showing:
        return templates.TemplateResponse("errors/404.html", template_ctx(request), status_code=404)

    session_obj = showing.session
    auditorium = db.query(Auditorium).get(showing.auditorium_id)

    existing = db.query(Feedback).filter(
        Feedback.user_id == user_id, Feedback.showing_id == showing_id
    ).first()
    if existing and existing.rating is not None:
        from app.dependencies import flash
        flash(request, "You have already submitted feedback for this session.", "info")
        return RedirectResponse("/booking/my", status_code=303)

    return templates.TemplateResponse(
        "public/feedback_form.html",
        template_ctx(
            request,
            showing=showing,
            session_obj=session_obj,
            auditorium=auditorium,
            existing=existing,
        ),
    )


@router.post("/feedback/{showing_id}")
async def feedback_submit(request: Request, showing_id: int, db: DbSession = Depends(get_db)):
    user_id = request.session.get("user_id")
    if not user_id:
        return RedirectResponse(f"/auth/login?next=/feedback/{showing_id}", status_code=303)

    showing = db.query(Showing).get(showing_id)
    if not showing:
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
        return RedirectResponse(f"/feedback/{showing_id}", status_code=303)

    existing = db.query(Feedback).filter(
        Feedback.user_id == user_id, Feedback.showing_id == showing_id
    ).first()

    if existing:
        existing.rating = rating
        existing.comment = comment or None
        existing.allow_public = allow_public
        existing.dismissed = False
    else:
        fb = Feedback(
            user_id=user_id,
            showing_id=showing_id,
            rating=rating,
            comment=comment or None,
            allow_public=allow_public,
        )
        db.add(fb)

    db.commit()
    flash(request, "Thank you for your feedback!", "success")
    return RedirectResponse("/booking/my", status_code=303)


@router.post("/feedback/{showing_id}/dismiss")
async def feedback_dismiss(request: Request, showing_id: int, db: DbSession = Depends(get_db)):
    user_id = request.session.get("user_id")
    if not user_id:
        return JSONResponse({"ok": False}, status_code=401)

    existing = db.query(Feedback).filter(
        Feedback.user_id == user_id, Feedback.showing_id == showing_id
    ).first()

    form = await request.form()
    dont_ask = form.get("dont_ask") == "1"

    if existing:
        existing.dismissed = True if dont_ask else existing.dismissed
    else:
        fb = Feedback(
            user_id=user_id,
            showing_id=showing_id,
            dismissed=dont_ask,
        )
        db.add(fb)

    db.commit()
    return JSONResponse({"ok": True})
