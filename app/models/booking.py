import uuid
from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from app.database import Base
from app.utils import now_ist


def _generate_ref():
    return uuid.uuid4().hex[:10].upper()


def _generate_ticket_id():
    now = now_ist()
    rand = uuid.uuid4().hex[:8].upper()
    return f"TT-{now.strftime('%Y%m%d')}-{rand}"


class Booking(Base):
    __tablename__ = "bookings"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    session_id = Column(Integer, ForeignKey("lecture_sessions.id"), nullable=False)
    seat_id = Column(Integer, ForeignKey("seats.id"), nullable=False)
    payment_status = Column(String(20), default="hold")
    booking_ref = Column(String(20), unique=True, default=_generate_ref)
    ticket_id = Column(String(30), unique=True, nullable=True)
    qr_code_data = Column(Text, nullable=True)
    booking_group = Column(String(20), nullable=True, index=True)
    group_qr_data = Column(Text, nullable=True)
    amount_paid = Column(Float, default=0)
    refund_amount = Column(Float, nullable=True)
    cancellation_fee = Column(Float, nullable=True)
    checked_in = Column(Boolean, default=False)
    checked_in_at = Column(DateTime, nullable=True)
    invoice_number = Column(String(30), nullable=True, index=True)
    razorpay_order_id = Column(String(50), nullable=True)
    razorpay_payment_id = Column(String(50), nullable=True)
    razorpay_signature = Column(String(128), nullable=True)
    held_until = Column(DateTime, nullable=True)
    booked_at = Column(DateTime, default=now_ist)

    user = relationship("User", back_populates="bookings")
    session = relationship("LectureSession", back_populates="bookings")
    seat = relationship("Seat", back_populates="bookings")
