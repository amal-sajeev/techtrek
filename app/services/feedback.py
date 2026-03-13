import asyncio
import logging
from datetime import timedelta

from sqlalchemy import and_
from sqlalchemy.orm import Session as DBSession

from app.database import SessionLocal
from app.models.booking import Booking
from app.models.feedback import Feedback
from app.models.showing import Showing
from app.models.user import User
from app.services.email import send_feedback_request
from app.utils import now_ist

logger = logging.getLogger(__name__)

FEEDBACK_CHECK_INTERVAL = 15 * 60  # 15 minutes


def process_pending_feedback(base_url: str = "https://techtrek.in"):
    """Find showings that have ended and create+email feedback requests."""
    db: DBSession = SessionLocal()
    try:
        now = now_ist()

        ended_showings = (
            db.query(Showing)
            .filter(Showing.status.in_(["published", "completed"]))
            .all()
        )

        for showing in ended_showings:
            end_time = showing.start_time + timedelta(minutes=showing.effective_duration)
            if end_time >= now:
                continue

            session_obj = showing.session
            if not session_obj:
                continue

            paid_user_ids = set(
                uid for (uid,) in db.query(Booking.user_id)
                .filter(
                    Booking.showing_id == showing.id,
                    Booking.payment_status == "paid",
                )
                .all()
            )

            existing_user_ids = set(
                uid for (uid,) in db.query(Feedback.user_id)
                .filter(Feedback.showing_id == showing.id)
                .all()
            )

            new_user_ids = paid_user_ids - existing_user_ids
            if not new_user_ids:
                continue

            showing_date = showing.start_time.strftime("%d %b %Y")
            feedback_url = f"{base_url}/feedback/{showing.id}"

            for user_id in new_user_ids:
                user = db.query(User).get(user_id)
                if not user:
                    continue

                fb = Feedback(
                    user_id=user_id,
                    showing_id=showing.id,
                    email_sent=True,
                    email_sent_at=now,
                )
                db.add(fb)
                db.flush()

                try:
                    send_feedback_request(
                        user.email,
                        user.full_name or user.username,
                        session_obj.title,
                        showing_date,
                        feedback_url,
                    )
                except Exception:
                    logger.exception("Failed to send feedback email to user %d", user_id)

            db.commit()
            logger.info(
                "Created %d feedback requests for showing %d (%s)",
                len(new_user_ids), showing.id, session_obj.title,
            )

    except Exception:
        logger.exception("Error in process_pending_feedback")
        db.rollback()
    finally:
        db.close()


async def feedback_task_loop(base_url: str = "https://techtrek.in"):
    """Background loop that periodically checks for feedback to send."""
    while True:
        try:
            process_pending_feedback(base_url)
        except Exception:
            logger.exception("Feedback task loop error")
        await asyncio.sleep(FEEDBACK_CHECK_INTERVAL)
