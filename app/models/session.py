from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import relationship

from app.database import Base
from app.utils import now_ist


class LectureSession(Base):
    __tablename__ = "lecture_sessions"

    id = Column(Integer, primary_key=True, index=True)
    auditorium_id = Column(Integer, ForeignKey("auditoriums.id"), nullable=False)
    speaker_id = Column(Integer, ForeignKey("speakers.id"), nullable=True)
    title = Column(String(300), nullable=False)
    speaker = Column(String(200), nullable=False)
    description = Column(Text, nullable=True)
    banner_url = Column(String(500), nullable=True)
    start_time = Column(DateTime, nullable=False)
    duration_minutes = Column(Integer, default=30)
    price = Column(Numeric(10, 2), nullable=False, default=0)
    price_vip = Column(Numeric(10, 2), nullable=True)
    price_accessible = Column(Numeric(10, 2), nullable=True)
    status = Column(String(20), default="draft")
    created_at = Column(DateTime, default=now_ist)

    auditorium = relationship("Auditorium", back_populates="sessions")
    speaker_rel = relationship("Speaker", back_populates="sessions")
    bookings = relationship("Booking", back_populates="session")
    agenda_items = relationship("AgendaItem", back_populates="session", cascade="all, delete-orphan", order_by="AgendaItem.order")
    waitlist_entries = relationship(
        "Waitlist",
        back_populates="session",
        foreign_keys="Waitlist.session_id",
    )
