import asyncio
import logging

from sqlalchemy.orm import Session as DBSession

from app.database import SessionLocal
from app.models.booking import Booking
from app.models.feedback import Feedback
from app.models.event import Event
from app.models.user import User
from app.config import settings
from app.services.email import send_certificate_ready
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
                    email_sent=True,
                    email_sent_at=now,
                )
                db.add(fb)
                db.flush()

                booking_id = user_booking_map[user_id]
                cert_url = f"{base_url}/booking/certificate/{booking_id}"

                try:
                    send_certificate_ready(
                        user.email,
                        user.full_name or user.username,
                        event.name,
                        event_date,
                        cert_url,
                    )
                except Exception:
                    logger.exception("Failed to send certificate email to user %d", user_id)

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


async def feedback_task_loop():
    """Background loop that periodically checks for feedback to send."""
    while True:
        try:
            process_pending_feedback()
        except Exception:
            logger.exception("Feedback task loop error")
        await asyncio.sleep(FEEDBACK_CHECK_INTERVAL)
