from sqlalchemy import Boolean, Column, ForeignKey, Integer, String
from sqlalchemy.orm import relationship

from app.database import Base


class Seat(Base):
    __tablename__ = "seats"

    id = Column(Integer, primary_key=True, index=True)
    auditorium_id = Column(Integer, ForeignKey("auditoriums.id"), nullable=False)
    row_num = Column(Integer, nullable=False)
    col_num = Column(Integer, nullable=False)
    label = Column(String(10), nullable=False)
    seat_type = Column(String(50), default="standard")
    is_active = Column(Boolean, default=True)

    auditorium = relationship("Auditorium", back_populates="seats")
    bookings = relationship("Booking", back_populates="seat")
