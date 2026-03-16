from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer
from sqlalchemy.orm import relationship

from app.database import Base
from app.utils import now_ist


class Waitlist(Base):
    __tablename__ = "waitlist"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    event_id = Column(Integer, ForeignKey("events.id"), nullable=False)
    joined_at = Column(DateTime, default=now_ist)
    notified = Column(Boolean, default=False)
    priority_expires_at = Column(DateTime, nullable=True)

    user = relationship("User", back_populates="waitlist_entries")
    event = relationship("Event", back_populates="waitlist_entries")
