import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.config import settings
from app.models.booking import Booking
from app.models.seat import Seat


def get_seat_map(db: Session, session_id: int, auditorium_id: int):
    """Build the seat map data for rendering the interactive picker."""
    seats = (
        db.query(Seat)
        .filter(Seat.auditorium_id == auditorium_id, Seat.is_active == True)
        .order_by(Seat.row_num, Seat.col_num)
        .all()
    )
    now = datetime.now(timezone.utc)
    booked_seat_ids = set(
        sid
        for (sid,) in db.query(Booking.seat_id)
        .filter(
            Booking.session_id == session_id,
            (Booking.payment_status == "paid")
            | (
                (Booking.payment_status == "hold")
                & (Booking.held_until > now)
            ),
        )
        .all()
    )

    seat_map = []
    for seat in seats:
        status = "available"
        if seat.seat_type == "aisle":
            status = "aisle"
        elif seat.id in booked_seat_ids:
            status = "taken"
        seat_map.append(
            {
                "id": seat.id,
                "row": seat.row_num,
                "col": seat.col_num,
                "label": seat.label,
                "type": seat.seat_type,
                "status": status,
            }
        )
    return seat_map


def hold_seats(
    db: Session, user_id: int, session_id: int, seat_ids: list[int]
) -> list[Booking]:
    """Create temporary holds on selected seats. Returns list of Booking objects."""
    now = datetime.now(timezone.utc)
    held_until = now + timedelta(minutes=settings.hold_timeout_minutes)

    cancel_existing_holds(db, user_id, session_id)

    bookings = []
    for seat_id in seat_ids:
        existing = (
            db.query(Booking)
            .filter(
                Booking.seat_id == seat_id,
                Booking.session_id == session_id,
                (Booking.payment_status == "paid")
                | (
                    (Booking.payment_status == "hold")
                    & (Booking.held_until > now)
                ),
            )
            .first()
        )
        if existing:
            continue

        booking = Booking(
            user_id=user_id,
            session_id=session_id,
            seat_id=seat_id,
            payment_status="hold",
            booking_ref=uuid.uuid4().hex[:10].upper(),
            held_until=held_until,
        )
        db.add(booking)
        bookings.append(booking)

    db.commit()
    for b in bookings:
        db.refresh(b)
    return bookings


def confirm_payment(db: Session, user_id: int, session_id: int) -> list[Booking]:
    """Confirm all held bookings for a user+session (mock payment)."""
    now = datetime.now(timezone.utc)
    holds = (
        db.query(Booking)
        .filter(
            Booking.user_id == user_id,
            Booking.session_id == session_id,
            Booking.payment_status == "hold",
            Booking.held_until > now,
        )
        .all()
    )
    for b in holds:
        b.payment_status = "paid"
        b.booked_at = now
        b.held_until = None
    db.commit()
    return holds


def cancel_existing_holds(db: Session, user_id: int, session_id: int):
    """Cancel any existing holds for this user on this session."""
    now = datetime.now(timezone.utc)
    holds = (
        db.query(Booking)
        .filter(
            Booking.user_id == user_id,
            Booking.session_id == session_id,
            Booking.payment_status == "hold",
        )
        .all()
    )
    for h in holds:
        h.payment_status = "cancelled"
    db.commit()


def get_user_bookings(db: Session, user_id: int):
    """Get all confirmed bookings for a user."""
    return (
        db.query(Booking)
        .filter(Booking.user_id == user_id, Booking.payment_status == "paid")
        .order_by(Booking.booked_at.desc())
        .all()
    )
