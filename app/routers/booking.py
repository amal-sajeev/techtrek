import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.dependencies import flash, get_db, template_ctx, templates
from app.models.auditorium import Auditorium
from app.models.booking import Booking
from app.models.seat import Seat
from app.models.session import LectureSession
from app.models.user import User
from app.models.waitlist import Waitlist
from app.services.booking import (
    _price_for_seat,
    cancel_booking_user,
    confirm_payment,
    get_seat_map,
    get_user_bookings,
    hold_seats,
)

router = APIRouter(prefix="/booking", tags=["booking"])


def _seat_price(lecture, seat_type: str) -> float:
    return _price_for_seat(lecture, seat_type)


def _require_user(request: Request, db: Session) -> User | None:
    user_id = request.session.get("user_id")
    if not user_id:
        return None
    return db.query(User).filter(User.id == user_id).first()


@router.get("/select/{session_id}")
def select_seat_page(request: Request, session_id: int, db: Session = Depends(get_db)):
    user = _require_user(request, db)
    if not user:
        flash(request, "Please sign in to book.", "warning")
        return RedirectResponse(f"/auth/login?next=/booking/select/{session_id}", status_code=303)

    lecture = db.query(LectureSession).filter(LectureSession.id == session_id).first()
    if not lecture or lecture.status != "published":
        flash(request, "Session not found.", "danger")
        return RedirectResponse("/sessions", status_code=303)

    auditorium = db.query(Auditorium).get(lecture.auditorium_id)
    seat_map = get_seat_map(db, session_id, lecture.auditorium_id)

    now = datetime.now(timezone.utc)
    priority_active = (
        db.query(Waitlist)
        .filter(
            Waitlist.priority_session_id == session_id,
            Waitlist.priority_expires_at > now,
        )
        .count()
        > 0
    )
    user_has_priority = (
        db.query(Waitlist)
        .filter(
            Waitlist.priority_session_id == session_id,
            Waitlist.user_id == user.id,
            Waitlist.priority_expires_at > now,
        )
        .first()
        is not None
    )

    if priority_active and not user_has_priority:
        flash(request, "This session is in priority booking. Only waitlisted users can book right now.", "warning")
        return RedirectResponse(f"/sessions/{session_id}", status_code=303)

    return templates.TemplateResponse(
        "booking/select_seat.html",
        template_ctx(
            request,
            lecture=lecture,
            auditorium=auditorium,
            seat_map_json=json.dumps(seat_map),
            total_rows=auditorium.total_rows,
            total_cols=auditorium.total_cols,
            stage_cols=auditorium.stage_cols,
            row_gaps=auditorium.row_gaps or "[]",
            col_gaps=auditorium.col_gaps or "[]",
            price=float(lecture.price),
            price_vip=float(lecture.price_vip) if lecture.price_vip is not None else float(lecture.price),
            price_accessible=float(lecture.price_accessible) if lecture.price_accessible is not None else float(lecture.price),
        ),
    )


@router.post("/hold/{session_id}")
async def hold_seats_route(request: Request, session_id: int, db: Session = Depends(get_db)):
    user = _require_user(request, db)
    if not user:
        return RedirectResponse("/auth/login", status_code=303)

    form = await request.form()
    seat_ids_raw = form.get("seat_ids", "")
    try:
        seat_ids = [int(x) for x in seat_ids_raw.split(",") if x.strip()]
    except ValueError:
        flash(request, "Invalid seat selection.", "danger")
        return RedirectResponse(f"/booking/select/{session_id}", status_code=303)

    if not seat_ids:
        flash(request, "Please select at least one seat.", "warning")
        return RedirectResponse(f"/booking/select/{session_id}", status_code=303)

    bookings = hold_seats(db, user.id, session_id, seat_ids)
    if not bookings:
        flash(request, "Some seats are no longer available. Please try again.", "danger")
        return RedirectResponse(f"/booking/select/{session_id}", status_code=303)

    return RedirectResponse(f"/booking/checkout/{session_id}", status_code=303)


@router.get("/checkout/{session_id}")
def checkout_page(request: Request, session_id: int, db: Session = Depends(get_db)):
    user = _require_user(request, db)
    if not user:
        return RedirectResponse("/auth/login", status_code=303)

    now = datetime.now(timezone.utc)
    holds = (
        db.query(Booking)
        .filter(
            Booking.user_id == user.id,
            Booking.session_id == session_id,
            Booking.payment_status == "hold",
            Booking.held_until > now,
        )
        .all()
    )
    if not holds:
        flash(request, "No seats held. Your hold may have expired.", "warning")
        return RedirectResponse(f"/booking/select/{session_id}", status_code=303)

    lecture = db.query(LectureSession).get(session_id)
    seats = []
    for h in holds:
        seat = db.query(Seat).get(h.seat_id)
        seats.append(seat)

    total = sum(_seat_price(lecture, s.seat_type) for s in seats)
    time_left = int((holds[0].held_until - now).total_seconds())

    return templates.TemplateResponse(
        "booking/checkout.html",
        template_ctx(
            request,
            lecture=lecture,
            seats=seats,
            total=total,
            time_left=time_left,
            booking_count=len(seats),
        ),
    )


@router.post("/pay/{session_id}")
def pay(request: Request, session_id: int, db: Session = Depends(get_db)):
    user = _require_user(request, db)
    if not user:
        return RedirectResponse("/auth/login", status_code=303)

    confirmed = confirm_payment(db, user.id, session_id)
    if not confirmed:
        flash(request, "Payment failed — your hold may have expired.", "danger")
        return RedirectResponse(f"/booking/select/{session_id}", status_code=303)

    flash(request, f"Booking confirmed! {len(confirmed)} seat(s) booked.", "success")
    return RedirectResponse(f"/booking/confirmation/{session_id}", status_code=303)


@router.get("/confirmation/{session_id}")
def confirmation_page(request: Request, session_id: int, db: Session = Depends(get_db)):
    user = _require_user(request, db)
    if not user:
        return RedirectResponse("/auth/login", status_code=303)

    bookings = (
        db.query(Booking)
        .filter(
            Booking.user_id == user.id,
            Booking.session_id == session_id,
            Booking.payment_status == "paid",
        )
        .order_by(Booking.booked_at.desc())
        .all()
    )
    if not bookings:
        return RedirectResponse("/sessions", status_code=303)

    lecture = db.query(LectureSession).get(session_id)
    auditorium = db.query(Auditorium).get(lecture.auditorium_id)
    seats = [db.query(Seat).get(b.seat_id) for b in bookings]
    total = sum(b.amount_paid or _seat_price(lecture, s.seat_type) for b, s in zip(bookings, seats))

    return templates.TemplateResponse(
        "booking/confirmation.html",
        template_ctx(
            request,
            lecture=lecture,
            auditorium=auditorium,
            bookings=bookings,
            seats=seats,
            total=total,
        ),
    )


@router.get("/my")
def my_bookings(request: Request, db: Session = Depends(get_db)):
    user = _require_user(request, db)
    if not user:
        return RedirectResponse("/auth/login?next=/booking/my", status_code=303)

    bookings = get_user_bookings(db, user.id)
    enriched = []
    for b in bookings:
        lecture = db.query(LectureSession).get(b.session_id)
        seat = db.query(Seat).get(b.seat_id)
        auditorium = db.query(Auditorium).get(lecture.auditorium_id) if lecture else None
        enriched.append({
            "booking": b,
            "lecture": lecture,
            "seat": seat,
            "auditorium": auditorium,
        })

    return templates.TemplateResponse(
        "booking/my_bookings.html",
        template_ctx(request, bookings=enriched),
    )


@router.post("/cancel/{booking_id}")
def cancel_booking(request: Request, booking_id: int, db: Session = Depends(get_db)):
    user = _require_user(request, db)
    if not user:
        return RedirectResponse("/auth/login", status_code=303)

    result = cancel_booking_user(db, booking_id, user.id)
    flash(request, result["msg"], "success" if result["ok"] else "danger")
    return RedirectResponse("/booking/my", status_code=303)


@router.post("/waitlist/{session_id}")
def join_waitlist(request: Request, session_id: int, db: Session = Depends(get_db)):
    user = _require_user(request, db)
    if not user:
        return RedirectResponse(f"/auth/login?next=/sessions/{session_id}", status_code=303)

    existing = (
        db.query(Waitlist)
        .filter(Waitlist.session_id == session_id, Waitlist.user_id == user.id)
        .first()
    )
    if existing:
        flash(request, "You're already on the waitlist.", "info")
    else:
        entry = Waitlist(user_id=user.id, session_id=session_id)
        db.add(entry)
        db.commit()
        flash(request, "You've been added to the waitlist!", "success")

    return RedirectResponse(f"/sessions/{session_id}", status_code=303)
