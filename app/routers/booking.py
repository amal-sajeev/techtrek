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
from app.models.event import Event
from app.models.user import User
from app.models.waitlist import Waitlist
from app.services.booking import (
    CANCELLATION_FEE,
    _generate_qr_base64,
    _price_for_seat,
    apply_coupon_to_price,
    cancel_booking_user,
    cancel_group_bookings,
    confirm_payment,
    get_seat_map,
    get_user_bookings,
    hold_seats,
    validate_coupon,
)
from app.models.feedback import Feedback
from app.models.session import Session as SessionModel
from app.models.session_feedback import SessionFeedback
from app.services.invoice import generate_invoice_pdf
from app.models.event_addon import BookingAddOn, EventAddOn
from app.services.razorpay import create_order as rz_create_order
from app.services.razorpay import verify_payment as rz_verify_payment

router = APIRouter(prefix="/booking", tags=["booking"], dependencies=[Depends(csrf_protection)])


def _get_booking_addons(db: Session, booking_group: str):
    """Return list of EventAddOn objects purchased for a booking group."""
    if not booking_group:
        return []
    rows = db.query(BookingAddOn).filter(BookingAddOn.booking_group == booking_group).all()
    if not rows:
        return []
    addon_ids = [r.addon_id for r in rows]
    return db.query(EventAddOn).filter(EventAddOn.id.in_(addon_ids)).all()


def _save_booking_addons(db: Session, request: Request, event_id: int, booking_group: str):
    selected_addon_ids = set(request.session.get("selected_addons", []))
    if not selected_addon_ids:
        return
    addons = db.query(EventAddOn).filter(
        EventAddOn.id.in_(selected_addon_ids),
        EventAddOn.event_id == event_id,
        EventAddOn.is_active == True,
    ).all()
    for addon in addons:
        db.add(BookingAddOn(booking_group=booking_group, addon_id=addon.id, quantity=1))
    request.session.pop("selected_addons", None)


def _seat_price(event, seat_type: str, db=None) -> float:
    return _price_for_seat(event, seat_type, db=db)


def _require_user(request: Request, db: Session) -> User | None:
    user_id = request.session.get("user_id")
    if not user_id:
        return None
    return db.query(User).filter(User.id == user_id, User.deleted_at.is_(None)).first()


# ---------------------------------------------------------------------------
# Event booking flow
# ---------------------------------------------------------------------------

@router.get("/event/{event_id}/select")
def event_select_seats(request: Request, event_id: int, db: Session = Depends(get_db)):
    user = _require_user(request, db)
    if not user:
        flash(request, "Please sign in to book.", "warning")
        return RedirectResponse(f"/auth/login?next=/booking/event/{event_id}/select", status_code=303)

    ev = db.query(Event).filter(Event.id == event_id, Event.status == "published").first()
    if not ev:
        flash(request, "Event not found.", "danger")
        return RedirectResponse("/events", status_code=303)

    if not ev.auditorium_id:
        flash(request, "This event has no venue configured.", "danger")
        return RedirectResponse(f"/events/{event_id}", status_code=303)

    auditorium = db.query(Auditorium).get(ev.auditorium_id)
    seat_map = get_seat_map(db, event_id, ev.auditorium_id)

    custom_types = db.query(SeatType).filter(SeatType.is_custom == True).order_by(SeatType.name).all()
    ev_cp = ev.custom_prices or {}
    custom_types_data = []
    for st in custom_types:
        key = f"custom_{st.id}"
        price = float(ev_cp[key]) if key in ev_cp else (float(st.price) if st.price is not None else None)
        custom_types_data.append({"id": st.id, "name": st.name, "colour": st.colour, "icon": st.icon, "price": price})

    return templates.TemplateResponse(
        "booking/event_select_seats.html",
        template_ctx(
            request,
            event=ev,
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
            price=float(ev.price),
            price_vip=float(ev.price_vip) if ev.price_vip is not None else float(ev.price),
            price_accessible=float(ev.price_accessible) if ev.price_accessible is not None else float(ev.price),
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

    form = await request.form()
    seat_ids_raw = form.get("seat_ids", "")
    try:
        seat_ids = [int(x) for x in seat_ids_raw.split(",") if x.strip()]
    except ValueError:
        flash(request, "Invalid seat selection.", "danger")
        return RedirectResponse(f"/booking/event/{event_id}/select", status_code=303)

    if not seat_ids:
        flash(request, "Please select at least one seat.", "warning")
        return RedirectResponse(f"/booking/event/{event_id}/select", status_code=303)

    bookings = hold_seats(db, user.id, event_id, seat_ids)
    if not bookings:
        flash(request, "Some seats are no longer available. Please try again.", "danger")
        return RedirectResponse(f"/booking/event/{event_id}/select", status_code=303)

    booking_group = str(uuid.uuid4())
    for b in bookings:
        b.booking_group = booking_group
    db.commit()

    request.session["event_booking_group"] = booking_group

    log_activity(
        db, category="booking", action="hold",
        description=f"Held {len(bookings)} seat(s) for event '{ev.name}'",
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

    custom_types_map = {f"custom_{st.id}": st.name for st in db.query(SeatType).filter(SeatType.is_custom == True).all()}

    seat_items = []
    for h in holds:
        seat = db.query(Seat).get(h.seat_id)
        if not seat:
            continue
        price = _seat_price(ev, seat.seat_type, db=db)
        seat_items.append({"seat": seat, "price": price})

    base_total = sum(item["price"] for item in seat_items)
    fee_pct = float(ev.processing_fee_pct) if ev.processing_fee_pct else 0

    held = holds[0].held_until
    time_left = int((held - now).total_seconds())

    coupon_code = request.session.get("applied_coupon_code")
    coupon_discount = 0
    discounted_total = base_total
    if coupon_code:
        coupon, err = validate_coupon(db, coupon_code, event_id)
        if coupon:
            discounted_total = sum(apply_coupon_to_price(item["price"], coupon) for item in seat_items)
            coupon_discount = base_total - discounted_total
        else:
            request.session.pop("applied_coupon_code", None)
            coupon_code = None

    available_addons = db.query(EventAddOn).filter(
        EventAddOn.event_id == event_id, EventAddOn.is_active == True
    ).all()
    selected_addon_ids = set(request.session.get("selected_addons", []))
    addon_items = []
    addon_total = 0
    for ao in available_addons:
        selected = ao.id in selected_addon_ids
        addon_items.append({"addon": ao, "selected": selected})
        if selected:
            addon_total += float(ao.price)

    processing_fee = round((discounted_total + addon_total) * fee_pct / 100, 2)
    total = discounted_total + addon_total + processing_fee

    return templates.TemplateResponse(
        "booking/event_checkout.html",
        template_ctx(
            request,
            event=ev,
            seat_items=seat_items,
            base_total=base_total,
            coupon_discount=coupon_discount,
            coupon_code=coupon_code,
            processing_fee=processing_fee,
            fee_pct=fee_pct,
            total=total,
            time_left=time_left,
            booking_count=len(holds),
            razorpay_key_id=settings.razorpay_key_id,
            user_email=user.email if user else "",
            user_phone=user.phone if user else "",
            custom_types_map=custom_types_map,
            addon_items=addon_items,
            addon_total=addon_total,
        ),
    )


@router.post("/event/{event_id}/apply-coupon")
async def apply_coupon(request: Request, event_id: int, db: Session = Depends(get_db)):
    user = _require_user(request, db)
    if not user:
        return JSONResponse({"error": "Not authenticated"}, status_code=401)

    body = await request.json()
    code = body.get("code", "").strip()
    if not code:
        request.session.pop("applied_coupon_code", None)
        return JSONResponse({"ok": True, "removed": True})

    coupon, err = validate_coupon(db, code, event_id)
    if not coupon:
        return JSONResponse({"error": err}, status_code=400)

    request.session["applied_coupon_code"] = coupon.code
    discount_desc = ""
    if coupon.discount_pct:
        discount_desc = f"{coupon.discount_pct}% off"
    elif coupon.discount_amount:
        discount_desc = f"₹{coupon.discount_amount} off"

    return JSONResponse({"ok": True, "discount": discount_desc, "code": coupon.code})


@router.post("/event/{event_id}/toggle-addon")
async def toggle_addon(request: Request, event_id: int, db: Session = Depends(get_db)):
    user = _require_user(request, db)
    if not user:
        return JSONResponse({"error": "Not authenticated"}, status_code=401)

    body = await request.json()
    addon_id = body.get("addon_id")
    if not addon_id:
        return JSONResponse({"error": "Missing addon_id"}, status_code=400)

    addon = db.query(EventAddOn).filter(
        EventAddOn.id == addon_id, EventAddOn.event_id == event_id, EventAddOn.is_active == True
    ).first()
    if not addon:
        return JSONResponse({"error": "Add-on not found"}, status_code=404)

    selected = set(request.session.get("selected_addons", []))
    if addon_id in selected:
        selected.discard(addon_id)
        toggled = False
    else:
        selected.add(addon_id)
        toggled = True
    request.session["selected_addons"] = list(selected)
    return JSONResponse({"ok": True, "selected": toggled, "addon_id": addon_id})


@router.post("/event/{event_id}/create-order")
def event_create_order(request: Request, event_id: int, db: Session = Depends(get_db)):
    user = _require_user(request, db)
    if not user:
        return JSONResponse({"error": "Not authenticated"}, status_code=401)

    group_id = request.session.get("event_booking_group")
    if not group_id:
        return JSONResponse({"error": "No seats held."}, status_code=400)

    ev = db.query(Event).filter(Event.id == event_id).first()
    if not ev:
        return JSONResponse({"error": "Event not found."}, status_code=404)

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

    coupon = None
    coupon_code = request.session.get("applied_coupon_code")
    if coupon_code:
        coupon, _ = validate_coupon(db, coupon_code, event_id)

    base = 0
    for h in holds:
        seat = db.query(Seat).get(h.seat_id)
        price = _seat_price(ev, seat.seat_type if seat else "standard", db=db)
        if coupon:
            price = apply_coupon_to_price(price, coupon)
        base += price

    selected_addon_ids = set(request.session.get("selected_addons", []))
    addon_total = 0
    if selected_addon_ids:
        addons = db.query(EventAddOn).filter(
            EventAddOn.id.in_(selected_addon_ids),
            EventAddOn.event_id == event_id,
            EventAddOn.is_active == True,
        ).all()
        addon_total = sum(float(a.price) for a in addons)

    fee_pct = float(ev.processing_fee_pct) if ev.processing_fee_pct else 0
    total_paise = int(round((base + addon_total) * (1 + fee_pct / 100), 2) * 100)
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

    coupon = None
    coupon_code = request.session.get("applied_coupon_code")
    if coupon_code:
        coupon, _ = validate_coupon(db, coupon_code, event_id)

    _save_booking_addons(db, request, event_id, group_id)
    saved_addons = _get_booking_addons(db, group_id)

    confirmed = confirm_payment(db, user.id, event_id, coupon=coupon, addons=saved_addons)
    for b in confirmed:
        b.razorpay_payment_id = payment_id
        b.razorpay_signature = signature

    log_activity(
        db, category="booking", action="event_payment",
        description=f"Payment verified for {len(confirmed)} seat(s), event #{event_id}",
        request=request, user_id=user.id, target_type="event", target_id=event_id,
        extra={"payment_id": payment_id},
    )
    db.commit()

    group_id = request.session.get("event_booking_group")
    request.session.pop("event_booking_group", None)
    request.session.pop("applied_coupon_code", None)
    flash(request, f"Booking confirmed! {len(confirmed)} seat(s) booked.", "success")
    url = f"/booking/event/{event_id}/confirmation?group_id={group_id}" if group_id else f"/booking/event/{event_id}/confirmation"
    return JSONResponse({"redirect": url})


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

    ev = db.query(Event).get(event_id)
    coupon = None
    coupon_code = request.session.get("applied_coupon_code")
    if coupon_code:
        coupon, _ = validate_coupon(db, coupon_code, event_id)

    seat_total = 0.0
    for h in holds:
        seat = db.query(Seat).get(h.seat_id)
        price = _seat_price(ev, seat.seat_type if seat else "standard", db=db)
        price = apply_coupon_to_price(price, coupon) if coupon else price
        seat_total += price
    fee_pct = float(ev.processing_fee_pct) if ev and ev.processing_fee_pct else 0
    processing_fee = round(seat_total * fee_pct / 100, 2)
    if seat_total + processing_fee > 0:
        flash(request, "This event requires payment.", "danger")
        return RedirectResponse(f"/booking/event/{event_id}/checkout", status_code=303)

    _save_booking_addons(db, request, event_id, group_id)
    saved_addons = _get_booking_addons(db, group_id)

    confirmed = confirm_payment(db, user.id, event_id, coupon=coupon, addons=saved_addons)

    log_activity(
        db, category="booking", action="event_payment",
        description=f"Free booking confirmed for {len(confirmed)} seat(s), event #{event_id}",
        request=request, user_id=user.id, target_type="event", target_id=event_id,
    )
    db.commit()

    request.session.pop("event_booking_group", None)
    request.session.pop("applied_coupon_code", None)
    request.session.pop("selected_addons", None)
    flash(request, f"Booking confirmed! {len(confirmed)} seat(s) booked.", "success")
    url = f"/booking/event/{event_id}/confirmation?group_id={group_id}" if group_id else f"/booking/event/{event_id}/confirmation"
    return RedirectResponse(url, status_code=303)


@router.get("/event/{event_id}/confirmation")
def event_confirmation(
    request: Request,
    event_id: int,
    db: Session = Depends(get_db),
    group_id: str = Query("", alias="group_id"),
):
    user = _require_user(request, db)
    if not user:
        return RedirectResponse("/auth/login", status_code=303)

    ev = db.query(Event).filter(Event.id == event_id).first()
    if not ev:
        return RedirectResponse("/events", status_code=303)

    base_query = (
        db.query(Booking)
        .filter(
            Booking.user_id == user.id,
            Booking.event_id == event_id,
            Booking.payment_status == "paid",
        )
    )
    if group_id and group_id.strip():
        bookings = base_query.filter(Booking.booking_group == group_id.strip()).order_by(Booking.id).all()
    else:
        all_paid = base_query.order_by(Booking.booked_at.desc()).all()
        if not all_paid:
            bookings = []
        else:
            first_group = all_paid[0].booking_group
            if first_group:
                bookings = [b for b in all_paid if b.booking_group == first_group]
            else:
                bookings = [all_paid[0]]
    if not bookings:
        return RedirectResponse(f"/booking/my", status_code=303)

    auditorium = db.query(Auditorium).get(ev.auditorium_id) if ev.auditorium_id else None
    seats = [db.query(Seat).get(b.seat_id) for b in bookings]
    total = sum(b.amount_paid or 0 for b in bookings)
    group_id_out = bookings[0].booking_group if bookings else None
    group_qr = _generate_qr_base64(f"GROUP-{group_id_out}") if group_id_out else None
    custom_types_map = {f"custom_{st.id}": st.name for st in db.query(SeatType).filter(SeatType.is_custom == True).all()}
    purchased_addons = _get_booking_addons(db, bookings[0].booking_group) if bookings else []

    return templates.TemplateResponse(
        "booking/event_confirmation.html",
        template_ctx(
            request,
            event=ev,
            auditorium=auditorium,
            bookings=bookings,
            seats=seats,
            group_qr=group_qr,
            group_id_out=group_id_out,
            total=total,
            custom_types_map=custom_types_map,
            purchased_addons=purchased_addons,
            cancellation_fee=CANCELLATION_FEE,
        ),
    )


# ---------------------------------------------------------------------------
# My Bookings, Detail, Cancel, Invoice, Certificate, Waitlist
# ---------------------------------------------------------------------------

@router.get("/my")
def my_bookings(request: Request, db: Session = Depends(get_db)):
    user = _require_user(request, db)
    if not user:
        return RedirectResponse("/auth/login?next=/booking/my", status_code=303)

    bookings = get_user_bookings(db, user.id)

    from collections import OrderedDict
    groups: OrderedDict[str, list] = OrderedDict()
    for b in bookings:
        key = f"{b.event_id}:{b.booking_group}" if b.booking_group else f"solo:{b.id}"
        groups.setdefault(key, []).append(b)

    grouped = []
    for key, group_bookings in groups.items():
        first = group_bookings[0]
        event = db.query(Event).get(first.event_id) if first.event_id else None
        auditorium = db.query(Auditorium).get(event.auditorium_id) if event and event.auditorium_id else None
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
        invoice_url = (
            f"/booking/invoice/group/{first.booking_group}"
            if first.booking_group
            else f"/booking/invoice/booking/{first.id}"
        )

        grouped.append({
            "bookings": group_bookings,
            "seats": seats,
            "event": event,
            "auditorium": auditorium,
            "total_paid": sum(b.amount_paid or 0 for b in group_bookings),
            "group_id": first.booking_group,
            "group_qr_data": first.group_qr_data,
            "status": status,
            "detail_url": detail_url,
            "invoice_url": invoice_url,
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
    event = db.query(Event).get(first.event_id) if first.event_id else None
    auditorium = db.query(Auditorium).get(event.auditorium_id) if event and event.auditorium_id else None
    seats = [db.query(Seat).get(b.seat_id) for b in bookings]
    total = sum(b.amount_paid or 0 for b in bookings)
    paid_bookings = [b for b in bookings if b.payment_status == "paid"]
    custom_types_map = {f"custom_{st.id}": st.name for st in db.query(SeatType).filter(SeatType.is_custom == True).all()}

    group_id = first.booking_group if len(bookings) > 1 else None
    # Always generate the group QR from the actual group_id so it stays consistent
    # with the booking_group field (avoids stale group_qr_data from earlier sessions).
    group_qr_data = _generate_qr_base64(f"GROUP-{group_id}") if group_id else None

    # Always regenerate individual QR images from ticket data so that stale or
    # incorrectly-formatted qr_code_data in the database (e.g. a plain URL string
    # written by the backfill endpoint instead of a base64 PNG) never reaches the
    # template.  The QR encodes the public certificate-verify URL so that scanning
    # with a phone camera also works.
    base = settings.base_url.rstrip("/")
    booking_qr_data = {
        b.id: _generate_qr_base64(f"{base}/certificate/verify/{b.ticket_id}")
        for b in bookings
        if b.ticket_id and b.payment_status == "paid"
    }

    purchased_addons = _get_booking_addons(db, first.booking_group)

    return templates.TemplateResponse(
        "booking/booking_detail.html",
        template_ctx(
            request,
            bookings=bookings,
            seats=seats,
            event=event,
            auditorium=auditorium,
            total=total,
            group_qr_data=group_qr_data,
            group_id=group_id,
            is_group=len(bookings) > 1,
            has_cancellable=len(paid_bookings) > 0,
            custom_types_map=custom_types_map,
            purchased_addons=purchased_addons,
            cancellation_fee=CANCELLATION_FEE,
            booking_qr_data=booking_qr_data,
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


@router.post("/waitlist/{event_id}")
def join_waitlist(request: Request, event_id: int, db: Session = Depends(get_db)):
    user = _require_user(request, db)
    if not user:
        return RedirectResponse(f"/auth/login?next=/events/{event_id}", status_code=303)

    existing = (
        db.query(Waitlist)
        .filter(Waitlist.event_id == event_id, Waitlist.user_id == user.id)
        .first()
    )
    if existing:
        flash(request, "You're already on the waitlist.", "info")
    else:
        entry = Waitlist(user_id=user.id, event_id=event_id)
        db.add(entry)
        db.commit()
        flash(request, "You've been added to the waitlist!", "success")

    back = request.headers.get("referer", "").strip()
    if back and back.startswith(("/", f"{request.base_url}")):
        return RedirectResponse(back, status_code=303)
    return RedirectResponse(f"/events/{event_id}", status_code=303)


@router.post("/waitlist/{event_id}/leave")
def leave_waitlist(request: Request, event_id: int, db: Session = Depends(get_db)):
    user = _require_user(request, db)
    if not user:
        return RedirectResponse(f"/auth/login?next=/events/{event_id}", status_code=303)

    entry = (
        db.query(Waitlist)
        .filter(Waitlist.event_id == event_id, Waitlist.user_id == user.id)
        .first()
    )
    if entry:
        db.delete(entry)
        db.commit()
        flash(request, "You've been removed from the waitlist.", "success")
    else:
        flash(request, "You're not on the waitlist for this event.", "info")

    back = request.headers.get("referer", "").strip()
    if back and back.startswith(("/", f"{request.base_url}")):
        return RedirectResponse(back, status_code=303)
    return RedirectResponse(f"/events/{event_id}", status_code=303)


def _validate_certificate_access(request, db, booking_id):
    """Common guard for all certificate endpoints. Returns (user, booking, event) or a redirect."""
    user = _require_user(request, db)
    if not user:
        return None, None, None, RedirectResponse("/auth/login", status_code=303)

    booking = db.query(Booking).filter(Booking.id == booking_id).first()
    if not booking or booking.user_id != user.id:
        flash(request, "Booking not found.", "danger")
        return None, None, None, RedirectResponse("/booking/my", status_code=303)

    if not booking.checked_in:
        flash(request, "Certificate is only available after check-in.", "warning")
        return None, None, None, RedirectResponse("/booking/my", status_code=303)

    if booking.payment_status != "paid":
        flash(request, "Certificate is only available for paid bookings.", "warning")
        return None, None, None, RedirectResponse("/booking/my", status_code=303)

    event = db.query(Event).get(booking.event_id) if booking.event_id else None
    if not event:
        flash(request, "Event not found.", "danger")
        return None, None, None, RedirectResponse("/booking/my", status_code=303)

    return user, booking, event, None


@router.get("/certificate/{booking_id}")
def certificate_feedback_page(request: Request, booking_id: int, db: Session = Depends(get_db)):
    user, booking, event, redirect = _validate_certificate_access(request, db, booking_id)
    if redirect:
        return redirect

    has_session_feedback = (
        db.query(SessionFeedback)
        .filter(SessionFeedback.user_id == user.id, SessionFeedback.event_id == event.id)
        .first()
    )
    if has_session_feedback:
        return RedirectResponse(f"/booking/certificate/{booking_id}/download", status_code=303)

    return RedirectResponse(f"/feedback/{event.id}?from_cert={booking_id}", status_code=303)


@router.get("/certificate/{booking_id}/download")
def certificate_download(request: Request, booking_id: int, db: Session = Depends(get_db)):
    user, booking, event, redirect = _validate_certificate_access(request, db, booking_id)
    if redirect:
        return redirect

    auditorium = db.query(Auditorium).get(event.auditorium_id) if event.auditorium_id else None

    from app.services.certificate import generate_certificate_pdf
    pdf_bytes = generate_certificate_pdf(booking, user, event, event, auditorium)
    log_activity(db, category="booking", action="certificate", description=f"Downloaded certificate for event '{event.name}'", request=request, user_id=user.id, target_type="booking", target_id=booking_id)
    db.commit()
    ref = booking.booking_ref or "certificate"
    return StreamingResponse(
        io.BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="certificate-{ref}.pdf"'},
    )


def _invoice_bookings_response(request: Request, db: Session, bookings: list, user_id: int):
    """Generate and return invoice PDF for the given bookings (single transaction)."""
    if not bookings:
        flash(request, "No bookings found.", "warning")
        return RedirectResponse("/booking/my", status_code=303), None
    first = bookings[0]
    event = db.query(Event).get(first.event_id) if first.event_id else None
    auditorium = db.query(Auditorium).get(event.auditorium_id) if event and event.auditorium_id else None
    if not event or not auditorium:
        flash(request, "Event not found.", "danger")
        return RedirectResponse("/booking/my", status_code=303), None
    user = db.query(User).get(user_id)
    seats = [db.query(Seat).get(b.seat_id) for b in bookings]
    custom_types_map = {f"custom_{st.id}": st for st in db.query(SeatType).filter(SeatType.is_custom == True).all()}
    purchased_addons = _get_booking_addons(db, first.booking_group) if first.booking_group else []
    pdf_bytes = generate_invoice_pdf(bookings, user, event, auditorium, seats, custom_types_map, db=db, addons=purchased_addons)
    ref = first.booking_ref or "invoice"
    return StreamingResponse(
        io.BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="invoice-{ref}.pdf"'},
    ), ref


@router.get("/invoice/group/{group_id}")
def download_invoice_group(request: Request, group_id: str, db: Session = Depends(get_db)):
    user = _require_user(request, db)
    if not user:
        return RedirectResponse("/auth/login", status_code=303)
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
    resp, _ = _invoice_bookings_response(request, db, bookings, user.id)
    return resp if isinstance(resp, StreamingResponse) else resp


@router.get("/invoice/booking/{booking_id}")
def download_invoice_booking(request: Request, booking_id: int, db: Session = Depends(get_db)):
    user = _require_user(request, db)
    if not user:
        return RedirectResponse("/auth/login", status_code=303)
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
    if booking.booking_group:
        bookings = (
            db.query(Booking)
            .filter(
                Booking.booking_group == booking.booking_group,
                Booking.user_id == user.id,
                Booking.payment_status.in_(["paid", "refunded"]),
            )
            .order_by(Booking.id)
            .all()
        )
    else:
        bookings = [booking]
    resp, _ = _invoice_bookings_response(request, db, bookings, user.id)
    return resp if isinstance(resp, StreamingResponse) else resp


@router.get("/invoice/{event_id}")
def download_invoice(
    request: Request,
    event_id: int,
    db: Session = Depends(get_db),
    group_id: str = Query("", alias="group_id"),
):
    user = _require_user(request, db)
    if not user:
        return RedirectResponse("/auth/login", status_code=303)

    base_query = (
        db.query(Booking)
        .filter(
            Booking.user_id == user.id,
            Booking.event_id == event_id,
            Booking.payment_status.in_(["paid", "refunded"]),
        )
    )
    if group_id and group_id.strip():
        bookings = base_query.filter(Booking.booking_group == group_id.strip()).order_by(Booking.id).all()
        if not bookings:
            flash(request, "No bookings found for this transaction.", "warning")
            return RedirectResponse("/booking/my", status_code=303)
    else:
        all_bookings = base_query.order_by(Booking.booked_at.desc()).all()
        if not all_bookings:
            flash(request, "No bookings found for this event.", "warning")
            return RedirectResponse("/booking/my", status_code=303)
        groups_seen = set()
        first_group = None
        for b in all_bookings:
            g = b.booking_group or f"solo-{b.id}"
            if first_group is None:
                first_group = g
            groups_seen.add(g)
        if len(groups_seen) > 1:
            flash(request, "You have multiple bookings for this event. Use My Bookings to download each invoice.", "info")
            return RedirectResponse("/booking/my", status_code=303)
        bookings = [b for b in all_bookings if (b.booking_group or f"solo-{b.id}") == first_group]

    event = db.query(Event).get(event_id)
    auditorium = db.query(Auditorium).get(event.auditorium_id) if event and event.auditorium_id else None
    if not event or not auditorium:
        flash(request, "Event not found.", "danger")
        return RedirectResponse("/booking/my", status_code=303)

    seats = [db.query(Seat).get(b.seat_id) for b in bookings]
    custom_types_map = {f"custom_{st.id}": st for st in db.query(SeatType).filter(SeatType.is_custom == True).all()}
    purchased_addons = _get_booking_addons(db, bookings[0].booking_group) if bookings else []
    pdf_bytes = generate_invoice_pdf(bookings, user, event, auditorium, seats, custom_types_map, db=db, addons=purchased_addons)
    ref = bookings[0].booking_ref or "invoice"
    return StreamingResponse(
        io.BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="invoice-{ref}.pdf"'},
    )
