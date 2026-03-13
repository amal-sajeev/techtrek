import json
import io
import uuid

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse, RedirectResponse, StreamingResponse
from sqlalchemy.orm import Session

from app.config import settings
from app.csrf import csrf_protection
from app.dependencies import flash, get_db, now_ist, template_ctx, templates
from app.services.activity_log import log_activity
from app.models.auditorium import Auditorium
from app.models.booking import Booking, _generate_ticket_id
from app.models.seat import Seat
from app.models.seat_type import SeatType
from app.models.session import LectureSession
from app.models.event import Event
from app.models.event_session import EventSession
from app.models.user import User
from app.models.waitlist import Waitlist
from app.services.booking import (
    _price_for_seat,
    cancel_booking_user,
    cancel_group_bookings,
    confirm_payment,
    get_seat_map,
    get_user_bookings,
    hold_seats,
)
from app.services.invoice import generate_invoice_pdf
from app.services.razorpay import create_order as rz_create_order
from app.services.razorpay import verify_payment as rz_verify_payment

router = APIRouter(prefix="/booking", tags=["booking"], dependencies=[Depends(csrf_protection)])


def _seat_price(lecture, seat_type: str, db=None) -> float:
    return _price_for_seat(lecture, seat_type, db=db)



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

    now = now_ist()
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

    custom_types = db.query(SeatType).filter(SeatType.is_custom == True).order_by(SeatType.name).all()
    custom_types_data = [
        {"id": st.id, "name": st.name, "colour": st.colour, "icon": st.icon,
         "price": float(st.price) if st.price is not None else None}
        for st in custom_types
    ]

    return templates.TemplateResponse(
        "booking/select_seat.html",
        template_ctx(
            request,
            lecture=lecture,
            auditorium=auditorium,
            seat_map=seat_map,
            custom_types=custom_types_data,
            total_rows=auditorium.total_rows,
            total_cols=auditorium.total_cols,
            stage_cols=auditorium.stage_cols,
            stage_offset=auditorium.stage_offset or 0,
            stage_label=auditorium.stage_label or "Stage",
            entry_exit_config=auditorium.entry_exit_config or [],
            row_gaps=json.loads(auditorium.row_gaps) if auditorium.row_gaps else [],
            col_gaps=json.loads(auditorium.col_gaps) if auditorium.col_gaps else [],
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

    log_activity(db, category="booking", action="hold", description=f"Held {len(bookings)} seat(s) for session #{session_id}", request=request, user_id=user.id, target_type="session", target_id=session_id)
    db.commit()
    return RedirectResponse(f"/booking/checkout/{session_id}", status_code=303)


@router.get("/checkout/{session_id}")
def checkout_page(request: Request, session_id: int, db: Session = Depends(get_db)):
    user = _require_user(request, db)
    if not user:
        return RedirectResponse("/auth/login", status_code=303)

    now = now_ist()
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
    if not lecture:
        flash(request, "Session no longer available.", "danger")
        return RedirectResponse("/sessions", status_code=303)

    seats = []
    for h in holds:
        seat = db.query(Seat).get(h.seat_id)
        seats.append(seat)

    custom_types_map = {f"custom_{st.id}": st.name for st in db.query(SeatType).filter(SeatType.is_custom == True).all()}

    base_total = sum(_seat_price(lecture, s.seat_type, db=db) for s in seats)
    fee_pct = float(lecture.processing_fee_pct) if lecture.processing_fee_pct else 0
    processing_fee = round(base_total * fee_pct / 100, 2)
    total = base_total + processing_fee
    held = holds[0].held_until
    time_left = int((held - now).total_seconds())

    return templates.TemplateResponse(
        "booking/checkout.html",
        template_ctx(
            request,
            lecture=lecture,
            seats=seats,
            base_total=base_total,
            processing_fee=processing_fee,
            fee_pct=fee_pct,
            total=total,
            time_left=time_left,
            booking_count=len(seats),
            razorpay_key_id=settings.razorpay_key_id,
            user_email=user.email if user else "",
            custom_types_map=custom_types_map,
        ),
    )


@router.post("/create-order/{session_id}")
def create_order(request: Request, session_id: int, db: Session = Depends(get_db)):
    user = _require_user(request, db)
    if not user:
        return JSONResponse({"error": "Not authenticated"}, status_code=401)

    now = now_ist()
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
        return JSONResponse({"error": "No seats held. Your hold may have expired."}, status_code=400)

    lecture = db.query(LectureSession).get(session_id)
    if not lecture:
        return JSONResponse({"error": "Session not found."}, status_code=404)

    seats = [db.query(Seat).get(h.seat_id) for h in holds]
    base = sum(_seat_price(lecture, s.seat_type, db=db) for s in seats)
    fee_pct = float(lecture.processing_fee_pct) if lecture.processing_fee_pct else 0
    total_paise = int(round(base * (1 + fee_pct / 100), 2) * 100)
    receipt = f"sess{session_id}_user{user.id}"

    try:
        order = rz_create_order(total_paise, receipt)
    except Exception:
        return JSONResponse({"error": "Payment gateway error. Please try again."}, status_code=502)

    # Persist the order_id against all holds so verify-payment can check binding
    for hold in holds:
        hold.razorpay_order_id = order["id"]
    db.commit()

    return JSONResponse({
        "order_id": order["id"],
        "amount": order["amount"],
        "currency": order["currency"],
    })


@router.post("/verify-payment/{session_id}")
async def verify_payment_route(request: Request, session_id: int, db: Session = Depends(get_db)):
    user = _require_user(request, db)
    if not user:
        return JSONResponse({"error": "Not authenticated"}, status_code=401)

    body = await request.json()
    order_id = body.get("razorpay_order_id", "")
    payment_id = body.get("razorpay_payment_id", "")
    signature = body.get("razorpay_signature", "")

    if not rz_verify_payment(order_id, payment_id, signature):
        return JSONResponse({"error": "Payment verification failed."}, status_code=400)

    # Verify order_id matches what was stored server-side against the user's holds
    now = now_ist()
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
        return JSONResponse({"error": "Hold expired before verification."}, status_code=400)
    if any(h.razorpay_order_id != order_id for h in holds):
        log_activity(db, category="booking", action="payment_tampered", description=f"Order ID mismatch on payment verify for session #{session_id}", request=request, user_id=user.id)
        db.commit()
        return JSONResponse({"error": "Payment order mismatch."}, status_code=400)

    confirmed = confirm_payment(db, user.id, session_id)
    if not confirmed:
        return JSONResponse({"error": "Hold expired before verification."}, status_code=400)

    for b in confirmed:
        b.razorpay_payment_id = payment_id
        b.razorpay_signature = signature
    log_activity(db, category="booking", action="payment", description=f"Payment verified for {len(confirmed)} seat(s), session #{session_id}", request=request, user_id=user.id, target_type="session", target_id=session_id, extra={"payment_id": payment_id})
    db.commit()

    flash(request, f"Booking confirmed! {len(confirmed)} seat(s) booked.", "success")
    return JSONResponse({"redirect": f"/booking/confirmation/{session_id}"})


@router.post("/pay/{session_id}")
def pay(request: Request, session_id: int, db: Session = Depends(get_db)):
    user = _require_user(request, db)
    if not user:
        return RedirectResponse("/auth/login", status_code=303)

    confirmed = confirm_payment(db, user.id, session_id)
    if not confirmed:
        flash(request, "Payment failed — your hold may have expired.", "danger")
        return RedirectResponse(f"/booking/select/{session_id}", status_code=303)

    log_activity(db, category="booking", action="payment", description=f"Free booking confirmed for {len(confirmed)} seat(s), session #{session_id}", request=request, user_id=user.id, target_type="session", target_id=session_id)
    db.commit()
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
    if not lecture:
        flash(request, "Session no longer available.", "danger")
        return RedirectResponse("/sessions", status_code=303)

    auditorium = db.query(Auditorium).get(lecture.auditorium_id)
    seats = [db.query(Seat).get(b.seat_id) for b in bookings]
    total = sum(b.amount_paid or _seat_price(lecture, s.seat_type) for b, s in zip(bookings, seats))
    custom_types_map = {f"custom_{st.id}": st.name for st in db.query(SeatType).filter(SeatType.is_custom == True).all()}

    return templates.TemplateResponse(
        "booking/confirmation.html",
        template_ctx(
            request,
            lecture=lecture,
            auditorium=auditorium,
            bookings=bookings,
            seats=seats,
            total=total,
            custom_types_map=custom_types_map,
        ),
    )


@router.get("/invoice/{session_id}")
def download_invoice(request: Request, session_id: int, db: Session = Depends(get_db)):
    user = _require_user(request, db)
    if not user:
        return RedirectResponse("/auth/login", status_code=303)

    bookings = (
        db.query(Booking)
        .filter(
            Booking.user_id == user.id,
            Booking.session_id == session_id,
            Booking.payment_status.in_(["paid", "refunded"]),
        )
        .order_by(Booking.booked_at.desc())
        .all()
    )
    if not bookings:
        flash(request, "No bookings found for this session.", "warning")
        return RedirectResponse("/booking/my", status_code=303)

    lecture = db.query(LectureSession).get(session_id)
    auditorium = db.query(Auditorium).get(lecture.auditorium_id) if lecture else None
    if not lecture or not auditorium:
        flash(request, "Session not found.", "danger")
        return RedirectResponse("/booking/my", status_code=303)

    seats = [db.query(Seat).get(b.seat_id) for b in bookings]
    custom_types_map = {f"custom_{st.id}": st for st in db.query(SeatType).filter(SeatType.is_custom == True).all()}
    pdf_bytes = generate_invoice_pdf(bookings, user, lecture, auditorium, seats, custom_types_map, db=db)
    ref = bookings[0].booking_ref or "invoice"
    return StreamingResponse(
        io.BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="invoice-{ref}.pdf"'},
    )


@router.get("/my")
def my_bookings(request: Request, db: Session = Depends(get_db)):
    user = _require_user(request, db)
    if not user:
        return RedirectResponse("/auth/login?next=/booking/my", status_code=303)

    bookings = get_user_bookings(db, user.id)

    from collections import OrderedDict
    groups: OrderedDict[str, list] = OrderedDict()
    for b in bookings:
        key = f"{b.session_id}:{b.booking_group}" if b.booking_group else f"solo:{b.id}"
        groups.setdefault(key, []).append(b)

    grouped = []
    for key, group_bookings in groups.items():
        first = group_bookings[0]
        lecture = db.query(LectureSession).get(first.session_id)
        auditorium = db.query(Auditorium).get(lecture.auditorium_id) if lecture else None
        seats = [db.query(Seat).get(b.seat_id) for b in group_bookings]
        paid_bookings = [b for b in group_bookings if b.payment_status == "paid"]
        refunded_bookings = [b for b in group_bookings if b.payment_status == "refunded"]
        if len(paid_bookings) == len(group_bookings):
            status = "paid"
        elif len(refunded_bookings) == len(group_bookings):
            status = "refunded"
        else:
            status = "mixed"

        detail_url = (
            f"/booking/detail/group/{first.booking_group}"
            if first.booking_group
            else f"/booking/detail/{first.id}"
        )

        grouped.append({
            "bookings": group_bookings,
            "seats": seats,
            "lecture": lecture,
            "auditorium": auditorium,
            "total_paid": sum(b.amount_paid or 0 for b in group_bookings),
            "group_id": first.booking_group,
            "group_qr_data": first.group_qr_data,
            "status": status,
            "detail_url": detail_url,
            "booked_at": first.booked_at,
            "all_checked_in": all(b.checked_in for b in paid_bookings) if paid_bookings else False,
        })

    active_groups = []
    archive_groups = []
    for g in grouped:
        if g["all_checked_in"] or g["status"] == "refunded":
            archive_groups.append(g)
        else:
            active_groups.append(g)

    custom_types_map = {f"custom_{st.id}": st.name for st in db.query(SeatType).filter(SeatType.is_custom == True).all()}

    return templates.TemplateResponse(
        "booking/my_bookings.html",
        template_ctx(request, groups=active_groups, archive_groups=archive_groups, custom_types_map=custom_types_map),
    )


@router.get("/detail/group/{group_id}")
def booking_detail_group(request: Request, group_id: str, db: Session = Depends(get_db)):
    user = _require_user(request, db)
    if not user:
        return RedirectResponse("/auth/login?next=/booking/my", status_code=303)

    bookings = (
        db.query(Booking)
        .filter(
            Booking.booking_group == group_id,
            Booking.user_id == user.id,
            Booking.payment_status.in_(["paid", "refunded"]),
        )
        .order_by(Booking.id)
        .all()
    )
    if not bookings:
        flash(request, "Booking not found.", "danger")
        return RedirectResponse("/booking/my", status_code=303)

    return _render_booking_detail(request, db, bookings)


@router.get("/detail/{booking_id}")
def booking_detail_solo(request: Request, booking_id: int, db: Session = Depends(get_db)):
    user = _require_user(request, db)
    if not user:
        return RedirectResponse("/auth/login?next=/booking/my", status_code=303)

    booking = (
        db.query(Booking)
        .filter(
            Booking.id == booking_id,
            Booking.user_id == user.id,
            Booking.payment_status.in_(["paid", "refunded"]),
        )
        .first()
    )
    if not booking:
        flash(request, "Booking not found.", "danger")
        return RedirectResponse("/booking/my", status_code=303)

    return _render_booking_detail(request, db, [booking])


def _render_booking_detail(request: Request, db: Session, bookings: list[Booking]):
    first = bookings[0]
    lecture = db.query(LectureSession).get(first.session_id)
    auditorium = db.query(Auditorium).get(lecture.auditorium_id) if lecture else None
    seats = [db.query(Seat).get(b.seat_id) for b in bookings]
    total = sum(b.amount_paid or 0 for b in bookings)
    paid_bookings = [b for b in bookings if b.payment_status == "paid"]
    custom_types_map = {f"custom_{st.id}": st.name for st in db.query(SeatType).filter(SeatType.is_custom == True).all()}

    return templates.TemplateResponse(
        "booking/booking_detail.html",
        template_ctx(
            request,
            bookings=bookings,
            seats=seats,
            lecture=lecture,
            auditorium=auditorium,
            total=total,
            group_qr_data=first.group_qr_data if len(bookings) > 1 else None,
            group_id=first.booking_group,
            is_group=len(bookings) > 1,
            has_cancellable=len(paid_bookings) > 0,
            custom_types_map=custom_types_map,
        ),
    )


@router.post("/cancel/{booking_id}")
def cancel_booking(request: Request, booking_id: int, db: Session = Depends(get_db)):
    user = _require_user(request, db)
    if not user:
        return RedirectResponse("/auth/login", status_code=303)

    result = cancel_booking_user(db, booking_id, user.id)
    if result["ok"]:
        log_activity(db, category="booking", action="cancel", description=f"User cancelled booking #{booking_id}", request=request, user_id=user.id, target_type="booking", target_id=booking_id)
        db.commit()
    flash(request, result["msg"], "success" if result["ok"] else "danger")
    return RedirectResponse("/booking/my", status_code=303)


@router.post("/cancel-group/{group_id}")
def cancel_group(request: Request, group_id: str, db: Session = Depends(get_db)):
    user = _require_user(request, db)
    if not user:
        return RedirectResponse("/auth/login", status_code=303)

    result = cancel_group_bookings(db, group_id, user.id)
    if result["ok"]:
        log_activity(db, category="booking", action="cancel", description=f"User cancelled group booking '{group_id}'", request=request, user_id=user.id, target_type="booking")
        db.commit()
    flash(request, result["msg"], "success" if result["ok"] else "warning")
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


@router.get("/certificate/{booking_id}")
def download_certificate(request: Request, booking_id: int, db: Session = Depends(get_db)):
    user = _require_user(request, db)
    if not user:
        return RedirectResponse("/auth/login", status_code=303)

    booking = db.query(Booking).filter(Booking.id == booking_id).first()
    if not booking or booking.user_id != user.id:
        flash(request, "Booking not found.", "danger")
        return RedirectResponse("/booking/my", status_code=303)

    if not booking.checked_in:
        flash(request, "Certificate is only available after check-in.", "warning")
        return RedirectResponse("/booking/my", status_code=303)

    if booking.payment_status != "paid":
        flash(request, "Certificate is only available for paid bookings.", "warning")
        return RedirectResponse("/booking/my", status_code=303)

    lecture = db.query(LectureSession).get(booking.session_id)
    auditorium = db.query(Auditorium).get(lecture.auditorium_id) if lecture else None
    if not lecture:
        flash(request, "Session not found.", "danger")
        return RedirectResponse("/booking/my", status_code=303)

    from app.services.certificate import generate_certificate_pdf
    pdf_bytes = generate_certificate_pdf(booking, user, lecture, auditorium)
    log_activity(db, category="booking", action="certificate", description=f"Downloaded certificate for session '{lecture.title}'", request=request, user_id=user.id, target_type="booking", target_id=booking_id)
    db.commit()
    ref = booking.booking_ref or "certificate"
    return StreamingResponse(
        io.BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="certificate-{ref}.pdf"'},
    )


# ---------------------------------------------------------------------------
# Event booking flow
# ---------------------------------------------------------------------------

@router.get("/event/{event_id}/select")
def event_select_seats(
    request: Request,
    event_id: int,
    session_ids: list[int] = Query(...),
    db: Session = Depends(get_db),
):
    user = _require_user(request, db)
    if not user:
        flash(request, "Please sign in to book.", "warning")
        return RedirectResponse(f"/events/{event_id}", status_code=303)

    ev = db.query(Event).filter(Event.id == event_id, Event.status == "published").first()
    if not ev:
        flash(request, "Event not found.", "danger")
        return RedirectResponse("/events", status_code=303)

    valid_session_ids = {
        es.session_id for es in ev.event_sessions
    }
    chosen_ids = [sid for sid in session_ids if sid in valid_session_ids]
    if not chosen_ids:
        flash(request, "Please select at least one session.", "warning")
        return RedirectResponse(f"/events/{event_id}", status_code=303)

    request.session["event_session_ids"] = chosen_ids

    sessions_data = []
    auditorium_groups = {}

    for sid in chosen_ids:
        lecture = db.query(LectureSession).filter(
            LectureSession.id == sid, LectureSession.status == "published"
        ).first()
        if not lecture:
            continue
        aud = db.query(Auditorium).get(lecture.auditorium_id)
        seat_map = get_seat_map(db, sid, lecture.auditorium_id)
        custom_types = db.query(SeatType).filter(SeatType.is_custom == True).order_by(SeatType.name).all()
        custom_types_data = [
            {"id": st.id, "name": st.name, "colour": st.colour, "icon": st.icon,
             "price": float(st.price) if st.price is not None else None}
            for st in custom_types
        ]

        sess_info = {
            "session": lecture,
            "auditorium": aud,
            "seat_map": seat_map,
            "custom_types": custom_types_data,
            "total_rows": aud.total_rows,
            "total_cols": aud.total_cols,
            "stage_cols": aud.stage_cols,
            "stage_offset": aud.stage_offset or 0,
            "stage_label": aud.stage_label or "Stage",
            "entry_exit_config": aud.entry_exit_config or [],
            "row_gaps": json.loads(aud.row_gaps) if aud.row_gaps else [],
            "col_gaps": json.loads(aud.col_gaps) if aud.col_gaps else [],
            "price": float(lecture.price),
            "price_vip": float(lecture.price_vip) if lecture.price_vip is not None else float(lecture.price),
            "price_accessible": float(lecture.price_accessible) if lecture.price_accessible is not None else float(lecture.price),
        }
        sessions_data.append(sess_info)

        aud_id = aud.id
        if aud_id not in auditorium_groups:
            auditorium_groups[aud_id] = {
                "auditorium": aud,
                "session_ids": [],
            }
        auditorium_groups[aud_id]["session_ids"].append(sid)

    if not sessions_data:
        flash(request, "No valid sessions found.", "danger")
        return RedirectResponse(f"/events/{event_id}", status_code=303)

    same_seats_available = any(len(g["session_ids"]) > 1 for g in auditorium_groups.values())

    intersection_maps = {}
    for aud_id, group in auditorium_groups.items():
        if len(group["session_ids"]) < 2:
            continue
        maps = []
        for sid in group["session_ids"]:
            sm = get_seat_map(db, sid, aud_id)
            maps.append({s["id"]: s for s in sm})
        all_seat_ids = set(maps[0].keys())
        for m in maps[1:]:
            all_seat_ids &= set(m.keys())
        merged = []
        for seat_id in all_seat_ids:
            seat = maps[0][seat_id].copy()
            for m in maps[1:]:
                if m[seat_id]["status"] == "taken":
                    seat["status"] = "taken"
                    break
            merged.append(seat)
        merged.sort(key=lambda s: (s["row"], s["col"]))
        intersection_maps[aud_id] = merged

    discount_pct = float(ev.discount_pct) if ev.discount_pct else 0

    sessions_json = []
    for sd in sessions_data:
        sessions_json.append({
            "session": {"id": sd["session"].id, "title": sd["session"].title},
            "auditorium": {"id": sd["auditorium"].id, "name": sd["auditorium"].name},
            "seat_map": sd["seat_map"],
            "custom_types": sd["custom_types"],
            "total_rows": sd["total_rows"],
            "total_cols": sd["total_cols"],
            "row_gaps": sd["row_gaps"],
            "col_gaps": sd["col_gaps"],
        })

    return templates.TemplateResponse(
        "booking/event_select_seats.html",
        template_ctx(
            request,
            event=ev,
            sessions_data=sessions_data,
            sessions_json=sessions_json,
            auditorium_groups=auditorium_groups,
            same_seats_available=same_seats_available,
            intersection_maps=intersection_maps,
            discount_pct=discount_pct,
        ),
    )


@router.post("/event/{event_id}/hold")
async def event_hold_seats(request: Request, event_id: int, db: Session = Depends(get_db)):
    user = _require_user(request, db)
    if not user:
        return RedirectResponse("/auth/login", status_code=303)

    ev = db.query(Event).filter(Event.id == event_id, Event.status == "published").first()
    if not ev:
        flash(request, "Event not found.", "danger")
        return RedirectResponse("/events", status_code=303)

    chosen_ids = request.session.get("event_session_ids", [])
    if not chosen_ids:
        flash(request, "No sessions selected.", "warning")
        return RedirectResponse(f"/events/{event_id}", status_code=303)

    form = await request.form()
    mode = form.get("seat_mode", "per_session")

    all_bookings = []
    booking_group = str(uuid.uuid4())

    def _parse_seat_ids(raw: str) -> list[int]:
        ids = []
        for x in (raw or "").split(","):
            x = x.strip()
            if not x:
                continue
            try:
                ids.append(int(x))
            except ValueError:
                continue
        return ids

    if mode == "same_seats":
        aud_seat_data = {}
        for key in form:
            if key.startswith("same_seats_aud_"):
                try:
                    aud_id = int(key.replace("same_seats_aud_", ""))
                except ValueError:
                    continue
                seat_ids = _parse_seat_ids(form.get(key, ""))
                if seat_ids:
                    aud_seat_data[aud_id] = seat_ids

        for sid in chosen_ids:
            lecture = db.query(LectureSession).get(sid)
            if not lecture:
                continue
            aud_id = lecture.auditorium_id
            seat_ids = aud_seat_data.get(aud_id, [])
            if seat_ids:
                bookings = hold_seats(db, user.id, sid, seat_ids)
                for b in bookings:
                    b.booking_group = booking_group
                    b.event_id = event_id
                all_bookings.extend(bookings)
    else:
        for sid in chosen_ids:
            raw = form.get(f"seats_session_{sid}", "")
            seat_ids = _parse_seat_ids(raw)
            if seat_ids:
                bookings = hold_seats(db, user.id, sid, seat_ids)
                for b in bookings:
                    b.booking_group = booking_group
                    b.event_id = event_id
                all_bookings.extend(bookings)

    if not all_bookings:
        flash(request, "Could not hold any seats. They may already be taken.", "danger")
        qs = "&".join(f"session_ids={sid}" for sid in chosen_ids)
        return RedirectResponse(f"/booking/event/{event_id}/select?{qs}", status_code=303)

    request.session["event_booking_group"] = booking_group
    log_activity(
        db, category="booking", action="event_hold",
        description=f"Held {len(all_bookings)} seat(s) across {len(chosen_ids)} session(s) for event '{ev.name}'",
        request=request, user_id=user.id, target_type="event", target_id=event_id,
    )
    db.commit()
    return RedirectResponse(f"/booking/event/{event_id}/checkout", status_code=303)


@router.get("/event/{event_id}/checkout")
def event_checkout(request: Request, event_id: int, db: Session = Depends(get_db)):
    user = _require_user(request, db)
    if not user:
        return RedirectResponse("/auth/login", status_code=303)

    ev = db.query(Event).filter(Event.id == event_id).first()
    if not ev:
        flash(request, "Event not found.", "danger")
        return RedirectResponse("/events", status_code=303)

    group_id = request.session.get("event_booking_group")
    if not group_id:
        flash(request, "No seats held for this event.", "warning")
        return RedirectResponse(f"/events/{event_id}", status_code=303)

    now = now_ist()
    holds = (
        db.query(Booking)
        .filter(
            Booking.booking_group == group_id,
            Booking.user_id == user.id,
            Booking.payment_status == "hold",
            Booking.held_until > now,
        )
        .all()
    )
    if not holds:
        flash(request, "Your hold has expired. Please try again.", "danger")
        return RedirectResponse(f"/events/{event_id}", status_code=303)

    discount_pct = float(ev.discount_pct) if ev.discount_pct else 0
    custom_types_map = {f"custom_{st.id}": st.name for st in db.query(SeatType).filter(SeatType.is_custom == True).all()}
    sessions_breakdown = {}
    for h in holds:
        lecture = db.query(LectureSession).get(h.session_id)
        seat = db.query(Seat).get(h.seat_id)
        if not lecture or not seat:
            continue
        price = _seat_price(lecture, seat.seat_type, db=db)
        discounted = round(price * (1 - discount_pct / 100), 2) if discount_pct else price
        if h.session_id not in sessions_breakdown:
            sessions_breakdown[h.session_id] = {
                "lecture": lecture,
                "seats": [],
                "subtotal": 0,
                "subtotal_discounted": 0,
            }
        sessions_breakdown[h.session_id]["seats"].append({
            "seat": seat,
            "price": price,
            "discounted": discounted,
        })
        sessions_breakdown[h.session_id]["subtotal"] += price
        sessions_breakdown[h.session_id]["subtotal_discounted"] += discounted

    base_total = sum(s["subtotal"] for s in sessions_breakdown.values())
    discounted_total = sum(s["subtotal_discounted"] for s in sessions_breakdown.values())

    avg_fee_pct = 0
    if sessions_breakdown:
        fee_pcts = []
        for s in sessions_breakdown.values():
            pct = float(s["lecture"].processing_fee_pct) if s["lecture"].processing_fee_pct else 0
            fee_pcts.append(pct)
        avg_fee_pct = sum(fee_pcts) / len(fee_pcts)
    processing_fee = round(discounted_total * avg_fee_pct / 100, 2)
    total = discounted_total + processing_fee

    held = holds[0].held_until
    time_left = int((held - now).total_seconds())

    return templates.TemplateResponse(
        "booking/event_checkout.html",
        template_ctx(
            request,
            event=ev,
            sessions_breakdown=sessions_breakdown,
            base_total=base_total,
            discounted_total=discounted_total,
            discount_pct=discount_pct,
            processing_fee=processing_fee,
            fee_pct=avg_fee_pct,
            total=total,
            time_left=time_left,
            booking_count=len(holds),
            razorpay_key_id=settings.razorpay_key_id,
            user_email=user.email if user else "",
            custom_types_map=custom_types_map,
        ),
    )


@router.post("/event/{event_id}/create-order")
def event_create_order(request: Request, event_id: int, db: Session = Depends(get_db)):
    user = _require_user(request, db)
    if not user:
        return JSONResponse({"error": "Not authenticated"}, status_code=401)

    group_id = request.session.get("event_booking_group")
    if not group_id:
        return JSONResponse({"error": "No seats held."}, status_code=400)

    ev = db.query(Event).filter(Event.id == event_id).first()
    discount_pct = float(ev.discount_pct) if ev and ev.discount_pct else 0

    now = now_ist()
    holds = (
        db.query(Booking)
        .filter(
            Booking.booking_group == group_id,
            Booking.user_id == user.id,
            Booking.payment_status == "hold",
            Booking.held_until > now,
        )
        .all()
    )
    if not holds:
        return JSONResponse({"error": "Hold expired."}, status_code=400)

    base = 0
    fee_pcts = []
    for h in holds:
        lecture = db.query(LectureSession).get(h.session_id)
        seat = db.query(Seat).get(h.seat_id)
        price = _seat_price(lecture, seat.seat_type if seat else "standard", db=db)
        discounted = round(price * (1 - discount_pct / 100), 2) if discount_pct else price
        base += discounted
        fee_pcts.append(float(lecture.processing_fee_pct) if lecture and lecture.processing_fee_pct else 0)

    avg_fee = sum(fee_pcts) / len(fee_pcts) if fee_pcts else 0
    total_paise = int(round(base * (1 + avg_fee / 100), 2) * 100)
    receipt = f"event{event_id}_user{user.id}"

    try:
        order = rz_create_order(total_paise, receipt)
    except Exception:
        return JSONResponse({"error": "Payment gateway error. Please try again."}, status_code=502)

    for hold in holds:
        hold.razorpay_order_id = order["id"]
    db.commit()

    return JSONResponse({
        "order_id": order["id"],
        "amount": order["amount"],
        "currency": order["currency"],
    })


@router.post("/event/{event_id}/verify-payment")
async def event_verify_payment(request: Request, event_id: int, db: Session = Depends(get_db)):
    user = _require_user(request, db)
    if not user:
        return JSONResponse({"error": "Not authenticated"}, status_code=401)

    body = await request.json()
    order_id = body.get("razorpay_order_id", "")
    payment_id = body.get("razorpay_payment_id", "")
    signature = body.get("razorpay_signature", "")

    if not rz_verify_payment(order_id, payment_id, signature):
        return JSONResponse({"error": "Payment verification failed."}, status_code=400)

    group_id = request.session.get("event_booking_group")
    if not group_id:
        return JSONResponse({"error": "No event booking in progress."}, status_code=400)

    now = now_ist()
    holds = (
        db.query(Booking)
        .filter(
            Booking.booking_group == group_id,
            Booking.user_id == user.id,
            Booking.payment_status == "hold",
            Booking.held_until > now,
        )
        .all()
    )
    if not holds:
        return JSONResponse({"error": "Hold expired."}, status_code=400)

    if any(h.razorpay_order_id != order_id for h in holds):
        return JSONResponse({"error": "Payment order mismatch."}, status_code=400)

    ev = db.query(Event).filter(Event.id == event_id).first()
    discount_pct = float(ev.discount_pct) if ev and ev.discount_pct else 0

    confirmed = _confirm_event_holds(db, holds, discount_pct, event_id)
    for b in confirmed:
        b.razorpay_payment_id = payment_id
        b.razorpay_signature = signature

    log_activity(
        db, category="booking", action="event_payment",
        description=f"Event payment verified for {len(confirmed)} seat(s), event #{event_id}",
        request=request, user_id=user.id, target_type="event", target_id=event_id,
        extra={"payment_id": payment_id},
    )
    db.commit()

    request.session.pop("event_booking_group", None)
    request.session.pop("event_session_ids", None)
    flash(request, f"Event booking confirmed! {len(confirmed)} seat(s) booked.", "success")
    return JSONResponse({"redirect": f"/booking/event/{event_id}/confirmation"})


@router.post("/event/{event_id}/pay")
async def event_pay_free(request: Request, event_id: int, db: Session = Depends(get_db)):
    user = _require_user(request, db)
    if not user:
        return RedirectResponse("/auth/login", status_code=303)

    group_id = request.session.get("event_booking_group")
    if not group_id:
        flash(request, "No event booking in progress.", "warning")
        return RedirectResponse(f"/events/{event_id}", status_code=303)

    now = now_ist()
    holds = (
        db.query(Booking)
        .filter(
            Booking.booking_group == group_id,
            Booking.user_id == user.id,
            Booking.payment_status == "hold",
            Booking.held_until > now,
        )
        .all()
    )
    if not holds:
        flash(request, "Hold expired. Please try again.", "danger")
        return RedirectResponse(f"/events/{event_id}", status_code=303)

    ev = db.query(Event).filter(Event.id == event_id).first()
    discount_pct = float(ev.discount_pct) if ev and ev.discount_pct else 0

    confirmed = _confirm_event_holds(db, holds, discount_pct, event_id)
    log_activity(
        db, category="booking", action="event_payment",
        description=f"Free event booking confirmed for {len(confirmed)} seat(s), event #{event_id}",
        request=request, user_id=user.id, target_type="event", target_id=event_id,
    )
    db.commit()

    request.session.pop("event_booking_group", None)
    request.session.pop("event_session_ids", None)
    flash(request, f"Event booking confirmed! {len(confirmed)} seat(s) booked.", "success")
    return RedirectResponse(f"/booking/event/{event_id}/confirmation", status_code=303)


@router.get("/event/{event_id}/confirmation")
def event_confirmation(request: Request, event_id: int, db: Session = Depends(get_db)):
    user = _require_user(request, db)
    if not user:
        return RedirectResponse("/auth/login", status_code=303)

    ev = db.query(Event).filter(Event.id == event_id).first()
    if not ev:
        return RedirectResponse("/events", status_code=303)

    bookings = (
        db.query(Booking)
        .filter(
            Booking.user_id == user.id,
            Booking.event_id == event_id,
            Booking.payment_status == "paid",
        )
        .order_by(Booking.booked_at.desc())
        .all()
    )
    if not bookings:
        return RedirectResponse(f"/events/{event_id}", status_code=303)

    sessions_info = {}
    for b in bookings:
        if b.session_id not in sessions_info:
            lecture = db.query(LectureSession).get(b.session_id)
            if not lecture:
                continue
            sessions_info[b.session_id] = {
                "lecture": lecture,
                "auditorium": db.query(Auditorium).get(lecture.auditorium_id),
                "bookings": [],
                "seats": [],
            }
        if b.session_id not in sessions_info:
            continue
        seat = db.query(Seat).get(b.seat_id)
        if not seat:
            continue
        sessions_info[b.session_id]["bookings"].append(b)
        sessions_info[b.session_id]["seats"].append(seat)

    group_qr = bookings[0].group_qr_data if bookings else None
    total = sum(b.amount_paid or 0 for b in bookings)
    custom_types_map = {f"custom_{st.id}": st.name for st in db.query(SeatType).filter(SeatType.is_custom == True).all()}

    return templates.TemplateResponse(
        "booking/event_confirmation.html",
        template_ctx(
            request,
            event=ev,
            sessions_info=sessions_info,
            bookings=bookings,
            group_qr=group_qr,
            total=total,
            custom_types_map=custom_types_map,
        ),
    )


def _confirm_event_holds(db: Session, holds: list[Booking], discount_pct: float, event_id: int) -> list[Booking]:
    """Confirm all held bookings for an event, applying discount and generating QR codes."""
    from app.services.booking import _generate_qr_base64, _price_for_seat
    from app.services.invoice import _generate_invoice_number

    now = now_ist()
    group_id = holds[0].booking_group if holds else str(uuid.uuid4())
    group_qr = _generate_qr_base64(f"GROUP-{group_id}") if len(holds) > 1 else None
    invoice_num = _generate_invoice_number()

    for b in holds:
        lecture = db.query(LectureSession).get(b.session_id)
        seat = db.query(Seat).get(b.seat_id)
        price = _price_for_seat(lecture, seat.seat_type if seat else "standard", db=db, discount_pct=discount_pct)
        b.payment_status = "paid"
        b.booked_at = now
        b.held_until = None
        b.amount_paid = price
        b.event_id = event_id
        b.ticket_id = _generate_ticket_id()
        b.invoice_number = invoice_num
        b.qr_code_data = _generate_qr_base64(b.ticket_id)
        b.booking_group = group_id
        if group_qr:
            b.group_qr_data = group_qr

    db.commit()
    return holds
