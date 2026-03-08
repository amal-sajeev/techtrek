import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import relationship

from app.database import Base


def _generate_ref():
    return uuid.uuid4().hex[:10].upper()


class Booking(Base):
    __tablename__ = "bookings"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    session_id = Column(Integer, ForeignKey("lecture_sessions.id"), nullable=False)
    seat_id = Column(Integer, ForeignKey("seats.id"), nullable=False)
    payment_status = Column(String(20), default="hold")
    booking_ref = Column(String(20), unique=True, default=_generate_ref)
    held_until = Column(DateTime, nullable=True)
    booked_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    user = relationship("User", back_populates="bookings")
    session = relationship("LectureSession", back_populates="bookings")
    seat = relationship("Seat", back_populates="bookings")
