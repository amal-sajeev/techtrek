from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, Text, UniqueConstraint
from sqlalchemy.orm import relationship

from app.database import Base
from app.utils import now_ist


class Feedback(Base):
    __tablename__ = "feedback"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    showing_id = Column(Integer, ForeignKey("showings.id"), nullable=False)
    rating = Column(Integer, nullable=True)
    comment = Column(Text, nullable=True)
    allow_public = Column(Boolean, default=False)
    is_featured = Column(Boolean, default=False)
    dismissed = Column(Boolean, default=False)
    email_sent = Column(Boolean, default=False)
    email_sent_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=now_ist)

    __table_args__ = (
        UniqueConstraint("user_id", "showing_id", name="uq_feedback_user_showing"),
    )

    user = relationship("User", backref="feedback_entries")
    showing = relationship("Showing", backref="feedback_entries")
