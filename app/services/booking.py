import io
import base64
import uuid
from datetime import datetime, timedelta

import qrcode
from sqlalchemy.orm import Session

from app.config import settings
from app.utils import now_ist
from app.models.booking import Booking, _generate_ticket_id
from app.services.invoice import _generate_invoice_number
from app.models.seat import Seat
from app.models.session import LectureSession
from app.models.user import User
from app.models.auditorium import Auditorium
from app.services.email import send_booking_confirmation, send_group_booking_confirmation, send_cancellation_confirmation, send_group_cancellation_confirmation

CANCELLATION_FEE = 100.0
TICKET_PRICE = 500.0


def get_seat_map(db: Session, session_id: int, auditorium_id: int):
    seats = (
        db.query(Seat)
        .filter(Seat.auditorium_id == auditorium_id, Seat.is_active == True)
        .order_by(Seat.row_num, Seat.col_num)
        .all()
    )
    now = now_ist()
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
    now = now_ist()
    held_until = now + timedelta(minutes=settings.hold_timeout_minutes)

    lecture = db.query(LectureSession).get(session_id)
    if not lecture:
        return []

    valid_seat_ids = set(
        sid for (sid,) in db.query(Seat.id)
        .filter(Seat.auditorium_id == lecture.auditorium_id, Seat.is_active == True, Seat.seat_type != "aisle")
        .all()
    )
    seat_ids = [sid for sid in seat_ids if sid in valid_seat_ids]
    if not seat_ids:
        return []

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


def _generate_qr_base64(data: str) -> str:
    qr = qrcode.QRCode(version=1, box_size=6, border=2)
    qr.add_data(data)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()


def _price_for_seat(lecture, seat_type: str) -> float:
    if not lecture:
        return TICKET_PRICE
    base = float(lecture.price)
    if seat_type == "vip" and lecture.price_vip is not None:
        return float(lecture.price_vip)
    if seat_type == "accessible" and lecture.price_accessible is not None:
        return float(lecture.price_accessible)
    return base


def confirm_payment(db: Session, user_id: int, session_id: int) -> list[Booking]:
    now = now_ist()
    lecture = db.query(LectureSession).get(session_id)

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
    group_id = uuid.uuid4().hex[:12].upper() if holds else None
    group_qr = None
    if len(holds) > 1 and group_id:
        group_qr = _generate_qr_base64(f"GROUP-{group_id}")

    invoice_num = _generate_invoice_number()
    for b in holds:
        seat = db.query(Seat).get(b.seat_id)
        b.payment_status = "paid"
        b.booked_at = now
        b.held_until = None
        b.amount_paid = _price_for_seat(lecture, seat.seat_type if seat else "standard")
        b.ticket_id = _generate_ticket_id()
        b.invoice_number = invoice_num
        b.qr_code_data = _generate_qr_base64(b.ticket_id)
        b.booking_group = group_id
        if group_qr:
            b.group_qr_data = group_qr
    db.commit()

    if holds:
        user = db.query(User).get(holds[0].user_id)
        auditorium = db.query(Auditorium).get(lecture.auditorium_id) if lecture else None
        invoice_pdf = None
        all_seats = [db.query(Seat).get(b.seat_id) for b in holds]
        if user and lecture and auditorium:
            try:
                from app.services.invoice import generate_invoice_pdf
                invoice_pdf = generate_invoice_pdf(holds, user, lecture, auditorium, all_seats)
            except Exception:
                pass

        session_title = lecture.title if lecture else "Session"
        if user and len(holds) > 1:
            tickets = []
            for b, seat in zip(holds, all_seats):
                if seat:
                    tickets.append({
                        "seat_label": seat.label,
                        "ticket_id": b.ticket_id,
                        "booking_ref": b.booking_ref,
                        "amount": float(b.amount_paid or 0),
                    })
            total = sum(t["amount"] for t in tickets)
            send_group_booking_confirmation(
                user.email, user.username, session_title,
                tickets, total, invoice_pdf=invoice_pdf,
            )
        elif user and len(holds) == 1 and all_seats[0]:
            send_booking_confirmation(
                user.email, user.username, session_title,
                all_seats[0].label, holds[0].ticket_id, holds[0].booking_ref,
                invoice_pdf=invoice_pdf,
            )

    return holds


def cancel_booking_user(db: Session, booking_id: int, user_id: int, *, send_email: bool = True) -> dict:
    b = db.query(Booking).filter(Booking.id == booking_id, Booking.user_id == user_id).first()
    if not b or b.payment_status != "paid":
        return {"ok": False, "msg": "Booking not found or already cancelled."}

    lecture = db.query(LectureSession).get(b.session_id)
    price = b.amount_paid or float(lecture.price) if lecture else TICKET_PRICE
    fee = CANCELLATION_FEE
    refund = max(0, price - fee)

    b.payment_status = "refunded"
    b.cancellation_fee = fee
    b.refund_amount = refund
    db.commit()

    if send_email:
        user = db.query(User).get(user_id)
        seat = db.query(Seat).get(b.seat_id)
        if user and seat:
            invoice_pdf = None
            auditorium = db.query(Auditorium).get(lecture.auditorium_id) if lecture else None
            if auditorium:
                try:
                    from app.services.invoice import generate_invoice_pdf
                    invoice_pdf = generate_invoice_pdf([b], user, lecture, auditorium, [seat])
                except Exception:
                    pass
            send_cancellation_confirmation(
                user.email, user.username,
                lecture.title if lecture else "Session",
                seat.label, b.booking_ref,
                float(price), float(fee), float(refund),
                invoice_pdf=invoice_pdf,
            )

    return {"ok": True, "msg": f"Booking cancelled. Refund of ₹{refund:.0f} will be processed (₹{fee:.0f} cancellation fee).", "refund": refund, "fee": fee}


def cancel_group_bookings(db: Session, group_id: str, user_id: int) -> dict:
    bookings = (
        db.query(Booking)
        .filter(
            Booking.booking_group == group_id,
            Booking.user_id == user_id,
            Booking.payment_status == "paid",
        )
        .all()
    )
    if not bookings:
        return {"ok": False, "msg": "No active bookings found in this group.", "cancelled": 0}

    lecture = db.query(LectureSession).get(bookings[0].session_id)
    cancelled_items = []
    total_refund = 0.0
    total_fees = 0.0

    for b in bookings:
        price = b.amount_paid or float(lecture.price) if lecture else TICKET_PRICE
        fee = CANCELLATION_FEE
        refund = max(0, price - fee)

        b.payment_status = "refunded"
        b.cancellation_fee = fee
        b.refund_amount = refund
        total_refund += refund
        total_fees += fee

        seat = db.query(Seat).get(b.seat_id)
        cancelled_items.append({
            "seat_label": seat.label if seat else "—",
            "amount_paid": float(price),
            "fee": float(fee),
            "refund": float(refund),
        })

    db.commit()

    user = db.query(User).get(user_id)
    if user:
        invoice_pdf = None
        auditorium = db.query(Auditorium).get(lecture.auditorium_id) if lecture else None
        if auditorium:
            try:
                from app.services.invoice import generate_invoice_pdf
                all_seats = [db.query(Seat).get(b.seat_id) for b in bookings]
                invoice_pdf = generate_invoice_pdf(bookings, user, lecture, auditorium, all_seats)
            except Exception:
                pass
        send_group_cancellation_confirmation(
            user.email, user.username,
            lecture.title if lecture else "Session",
            cancelled_items, total_fees, total_refund,
            invoice_pdf=invoice_pdf,
        )

    count = len(cancelled_items)
    return {"ok": True, "msg": f"Cancelled {count} ticket(s). Total refund: ₹{total_refund:.0f}.", "cancelled": count, "refund": total_refund}


def cancel_existing_holds(db: Session, user_id: int, session_id: int):
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
    return (
        db.query(Booking)
        .filter(Booking.user_id == user_id, Booking.payment_status.in_(["paid", "refunded"]))
        .order_by(Booking.booked_at.desc())
        .all()
    )
