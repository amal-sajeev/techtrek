import asyncio
import io
import re
from collections import defaultdict
from datetime import datetime, time, timedelta
from urllib.parse import urlparse, parse_qs

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import RedirectResponse, Response, StreamingResponse, JSONResponse
from sqlalchemy import func
from sqlalchemy.orm import Session as DbSession

from app.config import settings
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
from app.models.feedback import Feedback, SessionRating
from app.models.gallery_image import GalleryImage
from app.models.uploaded_image import UploadedImage
from app.models.user import User
from app.models.event_break import EventBreak
from app.models.event_addon import BookingAddOn, EventAddOn
from app.models.session_feedback import SessionFeedback
from app.models.ticket_share import TicketShare
from app.models.feedback_template import FeedbackTemplate, FeedbackResponse, QuestionResponse
from app.models.poll import Poll, PollOption, PollVote

router = APIRouter(tags=["public"], dependencies=[Depends(csrf_protection)])


@router.get("/uploads/{image_id}")
def serve_uploaded_image(image_id: int, db: DbSession = Depends(get_db)):
    img = db.query(UploadedImage).filter(UploadedImage.id == image_id).first()
    if not img:
        return Response(status_code=404)
    return Response(
        content=img.data,
        media_type=img.content_type,
        headers={"Cache-Control": "public, max-age=31536000, immutable"},
    )


from app.services.polls import (
    poll_results as _poll_results,
    notify_event_attendees_of_poll as _notify_event_attendees_of_poll,
    notify_event_attendees_poll_closed as _notify_event_attendees_poll_closed,
    build_embed_url as _build_embed_url,
)


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
        from app.models.event_session import EventSession as ES_home
        session_count = db.query(func.count(ES_home.id)).filter(ES_home.event_id == ev.id).scalar()
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

    from app.models.event_session import EventSession as ESHome
    featured_es = (
        db.query(ESHome)
        .join(Event, ESHome.event_id == Event.id)
        .filter(Event.status == "published", Event.start_date >= today)
        .order_by(ESHome.start_time)
        .limit(10)
        .all()
    )
    sessions_with_info = []
    for es in featured_es:
        sess = es.session
        ev = es.event
        speaker = db.query(Speaker).get(sess.speaker_id) if sess.speaker_id else None
        sessions_with_info.append({
            "session": sess,
            "event": ev,
            "event_session": es,
            "speaker_obj": speaker,
        })

    cities = db.query(City).filter(City.is_active == True).order_by(City.name).all()

    ev_ids = [ev.id for ev in upcoming_events]
    sess_ids = [es.session_id for es in featured_es]
    first_gallery: dict[str, str] = {}
    if ev_ids or sess_ids:
        from sqlalchemy import case
        rows = (
            db.query(GalleryImage)
            .filter(
                ((GalleryImage.owner_type == "event") & GalleryImage.owner_id.in_(ev_ids)) |
                ((GalleryImage.owner_type == "session") & GalleryImage.owner_id.in_(sess_ids))
            )
            .order_by(GalleryImage.position)
            .all()
        )
        for r in rows:
            key = f"{r.owner_type}:{r.owner_id}"
            if key not in first_gallery:
                first_gallery[key] = f"/uploads/{r.image_id}"

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
            cities=cities,
            first_gallery=first_gallery,
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
    from app.models.event_session import EventSession
    query = db.query(Session)
    if q:
        query = query.filter(
            Session.title.ilike(f"%{q}%")
            | Session.speaker_name.ilike(f"%{q}%")
        )
    if sort == "title":
        query = query.order_by(Session.title)
    else:
        query = query.order_by(Session.created_at.desc())

    all_sessions = query.all()
    sessions_with_info = []
    for sess in all_sessions:
        es = (
            db.query(EventSession).join(Event, EventSession.event_id == Event.id)
            .filter(EventSession.session_id == sess.id, Event.status == "published")
            .first()
        )
        event = es.event if es else None
        speaker = db.query(Speaker).get(sess.speaker_id) if sess.speaker_id else None
        sessions_with_info.append({
            "session": sess,
            "event": event,
            "event_session": es,
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
def session_detail(
    request: Request,
    session_id: int,
    db: DbSession = Depends(get_db),
    event_id: int = Query(0, alias="event_id"),
):
    from app.models.event_session import EventSession
    session_obj = db.query(Session).filter(Session.id == session_id).first()
    if not session_obj:
        return templates.TemplateResponse(
            "errors/404.html", template_ctx(request), status_code=404
        )

    es = None
    if event_id:
        es = db.query(EventSession).filter(
            EventSession.session_id == session_id, EventSession.event_id == event_id
        ).first()
    if not es:
        es = db.query(EventSession).filter(EventSession.session_id == session_id).first()

    event = es.event if es else None
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
        sibling_es = (
            db.query(EventSession)
            .filter(EventSession.event_id == event.id, EventSession.session_id != session_id)
            .order_by(EventSession.order, EventSession.start_time)
            .all()
        )
        for s_es in sibling_es:
            s = s_es.session
            speaker = db.query(Speaker).get(s.speaker_id) if s.speaker_id else None
            sibling_sessions.append({"session": s, "speaker_obj": speaker, "event_session": s_es})

    public_recordings = (
        db.query(SessionRecording)
        .filter(SessionRecording.session_id == session_id, SessionRecording.is_public == True)
        .order_by(SessionRecording.order)
        .all()
    )
    enriched_recordings = [{"rec": r, "embed_url": _build_embed_url(r.url)} for r in public_recordings]

    session_gallery = db.query(GalleryImage).filter(
        GalleryImage.owner_type == "session", GalleryImage.owner_id == session_id
    ).order_by(GalleryImage.position).all()
    gallery_urls = [f"/uploads/{gi.image_id}" for gi in session_gallery]

    avg_rating_row = (
        db.query(func.avg(SessionFeedback.rating), func.count(SessionFeedback.id))
        .filter(SessionFeedback.session_id == session_id, SessionFeedback.rating != None)
        .first()
    )
    avg_rating = round(float(avg_rating_row[0]), 1) if avg_rating_row[0] else None
    rating_count = avg_rating_row[1] if avg_rating_row else 0

    display_speaker_name = es.display_speaker_name if es else session_obj.speaker_name
    display_title = es.display_title if es else session_obj.title
    display_description = es.display_description if es else session_obj.description
    display_abstract = es.display_abstract if es else session_obj.abstract
    display_key_learning_outcomes = es.display_key_learning_outcomes if es else session_obj.key_learning_outcomes
    display_banner_url = es.display_banner_url if es else session_obj.banner_url
    display_duration_minutes = es.display_duration_minutes if es else session_obj.duration_minutes

    user_id = request.session.get("user_id")
    on_waitlist = False
    if user_id and event:
        from app.models.waitlist import Waitlist
        on_waitlist = (
            db.query(Waitlist)
            .filter(Waitlist.event_id == event.id, Waitlist.user_id == user_id)
            .first()
            is not None
        )

    return templates.TemplateResponse(
        "public/session_detail.html",
        template_ctx(
            request,
            lecture=session_obj,
            session=session_obj,
            event=event,
            event_session=es,
            display_title=display_title,
            display_description=display_description,
            display_abstract=display_abstract,
            display_key_learning_outcomes=display_key_learning_outcomes,
            display_banner_url=display_banner_url,
            display_duration_minutes=display_duration_minutes,
            auditorium=auditorium,
            recordings=enriched_recordings,
            stats=stats,
            availability=availability,
            event_status=event_status,
            sibling_sessions=sibling_sessions,
            total_sessions=(len(sibling_sessions) + 1) if event else 1,
            gallery_urls=gallery_urls,
            avg_rating=avg_rating,
            rating_count=rating_count,
            display_speaker_name=display_speaker_name,
            on_waitlist=on_waitlist,
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

    from app.models.event_session import EventSession as ES_list
    events_info = []
    for ev in events:
        session_count = db.query(func.count(ES_list.id)).filter(ES_list.event_id == ev.id).scalar()
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

    from app.models.event_session import EventSession
    ev_sessions = (
        db.query(EventSession)
        .filter(EventSession.event_id == event_id)
        .order_by(EventSession.order, EventSession.start_time)
        .all()
    )
    sessions_info = []
    for es in ev_sessions:
        sess = es.session
        spk_id = es.speaker_id or sess.speaker_id
        speaker = db.query(Speaker).get(spk_id) if spk_id else None
        sessions_info.append({
            "session": sess,
            "event_session": es,
            "speaker_obj": speaker,
            "display_speaker_name": es.display_speaker_name,
            "display_title": es.display_title,
            "display_description": es.display_description,
            "display_duration_minutes": es.display_duration_minutes,
            "display_banner_url": es.display_banner_url,
        })

    breaks = (
        db.query(EventBreak)
        .filter(EventBreak.event_id == event_id)
        .order_by(EventBreak.order, EventBreak.start_time)
        .all()
    )

    agenda_items = []
    for item in sessions_info:
        es = item["event_session"]
        agenda_items.append({
            "type": "session",
            "session": item["session"],
            "event_session": es,
            "speaker_obj": item["speaker_obj"],
            "display_speaker_name": item["display_speaker_name"],
            "display_title": item["display_title"],
            "display_description": item["display_description"],
            "display_duration_minutes": item["display_duration_minutes"],
            "display_banner_url": item["display_banner_url"],
            "order": es.order or 0,
            "start_time": es.start_time,
        })
    for brk in breaks:
        agenda_items.append({
            "type": "break",
            "break": brk,
            "order": brk.order or 0,
            "start_time": brk.start_time,
        })
    agenda_addons = (
        db.query(EventAddOn)
        .filter(EventAddOn.event_id == event_id, EventAddOn.is_active == True, EventAddOn.in_agenda == True)
        .all()
    )
    for addon in agenda_addons:
        agenda_items.append({
            "type": "addon",
            "addon": addon,
            "order": addon.order or 0,
            "start_time": addon.start_time,
        })
    agenda_items.sort(key=lambda x: (x["order"], x["start_time"] or datetime.min))

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

    event_gallery = db.query(GalleryImage).filter(
        GalleryImage.owner_type == "event", GalleryImage.owner_id == event_id
    ).order_by(GalleryImage.position).all()
    gallery_urls = [f"/uploads/{gi.image_id}" for gi in event_gallery]

    event_addons = db.query(EventAddOn).filter(
        EventAddOn.event_id == event_id, EventAddOn.is_active == True
    ).all()

    return templates.TemplateResponse(
        "public/event_detail.html",
        template_ctx(
            request,
            event=ev,
            auditorium=auditorium,
            sessions=sessions_info,
            agenda_items=agenda_items,
            stats=stats,
            availability=availability,
            event_status=_public_event_status(ev, stats),
            on_waitlist=on_waitlist,
            gallery_urls=gallery_urls,
            event_addons=event_addons,
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

    from app.models.event_session import EventSession
    paid_session_ids = set()
    if paid_event_ids:
        paid_session_ids = {
            row[0] for row in db.query(EventSession.session_id)
            .filter(EventSession.event_id.in_(paid_event_ids))
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
        es = db.query(EventSession).filter(EventSession.session_id == s.id).first()
        event = es.event if es else None
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
        from app.models.event_session import EventSession as ES_sched
        auditorium = db.query(Auditorium).get(ev.auditorium_id) if ev.auditorium_id else None
        ev_sess = (
            db.query(ES_sched)
            .filter(ES_sched.event_id == ev.id)
            .order_by(ES_sched.order, ES_sched.start_time)
            .all()
        )
        sessions = [es.session for es in ev_sess]
        grouped[date_key].append({"event": ev, "auditorium": auditorium, "sessions": sessions, "event_sessions": ev_sess})

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
        from app.models.event_session import EventSession as ES_api
        aud = db.query(Auditorium).get(ev.auditorium_id) if ev.auditorium_id else None
        ev_sess = db.query(ES_api).filter(ES_api.event_id == ev.id).order_by(ES_api.order, ES_api.start_time).all()
        result[date_key].append({
            "id": ev.id,
            "name": ev.name,
            "start_date": ev.start_date.isoformat(),
            "venue": aud.name if aud else "",
            "location": aud.location if aud else "",
            "status": ev.status,
            "sessions": [
                {
                    "title": es.display_title,
                    "speaker": es.display_speaker_name,
                    "start_time": es.start_time.isoformat() if es.start_time else None,
                    "duration_minutes": es.display_duration_minutes,
                }
                for es in ev_sess
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
        from app.models.event_session import EventSession as ES_pdf
        aud = db.query(Auditorium).get(ev.auditorium_id) if ev.auditorium_id else None
        ev_sess = db.query(ES_pdf).filter(ES_pdf.event_id == ev.id).order_by(ES_pdf.order, ES_pdf.start_time).all()
        grouped[date_key].append({"event": ev, "auditorium": aud, "event_sessions": ev_sess})

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
            for es in item["event_sessions"]:
                sess = es.session
                data.append([
                    es.start_time.strftime("%I:%M %p") if es.start_time else "",
                    sess.title,
                    es.speaker_name or sess.speaker_name,
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
def public_ticket(request: Request, ticket_id: str, share: str = Query(default=""), db: DbSession = Depends(get_db)):
    viewer_id = request.session.get("user_id")
    share_token = share.strip() if share else ""

    # ── Shared-ticket flow ──────────────────────────────────────────────
    if share_token:
        share_row = db.query(TicketShare).filter(
            TicketShare.share_token == share_token,
            TicketShare.ticket_id == ticket_id,
        ).first()
        if not share_row:
            flash(request, "This share link is invalid or has expired.", "danger")
            return RedirectResponse("/", status_code=303)
        if share_row.claimed_by is not None:
            if viewer_id and share_row.claimed_by == viewer_id:
                return RedirectResponse(f"/ticket/{ticket_id}", status_code=303)
            flash(request, "This shared ticket has already been claimed.", "info")
            return RedirectResponse("/", status_code=303)

        booking = (
            db.query(Booking)
            .filter(Booking.ticket_id == ticket_id, Booking.payment_status == "paid")
            .first()
        )
        if not booking:
            return templates.TemplateResponse("errors/404.html", template_ctx(request), status_code=404)

        # Logged-in user: claim the ticket if their email matches
        if viewer_id:
            from app.crypto import hash_lookup
            from app.config import settings
            viewer_user = db.query(User).filter(User.id == viewer_id).first()
            recipient_hash = hash_lookup(share_row.recipient_email.strip().lower(), settings.field_encryption_key)
            if not viewer_user or viewer_user.email_hash != recipient_hash:
                flash(request, f"This ticket was shared to {share_row.recipient_email}. Please log in with that email to claim it.", "danger")
                return RedirectResponse(f"/auth/login?next=/ticket/{ticket_id}%3Fshare%3D{share_token}", status_code=303)
            share_row.claimed_by = viewer_id
            share_row.claimed_at = now_ist()
            booking.original_user_id = booking.original_user_id or booking.user_id
            booking.user_id = viewer_id
            booking.is_shared_ticket = True
            db.commit()
            flash(request, "Ticket claimed! It's now in your account.", "success")
            return RedirectResponse(f"/ticket/{ticket_id}", status_code=303)

        # Not logged in: show ticket read-only with claim popup
        event = db.query(Event).get(booking.event_id) if booking.event_id else None
        auditorium = db.query(Auditorium).get(event.auditorium_id) if event and event.auditorium_id else None
        seat = db.query(Seat).get(booking.seat_id)
        return templates.TemplateResponse(
            "public/ticket.html",
            template_ctx(
                request,
                booking=booking,
                event=event,
                auditorium=auditorium,
                seat=seat,
                ticket_user=None,
                group_bookings=[],
                purchased_addons=[],
                show_claim_popup=True,
                share_token=share_token,
                shared_by_name=share_row.recipient_name,
                shared_to_email=share_row.recipient_email,
            ),
        )

    # ── Normal (non-shared) flow ────────────────────────────────────────
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

    purchased_addons = []
    if booking.booking_group:
        addon_rows = db.query(BookingAddOn).filter(BookingAddOn.booking_group == booking.booking_group).all()
        if addon_rows:
            addon_ids = [r.addon_id for r in addon_rows]
            purchased_addons = db.query(EventAddOn).filter(EventAddOn.id.in_(addon_ids)).all()

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
            purchased_addons=purchased_addons,
        ),
    )


@router.post("/ticket/{ticket_id}/share")
async def share_ticket(request: Request, ticket_id: str, db: DbSession = Depends(get_db)):
    user_id = request.session.get("user_id")
    if not user_id:
        return JSONResponse({"ok": False, "error": "Please log in."}, status_code=401)

    booking = (
        db.query(Booking)
        .filter(Booking.ticket_id == ticket_id, Booking.payment_status == "paid")
        .first()
    )
    if not booking:
        return JSONResponse({"ok": False, "error": "Ticket not found."}, status_code=404)

    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"ok": False, "error": "Invalid request."}, status_code=400)

    name = (body.get("name") or "").strip()
    email = (body.get("email") or "").strip()
    if not name or not email or "@" not in email:
        return JSONResponse({"ok": False, "error": "Name and valid email are required."}, status_code=400)

    sender = db.query(User).filter(User.id == user_id).first()
    sender_name = (sender.full_name or sender.username) if sender else "Someone"
    event = db.query(Event).get(booking.event_id) if booking.event_id else None
    event_name = event.name if event else "TechTrek Event"

    share = TicketShare(
        ticket_id=ticket_id,
        recipient_name=name,
        recipient_email=email,
        shared_by=user_id,
    )
    db.add(share)
    db.commit()
    db.refresh(share)

    base_url = str(request.base_url).rstrip("/")
    ticket_url = f"{base_url}/ticket/{ticket_id}?share={share.share_token}"

    from app.services.email import send_ticket_share
    send_ticket_share(email, name, sender_name, event_name, ticket_url)

    return JSONResponse({"ok": True, "message": "Ticket shared successfully!"})


@router.post("/ticket/{ticket_id}/claim")
async def claim_shared_ticket(request: Request, ticket_id: str, db: DbSession = Depends(get_db)):
    """Inline login from the shared-ticket claim popup. Authenticates the user,
    claims the ticket, and returns a JSON redirect URL."""
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"ok": False, "error": "Invalid request."}, status_code=400)

    login_id = (body.get("login_id") or "").strip()
    password = body.get("password") or ""
    share_token = (body.get("share_token") or "").strip()

    if not login_id or not password or not share_token:
        return JSONResponse({"ok": False, "error": "All fields are required."}, status_code=400)

    from app.crypto import hash_lookup
    from app.config import settings
    import bcrypt

    login_hash = hash_lookup(login_id, settings.field_encryption_key)
    user = db.query(User).filter(
        (User.username_hash == login_hash) | (User.email_hash == login_hash)
    ).first()

    if not user or not user.password_hash:
        return JSONResponse({"ok": False, "error": "Invalid username/email or password."}, status_code=401)
    if not bcrypt.checkpw(password.encode(), user.password_hash.encode()):
        return JSONResponse({"ok": False, "error": "Invalid username/email or password."}, status_code=401)

    share_row = db.query(TicketShare).filter(
        TicketShare.share_token == share_token,
        TicketShare.ticket_id == ticket_id,
    ).first()
    if not share_row:
        return JSONResponse({"ok": False, "error": "Invalid share link."}, status_code=400)
    if share_row.claimed_by is not None:
        return JSONResponse({"ok": False, "error": "This ticket has already been claimed."}, status_code=400)

    recipient_hash = hash_lookup(share_row.recipient_email.strip().lower(), settings.field_encryption_key)
    if user.email_hash != recipient_hash:
        return JSONResponse({"ok": False, "error": f"This ticket was shared to {share_row.recipient_email}. Please sign in with that email."}, status_code=403)

    booking = db.query(Booking).filter(
        Booking.ticket_id == ticket_id, Booking.payment_status == "paid"
    ).first()
    if not booking:
        return JSONResponse({"ok": False, "error": "Ticket not found."}, status_code=404)

    share_row.claimed_by = user.id
    share_row.claimed_at = now_ist()
    booking.original_user_id = booking.original_user_id or booking.user_id
    booking.user_id = user.id
    booking.is_shared_ticket = True
    db.commit()

    request.session["user_id"] = user.id
    return JSONResponse({"ok": True, "redirect": f"/ticket/{ticket_id}"})


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

    addon_rows = db.query(BookingAddOn).filter(BookingAddOn.booking_group == group_id).all()
    purchased_addons = []
    if addon_rows:
        addon_ids = [r.addon_id for r in addon_rows]
        purchased_addons = db.query(EventAddOn).filter(EventAddOn.id.in_(addon_ids)).all()

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
            purchased_addons=purchased_addons,
        ),
    )


@router.get("/terms")
def terms_page(request: Request):
    return templates.TemplateResponse("public/terms.html", template_ctx(request))


# --- Feedback (event-centric) ---

@router.get("/feedback/{event_id}")
def feedback_form(
    request: Request,
    event_id: int,
    db: DbSession = Depends(get_db),
    from_cert: str = Query("", alias="from_cert"),
):
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
    if existing and existing.submitted_at is not None:
        flash(request, "You have already submitted feedback for this event.", "info")
        if from_cert:
            return RedirectResponse(f"/booking/certificate/{from_cert}/download", status_code=303)
        return RedirectResponse("/booking/my", status_code=303)

    fb_template = None
    if event.feedback_template_id:
        fb_template = db.query(FeedbackTemplate).get(event.feedback_template_id)

    sessions = [es.session for es in event.event_sessions] if event.event_sessions else []

    return templates.TemplateResponse(
        "public/feedback_form.html",
        template_ctx(
            request,
            event=event,
            auditorium=auditorium,
            existing=existing,
            fb_template=fb_template,
            sessions=sessions,
            from_cert=from_cert or "",
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
    comment = form.get("comment", "").strip()
    allow_public = "allow_public" in form

    fb_template = None
    if event.feedback_template_id:
        fb_template = db.query(FeedbackTemplate).get(event.feedback_template_id)

    # Collect session ratings
    session_ratings = {}
    ev_sessions_list = [es.session for es in event.event_sessions] if event.event_sessions else []
    if fb_template and fb_template.session_ratings_enabled and ev_sessions_list:
        for s in ev_sessions_list:
            raw = form.get(f"session_rating_{s.id}", "")
            try:
                val = int(raw)
                if 1 <= val <= 5:
                    session_ratings[s.id] = val
            except (ValueError, TypeError):
                pass
        if fb_template.session_ratings_required and len(session_ratings) < len(ev_sessions_list):
            flash(request, "Please rate all sessions.", "danger")
            return RedirectResponse(f"/feedback/{event_id}", status_code=303)

    # Compute overall rating as average of session ratings
    rating = round(sum(session_ratings.values()) / len(session_ratings)) if session_ratings else None

    existing = db.query(Feedback).filter(
        Feedback.user_id == user_id, Feedback.event_id == event_id
    ).first()

    if existing:
        existing.rating = rating
        existing.comment = comment or None
        existing.allow_public = allow_public
        existing.dismissed = False
        existing.submitted_at = now_ist()
        db.query(SessionRating).filter(SessionRating.feedback_id == existing.id).delete()
        db.flush()
        for sid, val in session_ratings.items():
            db.add(SessionRating(feedback_id=existing.id, session_id=sid, rating=val))
    else:
        fb = Feedback(
            user_id=user_id,
            event_id=event_id,
            rating=rating,
            comment=comment or None,
            allow_public=allow_public,
            submitted_at=now_ist(),
        )
        db.add(fb)
        db.flush()
        for sid, val in session_ratings.items():
            db.add(SessionRating(feedback_id=fb.id, session_id=sid, rating=val))

    # Also write SessionFeedback rows (used by metrics)
    for sid, val in session_ratings.items():
        existing_sf = db.query(SessionFeedback).filter(
            SessionFeedback.user_id == user_id, SessionFeedback.session_id == sid
        ).first()
        if existing_sf:
            existing_sf.rating = val
        else:
            db.add(SessionFeedback(user_id=user_id, session_id=sid, event_id=event_id, rating=val))

    if fb_template:
        fr = FeedbackResponse(
            user_id=user_id,
            event_id=event_id,
            template_id=fb_template.id,
            overall_rating=rating,
            comment=comment or None,
        )
        db.add(fr)
        db.flush()
        for q in fb_template.questions:
            answer = form.get(f"question_{q.id}", "").strip()
            if answer:
                qr = QuestionResponse(
                    response_id=fr.id,
                    question_id=q.id,
                    answer_text=answer,
                )
                db.add(qr)

    db.commit()
    flash(request, "Thank you for your feedback!", "success")

    from_cert = form.get("from_cert", "").strip()
    if from_cert:
        return RedirectResponse(f"/booking/certificate/{from_cert}/download", status_code=303)
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


# --- Live Polls ---


@router.get("/sessions/{session_id}/polls/active")
def active_poll(request: Request, session_id: int, event_id: int = Query(default=0), db: DbSession = Depends(get_db)):
    filters = [Poll.session_id == session_id, Poll.is_active == True]
    if event_id:
        filters.append(Poll.event_id == event_id)
    poll = db.query(Poll).filter(*filters).first()
    if not poll:
        return JSONResponse({"poll": None})

    user_id = request.session.get("user_id")
    results = _poll_results(db, poll)
    if user_id:
        existing = db.query(PollVote).filter(
            PollVote.poll_id == poll.id, PollVote.user_id == user_id
        ).first()
        if existing:
            results["voted_option"] = existing.option_id
            results["voted_rating"] = existing.rating_value
            results["voted_text"] = existing.text_answer
    return JSONResponse({"poll": results})


@router.post("/sessions/{session_id}/polls/{poll_id}/vote")
async def vote_poll(request: Request, session_id: int, poll_id: int, event_id: int = Query(default=0), db: DbSession = Depends(get_db)):
    user_id = request.session.get("user_id")
    if not user_id:
        return JSONResponse({"ok": False, "error": "Please log in to vote."}, status_code=401)

    filters = [Poll.id == poll_id, Poll.session_id == session_id, Poll.is_active == True]
    if event_id:
        filters.append(Poll.event_id == event_id)
    poll = db.query(Poll).filter(*filters).first()
    if not poll:
        return JSONResponse({"ok": False, "error": "Poll not found or closed."}, status_code=404)

    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"ok": False, "error": "Invalid request."}, status_code=400)

    ptype = poll.poll_type or "multiple_choice"

    existing = db.query(PollVote).filter(
        PollVote.poll_id == poll_id, PollVote.user_id == user_id
    ).first()

    if ptype in ("multiple_choice", "yes_no"):
        option_id = body.get("option_id")
        if not option_id:
            return JSONResponse({"ok": False, "error": "No option selected."}, status_code=400)
        option = db.query(PollOption).filter(
            PollOption.id == option_id, PollOption.poll_id == poll_id
        ).first()
        if not option:
            return JSONResponse({"ok": False, "error": "Invalid option."}, status_code=400)
        if existing:
            existing.option_id = option_id
        else:
            db.add(PollVote(poll_id=poll_id, option_id=option_id, user_id=user_id))

    elif ptype == "rating":
        try:
            val = int(body.get("rating", 0))
        except (ValueError, TypeError):
            val = 0
        if val < 1 or val > 5:
            return JSONResponse({"ok": False, "error": "Rating must be 1-5."}, status_code=400)
        if existing:
            existing.rating_value = val
        else:
            db.add(PollVote(poll_id=poll_id, rating_value=val, user_id=user_id))

    elif ptype == "text":
        text = (body.get("text", "") or "").strip()
        if not text:
            return JSONResponse({"ok": False, "error": "Please enter a response."}, status_code=400)
        if existing:
            existing.text_answer = text
        else:
            db.add(PollVote(poll_id=poll_id, text_answer=text, user_id=user_id))

    else:
        return JSONResponse({"ok": False, "error": "Unknown poll type."}, status_code=400)

    db.commit()

    results = _poll_results(db, poll)
    if ptype in ("multiple_choice", "yes_no"):
        results["voted_option"] = body.get("option_id")
    elif ptype == "rating":
        results["voted_rating"] = int(body.get("rating", 0))
    elif ptype == "text":
        results["voted_text"] = (body.get("text", "") or "").strip()

    from app.services.poll_events import publish
    await publish(poll.session_id, poll.event_id, results)

    return JSONResponse({"ok": True, "poll": results})


_SSE_MAX_DURATION = 300  # seconds — server closes; client auto-reconnects


@router.get("/sessions/{session_id}/polls/stream")
async def poll_stream(request: Request, session_id: int, event_id: int = Query(default=0)):
    from time import monotonic
    from app.services.poll_events import subscribe, unsubscribe

    queue = subscribe(session_id, event_id)

    async def event_generator():
        deadline = monotonic() + _SSE_MAX_DURATION
        try:
            yield "data: {\"type\":\"connected\"}\n\n"
            while not await request.is_disconnected():
                if monotonic() > deadline:
                    break
                try:
                    msg = await asyncio.wait_for(queue.get(), timeout=15.0)
                    yield f"data: {msg}\n\n"
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        except (asyncio.CancelledError, GeneratorExit):
            pass
        finally:
            unsubscribe(session_id, event_id, queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/user/poll-notifications/stream")
async def user_poll_notifications_stream(request: Request):
    from time import monotonic
    from app.services.poll_events import subscribe_user, unsubscribe_user

    user_id = request.session.get("user_id")
    if not user_id:
        return JSONResponse({"error": "Login required."}, status_code=401)

    queue = subscribe_user(user_id)

    async def event_generator():
        deadline = monotonic() + _SSE_MAX_DURATION
        try:
            yield "data: {\"type\":\"connected\"}\n\n"
            while not await request.is_disconnected():
                if monotonic() > deadline:
                    break
                try:
                    msg = await asyncio.wait_for(queue.get(), timeout=15.0)
                    yield f"data: {msg}\n\n"
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        except (asyncio.CancelledError, GeneratorExit):
            pass
        finally:
            unsubscribe_user(user_id, queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


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


# --- Poll Display (presentation mode) ---

@router.get("/polls/{poll_id}/display")
def poll_display(request: Request, poll_id: int, db: DbSession = Depends(get_db)):
    user_id = request.session.get("user_id")
    if not user_id:
        return RedirectResponse(f"/auth/login?next=/polls/{poll_id}/display", status_code=303)
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        return RedirectResponse("/auth/login", status_code=303)

    is_speaker = db.query(Speaker).filter(Speaker.user_id == user.id).first() is not None
    if not (user.is_admin or user.is_supervisor or is_speaker):
        return RedirectResponse("/", status_code=303)

    poll = db.query(Poll).get(poll_id)
    if not poll:
        return RedirectResponse("/", status_code=303)

    session_obj = db.query(Session).get(poll.session_id) if poll.session_id else None
    event = db.query(Event).get(poll.event_id) if poll.event_id else None

    results = _poll_results(db, poll)

    return templates.TemplateResponse(
        "public/poll_display.html",
        {
            "request": request,
            "poll": poll,
            "results": results,
            "session_obj": session_obj,
            "event": event,
            "session_id": poll.session_id,
            "event_id": poll.event_id or 0,
        },
    )
