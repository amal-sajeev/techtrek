from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.dependencies import get_db, template_ctx, templates
from app.models.auditorium import Auditorium
from app.models.booking import Booking
from app.models.seat import Seat
from app.models.session import LectureSession

router = APIRouter(tags=["public"])


def _seat_stats(db: Session, session_id: int, auditorium_id: int):
    total = (
        db.query(func.count(Seat.id))
        .filter(Seat.auditorium_id == auditorium_id, Seat.is_active == True, Seat.seat_type != "aisle")
        .scalar()
    )
    now = datetime.now(timezone.utc)
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


@router.get("/")
def home(request: Request, db: Session = Depends(get_db)):
    now = datetime.now(timezone.utc)
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
        sessions_with_info.append({
            "session": s,
            "auditorium": db.query(Auditorium).get(s.auditorium_id),
            "stats": stats,
            "availability": _availability_label(stats),
        })
    return templates.TemplateResponse(
        "public/home.html",
        template_ctx(request, sessions=sessions_with_info),
    )


@router.get("/sessions")
def sessions_list(
    request: Request,
    db: Session = Depends(get_db),
    q: str = Query("", alias="q"),
    sort: str = Query("date", alias="sort"),
):
    now = datetime.now(timezone.utc)
    query = db.query(LectureSession).filter(
        LectureSession.status == "published",
        LectureSession.start_time > now,
    )
    if q:
        query = query.filter(
            LectureSession.title.ilike(f"%{q}%")
            | LectureSession.speaker.ilike(f"%{q}%")
        )
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
        })
    return templates.TemplateResponse(
        "public/sessions.html",
        template_ctx(request, sessions=sessions_with_info, q=q, sort=sort),
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
        now = datetime.now(timezone.utc)
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

    return templates.TemplateResponse(
        "public/session_detail.html",
        template_ctx(
            request,
            lecture=lecture,
            auditorium=auditorium,
            stats=stats,
            availability=availability,
            on_waitlist=on_waitlist,
            has_priority=has_priority,
        ),
    )
