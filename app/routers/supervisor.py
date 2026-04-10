from collections import defaultdict
from datetime import timedelta

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.csrf import csrf_protection
from app.dependencies import flash, get_db, now_ist, template_ctx, templates
from app.models.auditorium import Auditorium
from app.models.booking import Booking
from app.models.event import Event
from app.models.seat import Seat
from app.models.user import User

router = APIRouter(prefix="/supervisor", tags=["supervisor"], dependencies=[Depends(csrf_protection)])


def _require_supervisor(request: Request, db: Session) -> User | None:
    user_id = request.session.get("user_id")
    if not user_id:
        return None
    user = db.query(User).filter(User.id == user_id, User.deleted_at.is_(None)).first()
    if not user:
        return None
    if not (user.is_supervisor and user.supervisor_college_id):
        if user.is_admin:
            return None
        return None
    return user


def _college_auditorium_ids(user: User, db: Session) -> list[int]:
    """Return auditorium IDs belonging to the supervisor's assigned college."""
    return [
        a.id for a in
        db.query(Auditorium.id).filter(Auditorium.college_id == user.supervisor_college_id).all()
    ]


def _college_events_query(user: User, db: Session):
    """Return a base query of Event objects scoped to the supervisor's college."""
    aud_ids = _college_auditorium_ids(user, db)
    if not aud_ids:
        return db.query(Event).filter(False)
    return db.query(Event).filter(Event.auditorium_id.in_(aud_ids))


def _sv_ctx(request: Request, **kwargs):
    ctx = template_ctx(request, **kwargs)
    return ctx


# ─── Dashboard ───

@router.get("/")
def supervisor_dashboard(request: Request, db: Session = Depends(get_db)):
    sv = _require_supervisor(request, db)
    if not sv:
        return RedirectResponse("/auth/login?next=/supervisor/", status_code=303)

    college = sv.supervised_college
    aud_ids = _college_auditorium_ids(sv, db)
    now = now_ist()
    today = now.date()

    if aud_ids:
        base_q = db.query(Event).filter(Event.auditorium_id.in_(aud_ids))
        total_events = base_q.count()
        upcoming_count = base_q.filter(
            Event.status == "published", Event.start_date >= today
        ).count()

        event_ids = [e.id for e in base_q.all()]
        if event_ids:
            total_bookings = db.query(func.count(Booking.id)).filter(
                Booking.event_id.in_(event_ids), Booking.payment_status == "paid",
                Booking.is_shared_ticket == False,
            ).scalar() or 0
            total_checked_in = db.query(func.count(Booking.id)).filter(
                Booking.event_id.in_(event_ids), Booking.checked_in == True
            ).scalar() or 0
        else:
            total_bookings = 0
            total_checked_in = 0

        upcoming_events_raw = (
            base_q
            .filter(Event.status == "published", Event.start_date >= today)
            .order_by(Event.start_date)
            .limit(10)
            .all()
        )
    else:
        total_events = 0
        upcoming_count = 0
        total_bookings = 0
        total_checked_in = 0
        upcoming_events_raw = []

    upcoming_events = []
    for ev in upcoming_events_raw:
        aud = db.query(Auditorium).get(ev.auditorium_id) if ev.auditorium_id else None
        booked = db.query(func.count(Booking.id)).filter(
            Booking.event_id == ev.id, Booking.payment_status == "paid",
            Booking.is_shared_ticket == False,
        ).scalar() or 0
        checked = db.query(func.count(Booking.id)).filter(
            Booking.event_id == ev.id, Booking.checked_in == True
        ).scalar() or 0
        upcoming_events.append({
            "event": ev,
            "auditorium_name": aud.name if aud else "—",
            "booked": booked,
            "checked_in": checked,
        })

    # Smart check-in: if exactly one event is happening today, link directly to it
    today_events = [
        item for item in upcoming_events
        if item["event"].start_date == today
    ]
    today_event_id = today_events[0]["event"].id if len(today_events) == 1 else None

    return templates.TemplateResponse(
        "supervisor/dashboard.html",
        _sv_ctx(
            request,
            active_page="dashboard",
            sv_college=college,
            total_events=total_events,
            upcoming_count=upcoming_count,
            total_bookings=total_bookings,
            total_checked_in=total_checked_in,
            upcoming_events=upcoming_events,
            today_event_id=today_event_id,
            today=today,
        ),
    )


# ─── Bookings ───

@router.get("/bookings")
def supervisor_bookings(
    request: Request,
    db: Session = Depends(get_db),
    q: str = Query("", alias="q"),
    status_filter: str = Query("", alias="status"),
):
    sv = _require_supervisor(request, db)
    if not sv:
        return RedirectResponse("/auth/login?next=/supervisor/bookings", status_code=303)

    college = sv.supervised_college
    aud_ids = _college_auditorium_ids(sv, db)

    if aud_ids:
        event_ids = [
            e.id for e in
            db.query(Event.id).filter(Event.auditorium_id.in_(aud_ids)).all()
        ]
    else:
        event_ids = []

    if not event_ids:
        bookings_list = []
    else:
        bq = db.query(Booking).filter(Booking.event_id.in_(event_ids))
        if status_filter:
            bq = bq.filter(Booking.payment_status == status_filter)
        else:
            bq = bq.filter(Booking.payment_status.in_(["paid", "hold", "refunded"]))
        bookings_raw = bq.order_by(Booking.booked_at.desc()).all()

        bookings_list = []
        for b in bookings_raw:
            u = db.query(User).get(b.user_id)
            event = db.query(Event).get(b.event_id) if b.event_id else None
            seat = db.query(Seat).get(b.seat_id)
            if q:
                search = q.lower()
                match = (
                    (u and (search in (u.username or "").lower() or search in (u.email or "").lower() or (u.full_name and search in u.full_name.lower())))
                    or (event and search in event.name.lower())
                    or (b.booking_ref and search in b.booking_ref.lower())
                    or (b.ticket_id and search in b.ticket_id.lower())
                    or (b.ticket_number and search in b.ticket_number.lower())
                )
                if not match:
                    continue
            bookings_list.append({"booking": b, "user": u, "event": event, "seat": seat})

    return templates.TemplateResponse(
        "supervisor/bookings.html",
        _sv_ctx(
            request,
            active_page="bookings",
            sv_college=college,
            bookings=bookings_list,
            q=q,
            status_filter=status_filter,
        ),
    )


# ─── Schedule ───

@router.get("/schedule")
def supervisor_schedule(request: Request, db: Session = Depends(get_db)):
    sv = _require_supervisor(request, db)
    if not sv:
        return RedirectResponse("/auth/login?next=/supervisor/schedule", status_code=303)

    college = sv.supervised_college
    base_q = _college_events_query(sv, db)
    events = (
        base_q
        .filter(Event.status.in_(["published", "completed"]))
        .order_by(Event.start_date)
        .all()
    )

    grouped = defaultdict(list)
    for ev in events:
        aud = db.query(Auditorium).get(ev.auditorium_id) if ev.auditorium_id else None
        booked = db.query(func.count(Booking.id)).filter(
            Booking.event_id == ev.id, Booking.payment_status == "paid",
            Booking.is_shared_ticket == False,
        ).scalar() or 0
        date_key = ev.start_date.strftime("%Y-%m-%d") if ev.start_date else "TBD"
        grouped[date_key].append({
            "event": ev,
            "auditorium": aud,
            "booked": booked,
        })

    return templates.TemplateResponse(
        "supervisor/schedule.html",
        _sv_ctx(
            request,
            active_page="schedule",
            sv_college=college,
            grouped=dict(sorted(grouped.items())),
        ),
    )


# ─── Check-in ───

@router.get("/checkin")
def supervisor_checkin_page(request: Request, db: Session = Depends(get_db)):
    sv = _require_supervisor(request, db)
    if not sv:
        return RedirectResponse("/auth/login?next=/supervisor/checkin", status_code=303)

    college = sv.supervised_college
    events_list = (
        _college_events_query(sv, db)
        .filter(Event.status.in_(["published", "completed"]))
        .order_by(Event.start_date.desc())
        .all()
    )
    return templates.TemplateResponse(
        "supervisor/checkin.html",
        _sv_ctx(request, active_page="checkin", sv_college=college, events_list=events_list, result=None),
    )


@router.post("/checkin")
async def supervisor_checkin_verify(request: Request, db: Session = Depends(get_db)):
    sv = _require_supervisor(request, db)
    if not sv:
        return RedirectResponse("/auth/login", status_code=303)

    college = sv.supervised_college
    form = await request.form()
    ticket_id = form.get("ticket_id", "").strip()
    event_id_raw = form.get("event_id", "")

    # QR codes encode the certificate verify URL; extract just the ticket identifier
    if "/certificate/verify/" in ticket_id:
        ticket_id = ticket_id.split("/certificate/verify/")[-1].strip().split("?")[0]

    college_events = (
        _college_events_query(sv, db)
        .filter(Event.status.in_(["published", "completed"]))
        .order_by(Event.start_date.desc())
        .all()
    )
    college_event_ids = {ev.id for ev in college_events}

    if not ticket_id:
        return templates.TemplateResponse(
            "supervisor/checkin.html",
            _sv_ctx(request, active_page="checkin", sv_college=college, events_list=college_events, result={"status": "error", "msg": "Please enter a ticket ID."}),
        )

    is_group = ticket_id.startswith("GROUP-")

    if is_group:
        group_id = ticket_id[6:]
        all_group_any_status = db.query(Booking).filter(
            Booking.booking_group == group_id,
        ).all()
        all_group_any_status = [b for b in all_group_any_status if b.event_id in college_event_ids]
        all_group = [b for b in all_group_any_status if b.payment_status == "paid"]
        refunded_count = sum(1 for b in all_group_any_status if b.payment_status in ("refunded", "cancelled"))

        result = None
        group_bookings = []

        if not all_group_any_status:
            result = {"status": "error", "msg": f"Group '{group_id}' not found or no valid tickets at {college.name}."}
        elif not all_group:
            result = {"status": "error", "msg": f"No valid (paid) tickets in this group — {refunded_count} ticket(s) are refunded/cancelled."}
        elif event_id_raw:
            try:
                group_bookings = [b for b in all_group if b.event_id == int(event_id_raw)]
            except ValueError:
                group_bookings = all_group
            if not group_bookings:
                result = {"status": "error", "msg": "No tickets in this group match the selected event."}
        else:
            group_bookings = all_group

        if group_bookings:
            now = now_ist()
            newly_checked = []
            already_checked = []
            for gb in group_bookings:
                if gb.checked_in:
                    seat = db.query(Seat).get(gb.seat_id)
                    already_checked.append(seat.label if seat else gb.ticket_id)
                else:
                    gb.checked_in = True
                    gb.checked_in_at = now
                    seat = db.query(Seat).get(gb.seat_id)
                    newly_checked.append(seat.label if seat else gb.ticket_id)
            db.commit()

            user = db.query(User).get(group_bookings[0].user_id)
            event = db.query(Event).get(group_bookings[0].event_id) if group_bookings[0].event_id else None
            event_name = event.name if event else "unknown"
            refunded_note = f" ({refunded_count} ticket(s) in this group are refunded/cancelled.)" if refunded_count else ""

            if newly_checked and not already_checked:
                msg = f"Check-in successful! {len(newly_checked)} ticket(s) for '{event_name}'.{refunded_note}"
                status = "success"
            elif newly_checked and already_checked:
                msg = f"Checked in {len(newly_checked)} ticket(s). {len(already_checked)} already checked in.{refunded_note}"
                status = "success"
            else:
                msg = f"Re-entry — all {len(already_checked)} ticket(s) already checked in. Ticket is valid.{refunded_note}"
                status = "reentry"

            result = {
                "status": status,
                "msg": msg,
                "is_group": True,
                "user_name": user.full_name or user.username if user else "Unknown",
                "user_email": user.email if user else "",
                "event_name": event_name,
                "newly_checked": newly_checked,
                "already_checked": already_checked,
                "refunded_count": refunded_count,
            }
    else:
        query = db.query(Booking).filter(Booking.ticket_number == ticket_id, Booking.payment_status == "paid")
        if event_id_raw:
            try:
                query = query.filter(Booking.event_id == int(event_id_raw))
            except ValueError:
                pass
        booking = query.first()
        if not booking:
            query = db.query(Booking).filter(Booking.ticket_id == ticket_id, Booking.payment_status == "paid")
            if event_id_raw:
                try:
                    query = query.filter(Booking.event_id == int(event_id_raw))
                except ValueError:
                    pass
            booking = query.first()

        if not booking:
            result = {"status": "error", "msg": f"Ticket '{ticket_id}' not found or not valid."}
        elif booking.event_id not in college_event_ids:
            result = {"status": "error", "msg": f"This ticket is not for an event at {college.name}."}
        elif booking.checked_in:
            user = db.query(User).get(booking.user_id)
            seat = db.query(Seat).get(booking.seat_id)
            event = db.query(Event).get(booking.event_id) if booking.event_id else None
            time_str = booking.checked_in_at.strftime('%I:%M %p') if booking.checked_in_at else 'earlier'
            result = {
                "status": "reentry",
                "msg": f"Re-entry — ticket valid. Originally checked in at {time_str}.",
                "user_name": user.full_name or user.username if user else "Unknown",
                "user_email": user.email if user else "",
                "seat_label": seat.label if seat else "",
                "event_name": event.name if event else "",
                "ticket_id": ticket_id,
            }
        else:
            booking.checked_in = True
            booking.checked_in_at = now_ist()
            db.commit()
            user = db.query(User).get(booking.user_id)
            seat = db.query(Seat).get(booking.seat_id)
            event = db.query(Event).get(booking.event_id) if booking.event_id else None
            result = {
                "status": "success",
                "msg": "Check-in successful!",
                "user_name": user.full_name or user.username if user else "Unknown",
                "user_email": user.email if user else "",
                "seat_label": seat.label if seat else "",
                "event_name": event.name if event else "",
                "ticket_id": ticket_id,
            }

    stats = None
    if event_id_raw:
        try:
            eid = int(event_id_raw)
            if eid in college_event_ids:
                total_booked = db.query(func.count(Booking.id)).filter(Booking.event_id == eid, Booking.payment_status == "paid").scalar()
                checked_in_count = db.query(func.count(Booking.id)).filter(Booking.event_id == eid, Booking.payment_status == "paid", Booking.checked_in == True).scalar()
                stats = {"total": total_booked, "checked_in": checked_in_count}
        except ValueError:
            pass

    return templates.TemplateResponse(
        "supervisor/checkin.html",
        _sv_ctx(request, active_page="checkin", sv_college=college, events_list=college_events, result=result, stats=stats, selected_event=event_id_raw),
    )
