from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, Text, UniqueConstraint
from sqlalchemy.orm import relationship

from app.database import Base
from app.utils import now_ist


class Feedback(Base):
    __tablename__ = "feedback"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    event_id = Column(Integer, ForeignKey("events.id"), nullable=False)
    rating = Column(Integer, nullable=True)
    comment = Column(Text, nullable=True)
    allow_public = Column(Boolean, default=False)
    is_featured = Column(Boolean, default=False)
    dismissed = Column(Boolean, default=False)
    email_sent = Column(Boolean, default=False)
    email_sent_at = Column(DateTime, nullable=True)
    submitted_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=now_ist)

    __table_args__ = (
        UniqueConstraint("user_id", "event_id", name="uq_feedback_user_event"),
    )

    user = relationship("User", backref="feedback_entries")
    event = relationship("Event", backref="feedback_entries")
    session_ratings = relationship("SessionRating", back_populates="feedback", cascade="all, delete-orphan")


class SessionRating(Base):
    __tablename__ = "session_ratings"

    id = Column(Integer, primary_key=True, index=True)
    feedback_id = Column(Integer, ForeignKey("feedback.id", ondelete="CASCADE"), nullable=False)
    session_id = Column(Integer, ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False)
    rating = Column(Integer, nullable=False)

    feedback = relationship("Feedback", back_populates="session_ratings")
    session = relationship("Session")
