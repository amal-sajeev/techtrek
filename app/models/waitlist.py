from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer
from sqlalchemy.orm import relationship

from app.database import Base
from app.utils import now_ist


class Waitlist(Base):
    __tablename__ = "waitlist"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    showing_id = Column(Integer, ForeignKey("showings.id"), nullable=False)
    priority_showing_id = Column(
        Integer, ForeignKey("showings.id"), nullable=True
    )
    joined_at = Column(DateTime, default=now_ist)
    notified = Column(Boolean, default=False)
    priority_expires_at = Column(DateTime, nullable=True)

    user = relationship("User", back_populates="waitlist_entries")
    showing = relationship(
        "Showing",
        back_populates="waitlist_entries",
        foreign_keys=[showing_id],
    )
    priority_showing = relationship(
        "Showing",
        foreign_keys=[priority_showing_id],
    )
