from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer
from sqlalchemy.orm import relationship

from app.database import Base
from app.utils import now_ist


class Waitlist(Base):
    __tablename__ = "waitlist"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    session_id = Column(Integer, ForeignKey("lecture_sessions.id"), nullable=False)
    priority_session_id = Column(
        Integer, ForeignKey("lecture_sessions.id"), nullable=True
    )
    joined_at = Column(DateTime, default=now_ist)
    notified = Column(Boolean, default=False)
    priority_expires_at = Column(DateTime, nullable=True)

    user = relationship("User", back_populates="waitlist_entries")
    session = relationship(
        "LectureSession",
        back_populates="waitlist_entries",
        foreign_keys=[session_id],
    )
    priority_session = relationship(
        "LectureSession",
        foreign_keys=[priority_session_id],
    )
