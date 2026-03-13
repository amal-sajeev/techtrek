

from datetime import timedelta

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.csrf import csrf_protection
from app.dependencies import get_db, now_ist, template_ctx, templates
from app.models.booking import Booking
from app.models.seat import Seat
from app.models.showing import Showing
from app.models.user import User

router = APIRouter(prefix="/supervisor", tags=["supervisor"], dependencies=[Depends(csrf_protection)])


def _require_supervisor_or_admin(request: Request, db: Session) -> User | None:
    user_id = request.session.get("user_id")
    if not user_id:
        return None
    user = db.query(User).filter(User.id == user_id).first()
    if not user or not (user.is_admin or user.is_supervisor):
        return None
    return user


def _sv_ctx(request: Request, **kwargs):
    ctx = template_ctx(request)
    ctx.update(kwargs)
    return ctx


@router.get("/")
def supervisor_checkin_page(request: Request, db: Session = Depends(get_db)):
    sv = _require_supervisor_or_admin(request, db)
    if not sv:
        return RedirectResponse("/auth/login", status_code=303)
    showings = (
        db.query(Showing)
        .filter(Showing.status.in_(["published", "completed"]))
        .order_by(Showing.start_time.desc())
        .all()
    )
    return templates.TemplateResponse(
        "supervisor/checkin.html",
        _sv_ctx(request, sessions=showings, result=None),
    )


@router.post("/checkin")
async def supervisor_checkin_verify(request: Request, db: Session = Depends(get_db)):
    sv = _require_supervisor_or_admin(request, db)
    if not sv:
        return RedirectResponse("/auth/login", status_code=303)

    form = await request.form()
    ticket_id = form.get("ticket_id", "").strip()
    session_id_raw = form.get("session_id", "")

    showings = (
        db.query(Showing)
        .filter(Showing.status.in_(["published", "completed"]))
        .order_by(Showing.start_time.desc())
        .all()
    )

    if not ticket_id:
        return templates.TemplateResponse(
            "supervisor/checkin.html",
            _sv_ctx(request, sessions=showings, result={"status": "error", "msg": "Please enter a ticket ID."}),
        )

    is_group = ticket_id.startswith("GROUP-")

    if is_group:
        group_id = ticket_id[6:]
        all_group = db.query(Booking).filter(
            Booking.booking_group == group_id,
            Booking.payment_status == "paid",
        ).all()

        result = None
        group_bookings = []

        if not all_group:
            result = {"status": "error", "msg": f"Group '{group_id}' not found or no valid tickets."}
        elif session_id_raw:
            try:
                group_bookings = [b for b in all_group if b.showing_id == int(session_id_raw)]
            except ValueError:
                group_bookings = all_group
            if not group_bookings:
                result = {"status": "error", "msg": f"No tickets in this group match the selected session."}
        else:
            now = now_ist()
            showing_ids = {b.showing_id for b in all_group}
            active_showings = []
            for shid in showing_ids:
                sh = db.query(Showing).get(shid)
                if not sh or not sh.start_time:
                    continue
                sess = sh.session
                duration = sh.effective_duration or 30
                end = sh.start_time + timedelta(minutes=duration)
                if (sh.start_time - timedelta(hours=1)) <= now <= (end + timedelta(minutes=30)):
                    active_showings.append(sh)
            if len(active_showings) >= 1:
                unchecked = [
                    sh for sh in active_showings
                    if any(not b.checked_in for b in all_group if b.showing_id == sh.id)
                ]
                target = unchecked if unchecked else active_showings
                if len(target) == 1:
                    group_bookings = [b for b in all_group if b.showing_id == target[0].id]
                else:
                    titles = ", ".join(f"'{sh.session.title if sh.session else 'Session'}'" for sh in target)
                    result = {"status": "error", "msg": f"Multiple sessions are active right now ({titles}). Please select a specific session from the dropdown."}
            else:
                upcoming = []
                for shid in showing_ids:
                    sh = db.query(Showing).get(shid)
                    if sh and sh.start_time and sh.start_time > now:
                        upcoming.append(sh)
                upcoming.sort(key=lambda sh: sh.start_time)
                titles = ", ".join(f"'{sh.session.title if sh.session else 'Session'}' ({sh.start_time.strftime('%b %d %I:%M %p')})" for sh in upcoming[:3])
                hint = f" Upcoming: {titles}" if titles else ""
                result = {"status": "error", "msg": f"No session in this event is currently active. Please select a session from the dropdown.{hint}"}

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
            showing = db.query(Showing).get(group_bookings[0].showing_id)
            session_title = showing.session.title if showing and showing.session else "unknown"

            if newly_checked and not already_checked:
                msg = f"Check-in successful! {len(newly_checked)} ticket(s) for '{session_title}'."
                status = "success"
            elif newly_checked and already_checked:
                msg = f"Checked in {len(newly_checked)} ticket(s). {len(already_checked)} already checked in."
                status = "success"
            else:
                msg = f"Re-entry — all {len(already_checked)} ticket(s) already checked in. Ticket is valid."
                status = "reentry"

            result = {
                "status": status,
                "msg": msg,
                "is_group": True,
                "user_name": user.full_name or user.username if user else "Unknown",
                "user_email": user.email if user else "",
                "session_title": session_title,
                "newly_checked": newly_checked,
                "already_checked": already_checked,
            }
    else:
        query = db.query(Booking).filter(Booking.ticket_id == ticket_id, Booking.payment_status == "paid")
        if session_id_raw:
            try:
                query = query.filter(Booking.showing_id == int(session_id_raw))
            except ValueError:
                pass
        booking = query.first()

        if not booking:
            result = {"status": "error", "msg": f"Ticket '{ticket_id}' not found or not valid."}
        elif booking.checked_in:
            user = db.query(User).get(booking.user_id)
            seat = db.query(Seat).get(booking.seat_id)
            showing = db.query(Showing).get(booking.showing_id)
            session_title = showing.session.title if showing and showing.session else ""
            time_str = booking.checked_in_at.strftime('%I:%M %p') if booking.checked_in_at else 'earlier'
            result = {
                "status": "reentry",
                "msg": f"Re-entry — ticket valid. Originally checked in at {time_str}.",
                "user_name": user.full_name or user.username if user else "Unknown",
                "user_email": user.email if user else "",
                "seat_label": seat.label if seat else "",
                "session_title": session_title,
                "ticket_id": ticket_id,
            }
        else:
            booking.checked_in = True
            booking.checked_in_at = now_ist()
            db.commit()
            user = db.query(User).get(booking.user_id)
            seat = db.query(Seat).get(booking.seat_id)
            showing = db.query(Showing).get(booking.showing_id)
            session_title = showing.session.title if showing and showing.session else ""
            result = {
                "status": "success",
                "msg": "Check-in successful!",
                "user_name": user.full_name or user.username if user else "Unknown",
                "user_email": user.email if user else "",
                "seat_label": seat.label if seat else "",
                "session_title": session_title,
                "ticket_id": ticket_id,
            }

    stats = None
    if session_id_raw:
        try:
            sid = int(session_id_raw)
            total_booked = db.query(func.count(Booking.id)).filter(Booking.showing_id == sid, Booking.payment_status == "paid").scalar()
            checked_in_count = db.query(func.count(Booking.id)).filter(Booking.showing_id == sid, Booking.payment_status == "paid", Booking.checked_in == True).scalar()
            stats = {"total": total_booked, "checked_in": checked_in_count}
        except ValueError:
            pass

    return templates.TemplateResponse(
        "supervisor/checkin.html",
        _sv_ctx(request, sessions=showings, result=result, stats=stats, selected_session=session_id_raw),
    )
