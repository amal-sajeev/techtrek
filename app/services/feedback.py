import asyncio
import logging

from sqlalchemy.orm import Session as DBSession

from app.database import SessionLocal
from app.models.booking import Booking
from app.models.feedback import Feedback
from app.models.event import Event
from app.models.user import User
from app.config import settings
from app.services.email import send_certificate_ready, send_feedback_request, send_event_reminder
from app.utils import now_ist

logger = logging.getLogger(__name__)

FEEDBACK_CHECK_INTERVAL = 15 * 60  # 15 minutes


def process_pending_feedback(base_url: str | None = None):
    """Find ended events and email certificate links to checked-in attendees."""
    if not base_url:
        base_url = settings.base_url
    db: DBSession = SessionLocal()
    try:
        now = now_ist()

        ended_events = (
            db.query(Event)
            .filter(Event.status.in_(["published", "completed"]))
            .all()
        )

        for event in ended_events:
            if not event.start_date:
                continue
            from datetime import datetime, time
            end_date = event.end_date or event.start_date
            end_dt = datetime.combine(end_date, time(23, 59, 59))
            if end_dt >= now.replace(tzinfo=None):
                continue

            if event.status == "published":
                event.status = "completed"
                db.commit()
                logger.info("Auto-completed event %d (%s)", event.id, event.name)

            checked_in_bookings = (
                db.query(Booking)
                .filter(
                    Booking.event_id == event.id,
                    Booking.payment_status == "paid",
                    Booking.checked_in == True,
                )
                .all()
            )

            user_booking_map: dict[int, int] = {}
            for b in checked_in_bookings:
                if b.user_id not in user_booking_map:
                    user_booking_map[b.user_id] = b.id

            existing_user_ids = set(
                uid for (uid,) in db.query(Feedback.user_id)
                .filter(Feedback.event_id == event.id)
                .all()
            )

            new_user_ids = set(user_booking_map.keys()) - existing_user_ids
            if not new_user_ids:
                continue

            event_date = event.start_date.strftime("%d %b %Y")

            for user_id in new_user_ids:
                user = db.query(User).get(user_id)
                if not user:
                    continue

                fb = Feedback(
                    user_id=user_id,
                    event_id=event.id,
                    email_sent=False,
                )
                db.add(fb)
                db.flush()

                booking_id = user_booking_map[user_id]
                cert_url = f"{base_url}/booking/certificate/{booking_id}"

                try:
                    sent = send_certificate_ready(
                        user.email,
                        user.full_name or user.username,
                        event.name,
                        event_date,
                        cert_url,
                    )
                    if sent:
                        fb.email_sent = True
                        fb.email_sent_at = now
                except Exception:
                    logger.exception("Failed to send certificate email to user %d", user_id)

                try:
                    feedback_url = f"{base_url}/feedback/{event.id}"
                    send_feedback_request(
                        user.email,
                        user.full_name or user.username,
                        event.name,
                        event_date,
                        feedback_url,
                    )
                except Exception:
                    logger.exception("Failed to send feedback request email to user %d", user_id)

            db.commit()
            logger.info(
                "Sent %d certificate notifications for event %d (%s)",
                len(new_user_ids), event.id, event.name,
            )

    except Exception:
        logger.exception("Error in process_pending_feedback")
        db.rollback()
    finally:
        db.close()


def process_event_reminders(base_url: str | None = None):
    """Send day-before reminder emails to attendees of tomorrow's events.
    Only fires when the current IST hour is between 9-10 AM to avoid duplicates."""
    if not base_url:
        base_url = settings.base_url
    now = now_ist()
    if now.hour < 9 or now.hour >= 10:
        return

    from datetime import timedelta
    from app.models.auditorium import Auditorium
    tomorrow = (now + timedelta(days=1)).date()

    db: DBSession = SessionLocal()
    try:
        events = (
            db.query(Event)
            .filter(Event.status == "published", Event.start_date == tomorrow)
            .all()
        )
        for event in events:
            paid_bookings = (
                db.query(Booking)
                .filter(
                    Booking.event_id == event.id,
                    Booking.payment_status == "paid",
                )
                .all()
            )
            user_ids_seen: set[int] = set()
            event_date = event.start_date.strftime("%d %b %Y")
            auditorium = db.query(Auditorium).get(event.auditorium_id) if event.auditorium_id else None
            venue_name = auditorium.name if auditorium else ""
            event_url = f"{base_url}/events/{event.id}"

            for b in paid_bookings:
                if b.user_id in user_ids_seen:
                    continue
                user_ids_seen.add(b.user_id)
                user = db.query(User).get(b.user_id)
                if not user:
                    continue
                try:
                    send_event_reminder(
                        user.email,
                        user.full_name or user.username,
                        event.name,
                        event_date,
                        venue_name,
                        event_url,
                    )
                except Exception:
                    logger.exception("Failed to send reminder to user %d", b.user_id)

            if user_ids_seen:
                logger.info(
                    "Sent %d reminder emails for event %d (%s)",
                    len(user_ids_seen), event.id, event.name,
                )
    except Exception:
        logger.exception("Error in process_event_reminders")
    finally:
        db.close()


async def feedback_task_loop():
    """Background loop that periodically checks for feedback and reminders."""
    while True:
        try:
            process_pending_feedback()
        except Exception:
            logger.exception("Feedback task loop error")
        try:
            process_event_reminders()
        except Exception:
            logger.exception("Reminder task loop error")
        await asyncio.sleep(FEEDBACK_CHECK_INTERVAL)
