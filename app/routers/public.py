from datetime import datetime, date, time

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import RedirectResponse
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
from app.models.user import User

router = APIRouter(tags=["public"])


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

    cities = db.query(City).filter(City.is_active == True).order_by(City.name).all()
    colleges = db.query(College).filter(College.is_active == True).order_by(College.name).all()

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
        ),
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
