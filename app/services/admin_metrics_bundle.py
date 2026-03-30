"""Collect all admin Metrics page data in one JSON-friendly dict (single source of truth)."""

from collections import Counter
from datetime import date, datetime

from sqlalchemy import extract, func
from sqlalchemy.orm import Session

from app.dependencies import now_ist
from app.models.activity_log import ActivityLog
from app.models.booking import Booking
from app.models.city import City
from app.models.college import College
from app.models.coupon import Coupon
from app.models.event import Event
from app.models.event_alert import EventAlert
from app.models.event_session import EventSession
from app.models.feedback import Feedback
from app.models.newsletter import Newsletter
from app.models.testimonial import NewsletterSubscriber
from app.models.poll import Poll, PollVote
from app.models.seat import Seat
from app.models.seat_type import SeatType
from app.models.session import Session as SessionModel
from app.models.session_feedback import SessionFeedback
from app.models.session_recording import SessionRecording
from app.models.session_speaker import SessionSpeaker
from app.models.speaker import Speaker
from app.models.user import User
from app.models.waitlist import Waitlist
from app.models.webhook_log import WebhookLog

MONTH_NAMES = ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def metrics_report_kind_from_params(
    *,
    date_from: str = "",
    date_to: str = "",
    event_id: str = "",
    college_id: str = "",
) -> str:
    """PDF / narrative mode: unfiltered export = quarterly-style brief; any filter = focused report."""
    fp = {
        "date_from": date_from or "",
        "date_to": date_to or "",
        "event_id": event_id or "",
        "college_id": college_id or "",
    }
    if any(str(v).strip() for v in fp.values()):
        return "focused_report"
    return "quarterly_brief"


def _monthly_trend(db, model_cls, date_col, extra_filters=None, value_col=None):
    cols = [
        extract("year", date_col).label("yr"),
        extract("month", date_col).label("mo"),
    ]
    if value_col is not None:
        cols.append(func.coalesce(func.sum(value_col), 0))
    else:
        cols.append(func.count(model_cls.id))
    q = db.query(*cols).filter(date_col.isnot(None))
    if extra_filters:
        for f in extra_filters:
            q = q.filter(f)
    rows = q.group_by("yr", "mo").order_by("yr", "mo").all()
    key = "value" if value_col is not None else "count"
    return [{"label": f"{MONTH_NAMES[int(mo)]} {int(yr)}", key: float(v) if value_col else v}
            for yr, mo, v in rows]


def _custom_types_map(db: Session) -> dict:
    cts = db.query(SeatType).order_by(SeatType.name).all()
    return {f"custom_{ct.id}": {"id": ct.id, "name": ct.name, "colour": ct.colour} for ct in cts}


def _seat_type_display_name(seat_type_key: str | None, custom_map: dict) -> str:
    k = (seat_type_key or "standard").strip() or "standard"
    if k in custom_map:
        return custom_map[k]["name"]
    builtin = {
        "standard": "Standard",
        "vip": "VIP",
        "accessible": "Accessible",
        "aisle": "Aisle",
        "reserved": "Reserved",
    }
    if k in builtin:
        return builtin[k]
    return k.replace("_", " ").strip().title()


def build_admin_metrics_bundle(
    db: Session,
    *,
    date_from: str = "",
    date_to: str = "",
    event_id: str = "",
    college_id: str = "",
) -> dict:
    """
    Returns template kwargs dict plus filter_summary, generated_at, and filter_params.
    All numeric values are float/int suitable for JSON.
    """
    SessModel = SessionModel

    d_from = d_to = ev_filter = col_filter = None
    try:
        if date_from:
            d_from = date.fromisoformat(date_from)
        if date_to:
            d_to = date.fromisoformat(date_to)
        if event_id:
            ev_filter = int(event_id)
        if college_id:
            col_filter = int(college_id)
    except (ValueError, TypeError):
        pass

    dt_from = datetime.combine(d_from, datetime.min.time()) if d_from else None
    dt_to = datetime.combine(d_to, datetime.max.time()) if d_to else None

    def _bk_filters(q, *, join_event=False):
        q = q.filter(Booking.payment_status == "paid", Booking.is_shared_ticket == False)
        if dt_from:
            q = q.filter(Booking.booked_at >= dt_from)
        if dt_to:
            q = q.filter(Booking.booked_at <= dt_to)
        if ev_filter:
            q = q.filter(Booking.event_id == ev_filter)
        if col_filter:
            if not join_event:
                q = q.join(Event, Booking.event_id == Event.id)
            q = q.filter(Event.college_id == col_filter)
        return q

    def _ev_filters(q):
        if col_filter:
            q = q.filter(Event.college_id == col_filter)
        if d_from:
            q = q.filter(Event.start_date >= d_from)
        if d_to:
            q = q.filter(Event.start_date <= d_to)
        if ev_filter:
            q = q.filter(Event.id == ev_filter)
        return q

    def _fb_date(q, col):
        if dt_from:
            q = q.filter(col >= dt_from)
        if dt_to:
            q = q.filter(col <= dt_to)
        return q

    total_users = db.query(func.count(User.id)).filter(User.deleted_at.is_(None)).scalar() or 0
    total_revenue = float(_bk_filters(
        db.query(func.coalesce(func.sum(Booking.amount_paid), 0))
    ).scalar() or 0)
    total_bookings = _bk_filters(db.query(func.count(Booking.id))).scalar() or 0
    checked_in_count = _bk_filters(
        db.query(func.count(Booking.id)).filter(Booking.checked_in == True)
    ).scalar() or 0
    checkin_rate = round(checked_in_count / total_bookings * 100, 1) if total_bookings else 0.0

    fb_avg_q = db.query(func.avg(Feedback.rating)).filter(Feedback.submitted_at.isnot(None), Feedback.rating.isnot(None))
    if ev_filter:
        fb_avg_q = fb_avg_q.filter(Feedback.event_id == ev_filter)
    fb_avg_q = _fb_date(fb_avg_q, Feedback.submitted_at)
    avg_rating = round(float(fb_avg_q.scalar() or 0), 1)

    total_fb_count = db.query(func.count(Feedback.id)).filter(Feedback.submitted_at.isnot(None)).scalar() or 0

    ev_status_q = _ev_filters(db.query(Event.status, func.count(Event.id)))
    event_statuses = {s: c for s, c in ev_status_q.group_by(Event.status).all()}

    bk_trend_filters = [Booking.payment_status == "paid", Booking.is_shared_ticket == False]
    if ev_filter:
        bk_trend_filters.append(Booking.event_id == ev_filter)
    booking_trend = _monthly_trend(db, Booking, Booking.booked_at, bk_trend_filters)
    revenue_trend = _monthly_trend(db, Booking, Booking.booked_at, bk_trend_filters, value_col=Booking.amount_paid)

    bk_status_q = db.query(Booking.payment_status, func.count(Booking.id)).filter(Booking.is_shared_ticket == False)
    if dt_from:
        bk_status_q = bk_status_q.filter(Booking.booked_at >= dt_from)
    if dt_to:
        bk_status_q = bk_status_q.filter(Booking.booked_at <= dt_to)
    if ev_filter:
        bk_status_q = bk_status_q.filter(Booking.event_id == ev_filter)
    booking_statuses = {s: c for s, c in bk_status_q.group_by(Booking.payment_status).all()}

    rating_q = db.query(Feedback.rating, func.count(Feedback.id)).filter(
        Feedback.submitted_at.isnot(None), Feedback.rating.isnot(None))
    if ev_filter:
        rating_q = rating_q.filter(Feedback.event_id == ev_filter)
    rating_q = _fb_date(rating_q, Feedback.submitted_at)
    rating_dist = {r: c for r, c in rating_q.group_by(Feedback.rating).all()}

    reg_filters = [User.deleted_at.is_(None)]
    reg_trend = _monthly_trend(db, User, User.created_at, reg_filters)

    user_q = db.query(User).filter(User.deleted_at.is_(None))
    if dt_from:
        user_q = user_q.filter(User.created_at >= dt_from)
    if dt_to:
        user_q = user_q.filter(User.created_at <= dt_to)
    all_users = user_q.all()
    spec_counts = Counter(u.domain for u in all_users if u.domain).most_common(10)
    top_specializations = [{"name": n, "count": c} for n, c in spec_counts]

    yos_counts = Counter(u.year_of_study for u in all_users if u.year_of_study)
    yos_dist = [{"year": y, "count": c} for y, c in sorted(yos_counts.items())]

    oauth_count = sum(1 for u in all_users if u.oauth_provider)
    password_count = len(all_users) - oauth_count
    auth_counts = {"oauth": oauth_count, "password": password_count}

    role_counts = {
        "active": db.query(func.count(User.id)).filter(User.deleted_at.is_(None)).scalar() or 0,
        "admins": db.query(func.count(User.id)).filter(User.is_admin == True, User.deleted_at.is_(None)).scalar() or 0,
        "supervisors": db.query(func.count(User.id)).filter(User.is_supervisor == True, User.deleted_at.is_(None)).scalar() or 0,
        "deleted": db.query(func.count(User.id)).filter(User.deleted_at.isnot(None)).scalar() or 0,
    }

    college_counts = Counter(u.college for u in all_users if u.college).most_common(8)
    top_user_colleges = [{"name": n, "count": c} for n, c in college_counts]

    spe_q = (
        db.query(Event.name, func.count(EventSession.id))
        .join(EventSession, EventSession.event_id == Event.id)
    )
    spe_q = _ev_filters(spe_q)
    sessions_per_event = [{"name": n, "count": c} for n, c in
                          spe_q.group_by(Event.id, Event.name).order_by(func.count(EventSession.id).desc()).all()]

    ebc_q = (
        db.query(City.name, func.count(Event.id))
        .select_from(Event)
        .join(College, Event.college_id == College.id)
        .join(City, College.city_id == City.id)
    )
    ebc_q = _ev_filters(ebc_q)
    events_by_city = [{"name": n, "count": c} for n, c in
                      ebc_q.group_by(City.name).order_by(func.count(Event.id).desc()).limit(8).all()]

    city_bk_q = (
        db.query(City.name, func.count(Booking.id))
        .select_from(Booking)
        .join(Event, Booking.event_id == Event.id)
        .join(College, Event.college_id == College.id)
        .join(City, College.city_id == City.id)
        .filter(Booking.payment_status == "paid", Booking.is_shared_ticket == False)
    )
    if dt_from:
        city_bk_q = city_bk_q.filter(Booking.booked_at >= dt_from)
    if dt_to:
        city_bk_q = city_bk_q.filter(Booking.booked_at <= dt_to)
    if ev_filter:
        city_bk_q = city_bk_q.filter(Booking.event_id == ev_filter)
    if col_filter:
        city_bk_q = city_bk_q.filter(Event.college_id == col_filter)
    top_cities = [{"name": n, "count": c} for n, c in
                  city_bk_q.group_by(City.name).order_by(func.count(Booking.id).desc()).limit(8).all()]

    top_col_q = (
        db.query(College.name, func.count(Booking.id))
        .join(Event, Event.college_id == College.id)
        .join(Booking, Booking.event_id == Event.id)
        .filter(Booking.payment_status == "paid", Booking.is_shared_ticket == False)
    )
    if dt_from:
        top_col_q = top_col_q.filter(Booking.booked_at >= dt_from)
    if dt_to:
        top_col_q = top_col_q.filter(Booking.booked_at <= dt_to)
    if ev_filter:
        top_col_q = top_col_q.filter(Booking.event_id == ev_filter)
    if col_filter:
        top_col_q = top_col_q.filter(College.id == col_filter)
    top_colleges = [{"name": n, "count": c} for n, c in
                    top_col_q.group_by(College.id, College.name)
                    .order_by(func.count(Booking.id).desc()).limit(8).all()]

    bpe_q = (
        db.query(Event.name, func.count(Booking.id))
        .join(Booking, Booking.event_id == Event.id)
        .filter(Booking.payment_status == "paid", Booking.is_shared_ticket == False)
    )
    if dt_from:
        bpe_q = bpe_q.filter(Booking.booked_at >= dt_from)
    if dt_to:
        bpe_q = bpe_q.filter(Booking.booked_at <= dt_to)
    if ev_filter:
        bpe_q = bpe_q.filter(Booking.event_id == ev_filter)
    if col_filter:
        bpe_q = bpe_q.filter(Event.college_id == col_filter)
    top_events_by_bookings = [
        {"name": n, "count": c}
        for n, c in bpe_q.group_by(Event.id, Event.name)
        .order_by(func.count(Booking.id).desc())
        .limit(8)
        .all()
    ]

    wle_q = (
        db.query(Event.name, func.count(Waitlist.id))
        .join(Waitlist, Waitlist.event_id == Event.id)
    )
    wle_q = _ev_filters(wle_q)
    top_events_by_waitlist = [
        {"name": n, "count": c}
        for n, c in wle_q.group_by(Event.id, Event.name)
        .order_by(func.count(Waitlist.id).desc())
        .limit(8)
        .all()
    ]

    _bookable_seat_types = ("aisle", "reserved")
    _ct_map = _custom_types_map(db)

    seat_distribution = {"segments": [], "unsold": 0, "total_capacity": 0}
    if ev_filter:
        ev_one = db.query(Event).filter(Event.id == ev_filter).first()
        if ev_one and ev_one.auditorium_id:
            cap_q = (
                db.query(Seat.seat_type, func.count(Seat.id))
                .filter(
                    Seat.auditorium_id == ev_one.auditorium_id,
                    Seat.is_active == True,
                    Seat.seat_type.notin_(_bookable_seat_types),
                )
                .group_by(Seat.seat_type)
            )
            cap_by_type = {(t or "standard"): c for t, c in cap_q.all()}

            sold_q = (
                db.query(Seat.seat_type, func.count(Booking.id))
                .select_from(Booking)
                .join(Seat, Booking.seat_id == Seat.id)
                .filter(
                    Booking.event_id == ev_filter,
                    Booking.payment_status == "paid",
                    Booking.is_shared_ticket == False,
                    Seat.is_active == True,
                    Seat.seat_type.notin_(_bookable_seat_types),
                )
                .group_by(Seat.seat_type)
            )
            sold_by_type = {(t or "standard"): c for t, c in sold_q.all()}

            all_types = sorted(
                set(cap_by_type.keys()) | set(sold_by_type.keys()),
                key=lambda x: (x or "standard").lower(),
            )
            segments = []
            for st in all_types:
                sold = int(sold_by_type.get(st, 0) or 0)
                if sold > 0:
                    segments.append(
                        {"label": _seat_type_display_name(st, _ct_map), "count": sold}
                    )
            total_cap = sum(int(v) for v in cap_by_type.values())
            total_sold = sum(int(v) for v in sold_by_type.values())
            unsold = max(0, total_cap - total_sold)
            seat_distribution = {
                "segments": segments,
                "unsold": unsold,
                "total_capacity": total_cap,
            }

    rev_by_ev_q = (
        db.query(Event.name, func.sum(Booking.amount_paid), func.count(Booking.id))
        .join(Booking, Booking.event_id == Event.id)
        .filter(Booking.payment_status == "paid", Booking.is_shared_ticket == False)
    )
    if dt_from:
        rev_by_ev_q = rev_by_ev_q.filter(Booking.booked_at >= dt_from)
    if dt_to:
        rev_by_ev_q = rev_by_ev_q.filter(Booking.booked_at <= dt_to)
    if ev_filter:
        rev_by_ev_q = rev_by_ev_q.filter(Event.id == ev_filter)
    if col_filter:
        rev_by_ev_q = rev_by_ev_q.filter(Event.college_id == col_filter)
    revenue_by_event = [{"name": n, "revenue": float(r or 0), "bookings": c}
                        for n, r, c in rev_by_ev_q.group_by(Event.id, Event.name)
                        .order_by(func.sum(Booking.amount_paid).desc()).limit(8).all()]

    rev_seat_q = (
        db.query(Seat.seat_type, func.sum(Booking.amount_paid), func.count(Booking.id))
        .join(Seat, Booking.seat_id == Seat.id)
        .filter(Booking.payment_status == "paid", Booking.is_shared_ticket == False)
    )
    if dt_from:
        rev_seat_q = rev_seat_q.filter(Booking.booked_at >= dt_from)
    if dt_to:
        rev_seat_q = rev_seat_q.filter(Booking.booked_at <= dt_to)
    if ev_filter:
        rev_seat_q = rev_seat_q.filter(Booking.event_id == ev_filter)
    revenue_by_seat_type = [
        {
            "type": t or "standard",
            "display_label": _seat_type_display_name(t, _ct_map),
            "revenue": float(r or 0),
            "count": c,
        }
        for t, r, c in rev_seat_q.group_by(Seat.seat_type)
        .order_by(func.sum(Booking.amount_paid).desc())
        .all()
    ]

    refund_count = db.query(func.count(Booking.id)).filter(Booking.payment_status == "refunded").scalar() or 0
    refund_total = float(db.query(func.coalesce(func.sum(Booking.refund_amount), 0)).scalar() or 0)
    cancel_fees = float(db.query(func.coalesce(func.sum(Booking.cancellation_fee), 0)).scalar() or 0)
    shared_ticket_count = db.query(func.count(Booking.id)).filter(Booking.is_shared_ticket == True).scalar() or 0
    refund_stats = {"count": refund_count, "total": refund_total, "cancel_fees": cancel_fees, "shared": shared_ticket_count}

    coupon_total = db.query(func.count(Coupon.id)).scalar() or 0
    coupon_active = db.query(func.count(Coupon.id)).filter(Coupon.is_active == True).scalar() or 0
    coupon_redeemed = db.query(func.coalesce(func.sum(Coupon.used_count), 0)).scalar() or 0
    bk_with_coupon = db.query(func.count(Booking.id)).filter(
        Booking.coupon_id.isnot(None), Booking.payment_status == "paid"
    ).scalar() or 0
    coupon_pct = round(bk_with_coupon / total_bookings * 100, 1) if total_bookings else 0
    coupon_stats = {"total": coupon_total, "active": coupon_active, "redeemed": int(coupon_redeemed), "pct": coupon_pct}

    sess_q = (
        db.query(SessModel.title, func.avg(SessionFeedback.rating), func.count(SessionFeedback.id))
        .join(SessionFeedback, SessionFeedback.session_id == SessModel.id)
        .filter(SessionFeedback.rating.isnot(None))
    )
    if ev_filter:
        sess_q = sess_q.filter(SessionFeedback.event_id == ev_filter)
    sess_q = _fb_date(sess_q, SessionFeedback.created_at)
    best_sessions = [{"title": t, "avg": round(float(a), 1), "count": c}
                     for t, a, c in sess_q.group_by(SessModel.id, SessModel.title)
                     .having(func.count(SessionFeedback.id) >= 1)
                     .order_by(func.avg(SessionFeedback.rating).desc()).limit(8).all()]

    spk_q = (
        db.query(Speaker.name, func.avg(SessionFeedback.rating), func.count(SessionFeedback.id))
        .join(SessModel, SessModel.speaker_id == Speaker.id)
        .join(SessionFeedback, SessionFeedback.session_id == SessModel.id)
        .filter(SessionFeedback.rating.isnot(None))
    )
    if ev_filter:
        spk_q = spk_q.filter(SessionFeedback.event_id == ev_filter)
    spk_q = _fb_date(spk_q, SessionFeedback.created_at)
    best_speakers = [{"name": n, "avg": round(float(a), 1), "count": c}
                     for n, a, c in spk_q.group_by(Speaker.id, Speaker.name)
                     .having(func.count(SessionFeedback.id) >= 1)
                     .order_by(func.avg(SessionFeedback.rating).desc()).limit(8).all()]

    fb_submitted = db.query(func.count(Feedback.id)).filter(Feedback.submitted_at.isnot(None))
    if ev_filter:
        fb_submitted = fb_submitted.filter(Feedback.event_id == ev_filter)
    fb_submitted = _fb_date(fb_submitted, Feedback.submitted_at).scalar() or 0
    fb_total_eligible = _bk_filters(db.query(func.count(Booking.id))).scalar() or 0
    fb_response_rate = round(fb_submitted / fb_total_eligible * 100, 1) if fb_total_eligible else 0.0
    fb_with_comments = db.query(func.count(Feedback.id)).filter(
        Feedback.submitted_at.isnot(None), Feedback.comment.isnot(None), Feedback.comment != "").scalar() or 0
    fb_featured = db.query(func.count(Feedback.id)).filter(Feedback.is_featured == True).scalar() or 0
    feedback_stats = {"submitted": fb_submitted, "rate": fb_response_rate,
                      "with_comments": fb_with_comments, "featured": fb_featured}

    fb_dismissed = db.query(func.count(Feedback.id)).filter(
        Feedback.dismissed == True, Feedback.submitted_at.is_(None)).scalar() or 0
    fb_pending = db.query(func.count(Feedback.id)).filter(
        Feedback.dismissed == False, Feedback.submitted_at.is_(None)).scalar() or 0
    feedback_disp = {"submitted": fb_submitted, "dismissed": fb_dismissed, "pending": fb_pending}

    poll_total = db.query(func.count(Poll.id)).scalar() or 0
    poll_active = db.query(func.count(Poll.id)).filter(Poll.is_active == True).scalar() or 0
    poll_votes_total = db.query(func.count(PollVote.id)).scalar() or 0
    poll_stats = {"total": poll_total, "active": poll_active, "votes": poll_votes_total}

    ci_q = (
        db.query(extract("hour", Booking.checked_in_at).label("hr"), func.count(Booking.id))
        .filter(Booking.checked_in == True, Booking.checked_in_at.isnot(None))
    )
    if ev_filter:
        ci_q = ci_q.filter(Booking.event_id == ev_filter)
    checkin_hours = [{"hour": int(h), "count": c}
                     for h, c in ci_q.group_by("hr").order_by("hr").all() if h is not None]

    wl_ev_q = (
        db.query(Event.name, func.count(Waitlist.id))
        .join(Waitlist, Waitlist.event_id == Event.id)
    )
    wl_ev_q = _ev_filters(wl_ev_q)
    waitlist_by_event = [{"name": n, "count": c} for n, c in
                         wl_ev_q.group_by(Event.id, Event.name)
                         .order_by(func.count(Waitlist.id).desc()).limit(8).all()]

    wl_total = db.query(func.count(Waitlist.id)).scalar() or 0
    wl_notified = db.query(func.count(Waitlist.id)).filter(Waitlist.notified == True).scalar() or 0
    wl_converted = (
        db.query(func.count(Waitlist.id))
        .join(Booking, (Booking.user_id == Waitlist.user_id) & (Booking.event_id == Waitlist.event_id))
        .filter(Waitlist.notified == True, Booking.payment_status == "paid")
        .scalar() or 0
    )
    wl_conv_rate = round(wl_converted / wl_notified * 100, 1) if wl_notified else 0.0
    waitlist_stats = {"total": wl_total, "notified": wl_notified,
                      "converted": wl_converted, "rate": wl_conv_rate}

    spk_total = db.query(func.count(Speaker.id)).scalar() or 0
    spk_with_acct = db.query(func.count(Speaker.id)).filter(Speaker.user_id.isnot(None)).scalar() or 0
    spk_pending = db.query(func.count(Speaker.id)).filter(
        Speaker.invite_token.isnot(None), Speaker.invite_token_expires > now_ist()).scalar() or 0
    spk_avg_sess = 0.0
    if spk_total:
        total_speaker_sessions = db.query(func.count(SessModel.id)).filter(SessModel.speaker_id.isnot(None)).scalar() or 0
        spk_avg_sess = round(total_speaker_sessions / spk_total, 1)
    speaker_stats = {"total": spk_total, "with_accounts": spk_with_acct,
                     "pending": spk_pending, "avg_sessions": spk_avg_sess}

    total_sessions = db.query(func.count(SessModel.id)).scalar() or 0
    recorded_sessions = db.query(func.count(SessModel.id)).filter(
        SessModel.recording_url.isnot(None)).scalar() or 0
    public_recordings = db.query(func.count(SessionRecording.id)).filter(
        SessionRecording.is_public == True).scalar() or 0
    multi_speaker = (
        db.query(func.count(func.distinct(SessionSpeaker.session_id)))
        .filter(
            SessionSpeaker.session_id.in_(
                db.query(SessionSpeaker.session_id)
                .group_by(SessionSpeaker.session_id)
                .having(func.count(SessionSpeaker.id) > 1)
            )
        ).scalar() or 0
    )
    recording_stats = {"total": total_sessions, "recorded": recorded_sessions,
                       "public": public_recordings, "multi_speaker": multi_speaker}

    total_seats = db.query(func.count(Seat.id)).scalar() or 0
    bookable_seats = db.query(func.count(Seat.id)).filter(
        Seat.is_active == True, Seat.seat_type.notin_(["aisle", "reserved"])).scalar() or 0
    booked_seats = _bk_filters(db.query(func.count(func.distinct(Booking.seat_id)))).scalar() or 0
    occupancy = round(booked_seats / bookable_seats * 100, 1) if bookable_seats else 0.0
    venue_stats = {"total_seats": total_seats, "bookable": bookable_seats,
                   "booked": booked_seats, "occupancy": occupancy}

    subscriber_trend = _monthly_trend(db, NewsletterSubscriber, NewsletterSubscriber.subscribed_at)

    act_q = (
        db.query(ActivityLog.category, func.count(ActivityLog.id))
        .group_by(ActivityLog.category)
        .order_by(func.count(ActivityLog.id).desc())
        .limit(10)
    )
    activity_by_cat = [{"category": c, "count": n} for c, n in act_q.all()]

    nl_subscribers = db.query(func.count(NewsletterSubscriber.id)).scalar() or 0
    nl_sent = db.query(func.count(Newsletter.id)).filter(Newsletter.status == "sent").scalar() or 0
    nl_avg_recip = float(
        db.query(func.coalesce(func.avg(Newsletter.total_recipients), 0)).scalar() or 0)
    nl_failed = int(
        db.query(func.coalesce(func.sum(Newsletter.failed_count), 0)).scalar() or 0)
    newsletter_stats = {"subscribers": nl_subscribers, "sent": nl_sent,
                        "avg_recipients": round(nl_avg_recip), "failed": nl_failed}

    wh_total = db.query(func.count(WebhookLog.id)).scalar() or 0
    wh_processed = db.query(func.count(WebhookLog.id)).filter(WebhookLog.processed == True).scalar() or 0
    wh_pending = wh_total - wh_processed
    wh_rate = round(wh_processed / wh_total * 100, 1) if wh_total else 0.0
    webhook_stats = {"total": wh_total, "processed": wh_processed,
                     "pending": wh_pending, "rate": wh_rate}

    alert_q = db.query(EventAlert.alert_type, func.count(EventAlert.id)).group_by(EventAlert.alert_type)
    alert_stats = {t: c for t, c in alert_q.all()}

    filter_summary = []
    if date_from:
        filter_summary.append(f"Bookings / feedback window from: {date_from}")
    else:
        filter_summary.append("Bookings / feedback window from: (all time)")
    if date_to:
        filter_summary.append(f"Bookings / feedback window to: {date_to}")
    else:
        filter_summary.append("Bookings / feedback window to: (all time)")
    if d_from:
        filter_summary.append(f"Event start date from: {d_from.isoformat()}")
    if d_to:
        filter_summary.append(f"Event start date to: {d_to.isoformat()}")
    if ev_filter:
        ev_row = db.query(Event).filter(Event.id == ev_filter).first()
        filter_summary.append(f"Event: {ev_row.name if ev_row else ev_filter}")
    else:
        filter_summary.append("Event: All events")
    if col_filter:
        col_row = db.query(College).filter(College.id == col_filter).first()
        filter_summary.append(f"College: {col_row.name if col_row else col_filter}")
    else:
        filter_summary.append("College: All colleges")

    return {
        "total_users": total_users,
        "total_revenue": total_revenue,
        "total_bookings": total_bookings,
        "checkin_rate": checkin_rate,
        "avg_rating": avg_rating,
        "total_feedback": total_fb_count,
        "event_statuses": event_statuses,
        "booking_trend": booking_trend,
        "revenue_trend": revenue_trend,
        "booking_statuses": booking_statuses,
        "rating_dist": rating_dist,
        "reg_trend": reg_trend,
        "top_specializations": top_specializations,
        "yos_dist": yos_dist,
        "auth_counts": auth_counts,
        "role_counts": role_counts,
        "top_user_colleges": top_user_colleges,
        "seat_distribution": seat_distribution,
        "sessions_per_event": sessions_per_event,
        "events_by_city": events_by_city,
        "top_cities": top_cities,
        "top_colleges": top_colleges,
        "top_events_by_bookings": top_events_by_bookings,
        "top_events_by_waitlist": top_events_by_waitlist,
        "revenue_by_event": revenue_by_event,
        "revenue_by_seat_type": revenue_by_seat_type,
        "refund_stats": refund_stats,
        "coupon_stats": coupon_stats,
        "best_sessions": best_sessions,
        "best_speakers": best_speakers,
        "feedback_stats": feedback_stats,
        "feedback_disp": feedback_disp,
        "poll_stats": poll_stats,
        "checkin_hours": checkin_hours,
        "waitlist_by_event": waitlist_by_event,
        "waitlist_stats": waitlist_stats,
        "speaker_stats": speaker_stats,
        "recording_stats": recording_stats,
        "venue_stats": venue_stats,
        "subscriber_trend": subscriber_trend,
        "activity_by_cat": activity_by_cat,
        "newsletter_stats": newsletter_stats,
        "webhook_stats": webhook_stats,
        "alert_stats": alert_stats,
        "filter_summary": filter_summary,
        "generated_at": now_ist().isoformat(),
        "filter_params": {
            "date_from": date_from or "",
            "date_to": date_to or "",
            "event_id": event_id or "",
            "college_id": college_id or "",
        },
        "report_kind": metrics_report_kind_from_params(
            date_from=date_from, date_to=date_to, event_id=event_id, college_id=college_id
        ),
        "single_event_selected": bool(ev_filter),
    }
