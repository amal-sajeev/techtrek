import io
import base64
import uuid
from datetime import timedelta

import qrcode
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as DBSession

from app.config import settings
from app.utils import now_ist
from app.models.booking import Booking, _generate_ticket_id
from app.services.invoice import _generate_invoice_number
from app.models.seat import Seat
from app.models.event import Event
from app.models.coupon import Coupon
from app.models.user import User
from app.models.auditorium import Auditorium
from app.services.email import send_booking_confirmation, send_group_booking_confirmation, send_cancellation_confirmation, send_group_cancellation_confirmation
from app.services.razorpay import process_refund as rz_process_refund

CANCELLATION_FEE = 100.0
TICKET_PRICE = 500.0


def get_seat_map(db: DBSession, event_id: int, auditorium_id: int):
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
            Booking.event_id == event_id,
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
        elif seat.seat_type == "reserved":
            status = "reserved"
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
    db: DBSession, user_id: int, event_id: int, seat_ids: list[int]
) -> list[Booking]:
    now = now_ist()
    held_until = now + timedelta(minutes=settings.hold_timeout_minutes)

    event = db.query(Event).get(event_id)
    if not event or not event.auditorium_id:
        return []

    valid_seat_ids = set(
        sid for (sid,) in db.query(Seat.id)
        .filter(Seat.auditorium_id == event.auditorium_id, Seat.is_active == True, Seat.seat_type.notin_(["aisle", "reserved"]))
        .all()
    )
    seat_ids = [sid for sid in seat_ids if sid in valid_seat_ids]
    if not seat_ids:
        return []

    cancel_existing_holds(db, user_id, event_id)

    bookings = []
    for seat_id in seat_ids:
        existing = (
            db.query(Booking)
            .filter(
                Booking.seat_id == seat_id,
                Booking.event_id == event_id,
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
            event_id=event_id,
            seat_id=seat_id,
            payment_status="hold",
            booking_ref=uuid.uuid4().hex[:10].upper(),
            held_until=held_until,
        )
        db.add(booking)
        try:
            db.flush()
        except IntegrityError:
            db.rollback()
            continue
        bookings.append(booking)

    if bookings:
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


def _price_for_seat(event, seat_type: str, db=None) -> float:
    if not event:
        return TICKET_PRICE
    base = float(event.price)
    if seat_type == "vip" and event.price_vip is not None:
        price = float(event.price_vip)
    elif seat_type == "accessible" and event.price_accessible is not None:
        price = float(event.price_accessible)
    elif seat_type and seat_type.startswith("custom_") and db is not None:
        price = base
        try:
            ct_id = int(seat_type.split("_", 1)[1])
            from app.models.seat_type import SeatType
            ct = db.query(SeatType).get(ct_id)
            if ct and ct.price is not None:
                price = float(ct.price)
        except (ValueError, IndexError):
            pass
    else:
        price = base
    return price


def validate_coupon(db: DBSession, code: str, event_id: int):
    """Validate a coupon code. Returns (coupon, error_message)."""
    now = now_ist()
    coupon = db.query(Coupon).filter(Coupon.code == code.strip().upper()).first()
    if not coupon:
        return None, "Invalid coupon code."
    if not coupon.is_active:
        return None, "This coupon is no longer active."
    if coupon.event_id and coupon.event_id != event_id:
        return None, "This coupon is not valid for this event."
    if coupon.valid_from and now < coupon.valid_from:
        return None, "This coupon is not yet valid."
    if coupon.valid_until and now > coupon.valid_until:
        return None, "This coupon has expired."
    if coupon.max_uses is not None and coupon.used_count >= coupon.max_uses:
        return None, "This coupon has reached its usage limit."
    return coupon, None


def apply_coupon_to_price(base_price: float, coupon) -> float:
    if not coupon:
        return base_price
    if coupon.discount_pct:
        return round(base_price * (1 - float(coupon.discount_pct) / 100), 2)
    if coupon.discount_amount:
        return max(0, round(base_price - float(coupon.discount_amount), 2))
    return base_price


def confirm_payment(db: DBSession, user_id: int, event_id: int, coupon=None) -> list[Booking]:
    now = now_ist()
    event = db.query(Event).get(event_id)

    holds = (
        db.query(Booking)
        .filter(
            Booking.user_id == user_id,
            Booking.event_id == event_id,
            Booking.payment_status == "hold",
            Booking.held_until > now,
        )
        .all()
    )
    # Preserve existing booking_group from holds (set during hold phase) so the
    # group UUID stays stable across hold → payment. Fall back to a new UUID only
    # when holds come from multiple sessions (different booking_group values).
    existing_groups = {h.booking_group for h in holds if h.booking_group}
    if len(existing_groups) == 1:
        group_id = existing_groups.pop()
    elif holds:
        group_id = str(uuid.uuid4())
    else:
        group_id = None
    group_qr = None
    if len(holds) > 1 and group_id:
        group_qr = _generate_qr_base64(f"GROUP-{group_id}")

    invoice_num = _generate_invoice_number()
    for b in holds:
        seat = db.query(Seat).get(b.seat_id)
        b.payment_status = "paid"
        b.booked_at = now
        b.held_until = None
        base_price = _price_for_seat(event, seat.seat_type if seat else "standard")
        b.amount_paid = apply_coupon_to_price(base_price, coupon) if coupon else base_price
        if coupon:
            b.coupon_id = coupon.id
        b.ticket_id = _generate_ticket_id()
        b.invoice_number = invoice_num
        b.qr_code_data = _generate_qr_base64(b.ticket_id)
        b.booking_group = group_id
        if group_qr:
            b.group_qr_data = group_qr

    if coupon and holds:
        coupon.used_count = (coupon.used_count or 0) + 1

    db.commit()

    if holds:
        user = db.query(User).get(holds[0].user_id)
        auditorium = db.query(Auditorium).get(event.auditorium_id) if event else None
        invoice_pdf = None
        all_seats = [db.query(Seat).get(b.seat_id) for b in holds]
        event_title = event.name if event else "Event"
        if user and event and auditorium:
            try:
                from app.services.invoice import generate_invoice_pdf
                invoice_pdf = generate_invoice_pdf(holds, user, event, auditorium, all_seats)
            except Exception:
                pass

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
                user.email, user.username, event_title,
                tickets, total, invoice_pdf=invoice_pdf,
            )
        elif user and len(holds) == 1 and all_seats[0]:
            send_booking_confirmation(
                user.email, user.username, event_title,
                all_seats[0].label, holds[0].ticket_id, holds[0].booking_ref,
                invoice_pdf=invoice_pdf,
            )

    return holds


def cancel_booking_user(db: DBSession, booking_id: int, user_id: int, *, send_email: bool = True) -> dict:
    b = db.query(Booking).filter(Booking.id == booking_id, Booking.user_id == user_id).first()
    if not b or b.payment_status != "paid":
        return {"ok": False, "msg": "Booking not found or already cancelled."}

    event = db.query(Event).get(b.event_id) if b.event_id else None
    price = b.amount_paid or (float(event.price) if event else TICKET_PRICE)
    fee = CANCELLATION_FEE
    refund = max(0, price - fee)

    rz_warning = ""
    if b.razorpay_payment_id and refund > 0:
        rz_result = rz_process_refund(b.razorpay_payment_id, int(refund * 100))
        if rz_result and isinstance(rz_result, dict):
            b.refund_id = rz_result.get("id")
            b.refund_status = "initiated"
        elif not rz_result:
            b.refund_status = "failed"
            rz_warning = " (Razorpay refund failed — process manually)"

    b.payment_status = "refunded"
    b.cancellation_fee = fee
    b.refund_amount = refund
    db.commit()

    if send_email:
        user = db.query(User).get(user_id)
        seat = db.query(Seat).get(b.seat_id)
        event_title = event.name if event else "Event"
        if user and seat:
            invoice_pdf = None
            auditorium = db.query(Auditorium).get(event.auditorium_id) if event else None
            if auditorium:
                try:
                    from app.services.invoice import generate_invoice_pdf
                    invoice_pdf = generate_invoice_pdf([b], user, event, auditorium, [seat])
                except Exception:
                    pass
            send_cancellation_confirmation(
                user.email, user.username,
                event_title,
                seat.label, b.booking_ref,
                float(price), float(fee), float(refund),
                invoice_pdf=invoice_pdf,
            )

    return {"ok": True, "msg": f"Booking cancelled. Refund of ₹{refund:.0f} will be processed (₹{fee:.0f} cancellation fee).{rz_warning}", "refund": refund, "fee": fee}


def cancel_group_bookings(db: DBSession, group_id: str, user_id: int) -> dict:
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

    event = db.query(Event).get(bookings[0].event_id) if bookings[0].event_id else None
    event_title = event.name if event else "Event"
    cancelled_items = []
    total_refund = 0.0
    total_fees = 0.0
    rz_failures = 0

    for b in bookings:
        price = b.amount_paid or (float(event.price) if event else TICKET_PRICE)
        fee = CANCELLATION_FEE
        refund = max(0, price - fee)

        if b.razorpay_payment_id and refund > 0:
            rz_result = rz_process_refund(b.razorpay_payment_id, int(refund * 100))
            if rz_result and isinstance(rz_result, dict):
                b.refund_id = rz_result.get("id")
                b.refund_status = "initiated"
            elif not rz_result:
                b.refund_status = "failed"
                rz_failures += 1

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
        auditorium = db.query(Auditorium).get(event.auditorium_id) if event else None
        if auditorium:
            try:
                from app.services.invoice import generate_invoice_pdf
                all_seats = [db.query(Seat).get(b.seat_id) for b in bookings]
                invoice_pdf = generate_invoice_pdf(bookings, user, event, auditorium, all_seats)
            except Exception:
                pass
        send_group_cancellation_confirmation(
            user.email, user.username,
            event_title,
            cancelled_items, total_fees, total_refund,
            invoice_pdf=invoice_pdf,
        )

    count = len(cancelled_items)
    rz_warning = f" ({rz_failures} Razorpay refund(s) failed — process manually)" if rz_failures else ""
    return {"ok": True, "msg": f"Cancelled {count} ticket(s). Total refund: ₹{total_refund:.0f}.{rz_warning}", "cancelled": count, "refund": total_refund}


def cancel_existing_holds(db: DBSession, user_id: int, event_id: int):
    holds = (
        db.query(Booking)
        .filter(
            Booking.user_id == user_id,
            Booking.event_id == event_id,
            Booking.payment_status == "hold",
        )
        .all()
    )
    for h in holds:
        h.payment_status = "cancelled"
    db.commit()


def get_user_bookings(db: DBSession, user_id: int):
    return (
        db.query(Booking)
        .filter(Booking.user_id == user_id, Booking.payment_status.in_(["paid", "refunded"]))
        .order_by(Booking.booked_at.desc())
        .all()
    )
