from sqlalchemy import Column, Date, DateTime, ForeignKey, Integer, Numeric, String, Text
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
    auditorium_id = Column(Integer, ForeignKey("auditoriums.id"), nullable=True)
    start_date = Column(Date, nullable=True)
    end_date = Column(Date, nullable=True)
    price = Column(Numeric(10, 2), nullable=False, default=0)
    price_vip = Column(Numeric(10, 2), nullable=True)
    price_accessible = Column(Numeric(10, 2), nullable=True)
    processing_fee_pct = Column(Numeric(5, 2), nullable=True, default=0)
    status = Column(String(20), default="draft")
    created_at = Column(DateTime, default=now_ist)

    college = relationship("College")
    auditorium = relationship("Auditorium", back_populates="events")
    sessions = relationship("Session", back_populates="event", cascade="all, delete-orphan", order_by="Session.order, Session.start_time")
    bookings = relationship("Booking", back_populates="event")
    coupons = relationship("Coupon", back_populates="event")
    waitlist_entries = relationship("Waitlist", back_populates="event")
