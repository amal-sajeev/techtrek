from sqlalchemy import Column, DateTime, ForeignKey, Integer, UniqueConstraint
from sqlalchemy.orm import relationship

from app.database import Base
from app.utils import now_ist


class SessionFeedback(Base):
    __tablename__ = "session_feedback"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    session_id = Column(Integer, ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False)
    event_id = Column(Integer, ForeignKey("events.id"), nullable=False)
    rating = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=now_ist)

    __table_args__ = (
        UniqueConstraint("user_id", "session_id", name="uq_session_feedback_user_session"),
    )

    user = relationship("User", backref="session_feedback_entries")
    session = relationship("Session", backref="feedback_ratings")
    event = relationship("Event", backref="session_feedback_entries")
