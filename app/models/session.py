from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import relationship

from app.database import Base


class LectureSession(Base):
    __tablename__ = "lecture_sessions"

    id = Column(Integer, primary_key=True, index=True)
    auditorium_id = Column(Integer, ForeignKey("auditoriums.id"), nullable=False)
    title = Column(String(300), nullable=False)
    speaker = Column(String(200), nullable=False)
    description = Column(Text, nullable=True)
    start_time = Column(DateTime, nullable=False)
    duration_minutes = Column(Integer, default=30)
    price = Column(Numeric(10, 2), nullable=False, default=0)
    status = Column(String(20), default="draft")
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    auditorium = relationship("Auditorium", back_populates="sessions")
    bookings = relationship("Booking", back_populates="session")
    waitlist_entries = relationship(
        "Waitlist",
        back_populates="session",
        foreign_keys="Waitlist.session_id",
    )
