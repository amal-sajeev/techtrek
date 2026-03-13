from sqlalchemy import Column, DateTime, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import relationship

from app.database import Base
from app.utils import now_ist


class Event(Base):
    __tablename__ = "events"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(300), nullable=False)
    description = Column(Text, nullable=True)
    banner_url = Column(String(500), nullable=True)
    college_id = Column(Integer, ForeignKey("colleges.id"), nullable=True)
    discount_pct = Column(Numeric(5, 2), nullable=True)
    status = Column(String(20), default="draft")
    created_at = Column(DateTime, default=now_ist)

    college = relationship("College")
    event_showings = relationship("EventShowing", back_populates="event", cascade="all, delete-orphan")
    bookings = relationship("Booking", back_populates="event")
