from sqlalchemy import Column, DateTime, ForeignKey, Integer, Numeric, String
from sqlalchemy.orm import relationship

from app.database import Base
from app.utils import now_ist


class Showing(Base):
    __tablename__ = "showings"

    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(Integer, ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False)
    auditorium_id = Column(Integer, ForeignKey("auditoriums.id"), nullable=False)
    start_time = Column(DateTime, nullable=False)
    duration_minutes = Column(Integer, nullable=True)
    price = Column(Numeric(10, 2), nullable=False, default=0)
    price_vip = Column(Numeric(10, 2), nullable=True)
    price_accessible = Column(Numeric(10, 2), nullable=True)
    processing_fee_pct = Column(Numeric(5, 2), nullable=True, default=0)
    status = Column(String(20), default="draft")
    created_at = Column(DateTime, default=now_ist)

    session = relationship("Session", back_populates="showings")
    auditorium = relationship("Auditorium", back_populates="showings")
    bookings = relationship("Booking", back_populates="showing")
    waitlist_entries = relationship(
        "Waitlist",
        back_populates="showing",
        foreign_keys="Waitlist.showing_id",
    )
    event_showings = relationship("EventShowing", back_populates="showing")

    @property
    def effective_duration(self):
        """Return override duration or fall back to session default."""
        return self.duration_minutes or (self.session.duration_minutes if self.session else 30)
