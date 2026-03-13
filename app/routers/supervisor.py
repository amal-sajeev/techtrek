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
from app.models.seat import Seat
from app.models.showing import Showing
from app.models.user import User

router = APIRouter(prefix="/supervisor", tags=["supervisor"], dependencies=[Depends(csrf_protection)])


def _require_supervisor(request: Request, db: Session) -> User | None:
    user_id = request.session.get("user_id")
    if not user_id:
        return None
    user = db.query(User).filter(User.id == user_id).first()
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


def _college_showings_query(user: User, db: Session):
    """Return a base query of Showing objects scoped to the supervisor's college."""
    aud_ids = _college_auditorium_ids(user, db)
    if not aud_ids:
        return db.query(Showing).filter(False)
    return db.query(Showing).filter(Showing.auditorium_id.in_(aud_ids))


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

    if aud_ids:
        base_q = db.query(Showing).filter(Showing.auditorium_id.in_(aud_ids))
        total_showings = base_q.count()
        upcoming_count = base_q.filter(
            Showing.status == "published", Showing.start_time > now
        ).count()

        showing_ids = [s.id for s in base_q.all()]
        if showing_ids:
            total_bookings = db.query(func.count(Booking.id)).filter(
                Booking.showing_id.in_(showing_ids), Booking.payment_status == "paid"
            ).scalar() or 0
            total_checked_in = db.query(func.count(Booking.id)).filter(
                Booking.showing_id.in_(showing_ids), Booking.checked_in == True
            ).scalar() or 0
        else:
            total_bookings = 0
            total_checked_in = 0

        upcoming_showings_raw = (
            base_q
            .filter(Showing.status == "published", Showing.start_time > now)
            .order_by(Showing.start_time)
            .limit(10)
            .all()
        )
    else:
        total_showings = 0
        upcoming_count = 0
        total_bookings = 0
        total_checked_in = 0
        upcoming_showings_raw = []

    upcoming_showings = []
    for sh in upcoming_showings_raw:
        aud = db.query(Auditorium).get(sh.auditorium_id)
        booked = db.query(func.count(Booking.id)).filter(
            Booking.showing_id == sh.id, Booking.payment_status == "paid"
        ).scalar() or 0
        checked = db.query(func.count(Booking.id)).filter(
            Booking.showing_id == sh.id, Booking.checked_in == True
        ).scalar() or 0
        upcoming_showings.append({
            "showing": sh,
            "session_title": sh.session.title if sh.session else "Unknown",
            "auditorium_name": aud.name if aud else "—",
            "booked": booked,
            "checked_in": checked,
        })

    return templates.TemplateResponse(
        "supervisor/dashboard.html",
        _sv_ctx(
            request,
            active_page="dashboard",
            sv_college=college,
            total_showings=total_showings,
            upcoming_count=upcoming_count,
            total_bookings=total_bookings,
            total_checked_in=total_checked_in,
            upcoming_showings=upcoming_showings,
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
        showing_ids = [
            s.id for s in
            db.query(Showing.id).filter(Showing.auditorium_id.in_(aud_ids)).all()
        ]
    else:
        showing_ids = []

    if not showing_ids:
        bookings_list = []
    else:
        bq = db.query(Booking).filter(Booking.showing_id.in_(showing_ids))
        if status_filter:
            bq = bq.filter(Booking.payment_status == status_filter)
        else:
            bq = bq.filter(Booking.payment_status.in_(["paid", "hold", "refunded"]))
        bookings_raw = bq.order_by(Booking.booked_at.desc()).all()

        bookings_list = []
        for b in bookings_raw:
            u = db.query(User).get(b.user_id)
            showing = db.query(Showing).get(b.showing_id)
            sess = showing.session if showing else None
            seat = db.query(Seat).get(b.seat_id)
            if q:
                search = q.lower()
                match = (
                    (u and (search in (u.username or "").lower() or search in (u.email or "").lower() or (u.full_name and search in u.full_name.lower())))
                    or (sess and search in sess.title.lower())
                    or (b.booking_ref and search in b.booking_ref.lower())
                    or (b.ticket_id and search in b.ticket_id.lower())
                )
                if not match:
                    continue
            bookings_list.append({"booking": b, "user": u, "session": sess, "showing": showing, "seat": seat})

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
    base_q = _college_showings_query(sv, db)
    showings = (
        base_q
        .filter(Showing.status.in_(["published", "completed"]))
        .order_by(Showing.start_time)
        .all()
    )

    grouped = defaultdict(list)
    for sh in showings:
        aud = db.query(Auditorium).get(sh.auditorium_id)
        booked = db.query(func.count(Booking.id)).filter(
            Booking.showing_id == sh.id, Booking.payment_status == "paid"
        ).scalar() or 0
        date_key = sh.start_time.strftime("%Y-%m-%d")
        grouped[date_key].append({
            "showing": sh,
            "session_title": sh.session.title if sh.session else "Unknown",
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
    showings = (
        _college_showings_query(sv, db)
        .filter(Showing.status.in_(["published", "completed"]))
        .order_by(Showing.start_time.desc())
        .all()
    )
    return templates.TemplateResponse(
        "supervisor/checkin.html",
        _sv_ctx(request, active_page="checkin", sv_college=college, sessions=showings, result=None),
    )


@router.post("/checkin")
async def supervisor_checkin_verify(request: Request, db: Session = Depends(get_db)):
    sv = _require_supervisor(request, db)
    if not sv:
        return RedirectResponse("/auth/login", status_code=303)

    college = sv.supervised_college
    form = await request.form()
    ticket_id = form.get("ticket_id", "").strip()
    session_id_raw = form.get("session_id", "")

    college_showings = (
        _college_showings_query(sv, db)
        .filter(Showing.status.in_(["published", "completed"]))
        .order_by(Showing.start_time.desc())
        .all()
    )
    college_showing_ids = {sh.id for sh in college_showings}

    if not ticket_id:
        return templates.TemplateResponse(
            "supervisor/checkin.html",
            _sv_ctx(request, active_page="checkin", sv_college=college, sessions=college_showings, result={"status": "error", "msg": "Please enter a ticket ID."}),
        )

    is_group = ticket_id.startswith("GROUP-")

    if is_group:
        group_id = ticket_id[6:]
        all_group = db.query(Booking).filter(
            Booking.booking_group == group_id,
            Booking.payment_status == "paid",
        ).all()

        all_group = [b for b in all_group if b.showing_id in college_showing_ids]

        result = None
        group_bookings = []

        if not all_group:
            result = {"status": "error", "msg": f"Group '{group_id}' not found or no valid tickets at {college.name}."}
        elif session_id_raw:
            try:
                group_bookings = [b for b in all_group if b.showing_id == int(session_id_raw)]
            except ValueError:
                group_bookings = all_group
            if not group_bookings:
                result = {"status": "error", "msg": "No tickets in this group match the selected session."}
        else:
            now = now_ist()
            showing_ids = {b.showing_id for b in all_group}
            active_showings = []
            for shid in showing_ids:
                sh = db.query(Showing).get(shid)
                if not sh or not sh.start_time:
                    continue
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
                result = {"status": "error", "msg": f"No session is currently active. Please select a session from the dropdown.{hint}"}

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
        elif booking.showing_id not in college_showing_ids:
            result = {"status": "error", "msg": f"This ticket is not for a showing at {college.name}."}
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
            if sid in college_showing_ids:
                total_booked = db.query(func.count(Booking.id)).filter(Booking.showing_id == sid, Booking.payment_status == "paid").scalar()
                checked_in_count = db.query(func.count(Booking.id)).filter(Booking.showing_id == sid, Booking.payment_status == "paid", Booking.checked_in == True).scalar()
                stats = {"total": total_booked, "checked_in": checked_in_count}
        except ValueError:
            pass

    return templates.TemplateResponse(
        "supervisor/checkin.html",
        _sv_ctx(request, active_page="checkin", sv_college=college, sessions=college_showings, result=result, stats=stats, selected_session=session_id_raw),
    )
