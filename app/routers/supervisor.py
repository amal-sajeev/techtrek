

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.csrf import csrf_protection
from app.dependencies import get_db, now_ist, template_ctx, templates
from app.models.booking import Booking
from app.models.seat import Seat
from app.models.session import LectureSession
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
    sessions = (
        db.query(LectureSession)
        .filter(LectureSession.status.in_(["published", "completed"]))
        .order_by(LectureSession.start_time.desc())
        .all()
    )
    return templates.TemplateResponse(
        "supervisor/checkin.html",
        _sv_ctx(request, sessions=sessions, result=None),
    )


@router.post("/checkin")
async def supervisor_checkin_verify(request: Request, db: Session = Depends(get_db)):
    sv = _require_supervisor_or_admin(request, db)
    if not sv:
        return RedirectResponse("/auth/login", status_code=303)

    form = await request.form()
    ticket_id = form.get("ticket_id", "").strip()
    session_id_raw = form.get("session_id", "")

    sessions = (
        db.query(LectureSession)
        .filter(LectureSession.status.in_(["published", "completed"]))
        .order_by(LectureSession.start_time.desc())
        .all()
    )

    if not ticket_id:
        return templates.TemplateResponse(
            "supervisor/checkin.html",
            _sv_ctx(request, sessions=sessions, result={"status": "error", "msg": "Please enter a ticket ID."}),
        )

    is_group = ticket_id.startswith("GROUP-")

    if is_group:
        group_id = ticket_id[6:]
        group_query = db.query(Booking).filter(
            Booking.booking_group == group_id,
            Booking.payment_status == "paid",
        )
        if session_id_raw:
            try:
                group_query = group_query.filter(Booking.session_id == int(session_id_raw))
            except ValueError:
                pass
        group_bookings = group_query.all()

        if not group_bookings:
            result = {"status": "error", "msg": f"Group '{group_id}' not found or no valid tickets."}
        else:
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
            lecture = db.query(LectureSession).get(group_bookings[0].session_id)

            if newly_checked and not already_checked:
                msg = f"Group check-in successful! {len(newly_checked)} ticket(s) checked in."
                status = "success"
            elif newly_checked and already_checked:
                msg = f"Checked in {len(newly_checked)} ticket(s). {len(already_checked)} already checked in."
                status = "success"
            else:
                msg = f"All {len(already_checked)} ticket(s) in this group were already checked in."
                status = "warning"

            result = {
                "status": status,
                "msg": msg,
                "is_group": True,
                "user_name": user.full_name or user.username if user else "Unknown",
                "user_email": user.email if user else "",
                "session_title": lecture.title if lecture else "",
                "newly_checked": newly_checked,
                "already_checked": already_checked,
            }
    else:
        query = db.query(Booking).filter(Booking.ticket_id == ticket_id, Booking.payment_status == "paid")
        if session_id_raw:
            try:
                query = query.filter(Booking.session_id == int(session_id_raw))
            except ValueError:
                pass
        booking = query.first()

        if not booking:
            result = {"status": "error", "msg": f"Ticket '{ticket_id}' not found or not valid."}
        elif booking.checked_in:
            result = {
                "status": "warning",
                "msg": f"Ticket '{ticket_id}' was already checked in at {booking.checked_in_at.strftime('%I:%M %p') if booking.checked_in_at else 'earlier'}.",
            }
        else:
            booking.checked_in = True
            booking.checked_in_at = now_ist()
            db.commit()
            user = db.query(User).get(booking.user_id)
            seat = db.query(Seat).get(booking.seat_id)
            lecture = db.query(LectureSession).get(booking.session_id)
            result = {
                "status": "success",
                "msg": "Check-in successful!",
                "user_name": user.full_name or user.username if user else "Unknown",
                "user_email": user.email if user else "",
                "seat_label": seat.label if seat else "",
                "session_title": lecture.title if lecture else "",
                "ticket_id": ticket_id,
            }

    stats = None
    if session_id_raw:
        try:
            sid = int(session_id_raw)
            total_booked = db.query(func.count(Booking.id)).filter(Booking.session_id == sid, Booking.payment_status == "paid").scalar()
            checked_in_count = db.query(func.count(Booking.id)).filter(Booking.session_id == sid, Booking.payment_status == "paid", Booking.checked_in == True).scalar()
            stats = {"total": total_booked, "checked_in": checked_in_count}
        except ValueError:
            pass

    return templates.TemplateResponse(
        "supervisor/checkin.html",
        _sv_ctx(request, sessions=sessions, result=result, stats=stats, selected_session=session_id_raw),
    )
