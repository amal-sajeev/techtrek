from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import relationship

from app.database import Base


class EventSession(Base):
    __tablename__ = "event_sessions"

    id = Column(Integer, primary_key=True, index=True)
    event_id = Column(Integer, ForeignKey("events.id", ondelete="CASCADE"), nullable=False)
    session_id = Column(Integer, ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False)
    order = Column(Integer, default=0)
    start_time = Column(DateTime, nullable=True)
    speaker_id = Column(Integer, ForeignKey("speakers.id", ondelete="SET NULL"), nullable=True)
    speaker_name = Column(String(200), nullable=True)

    __table_args__ = (
        UniqueConstraint("event_id", "session_id", name="uq_event_session"),
    )

    event = relationship("Event", back_populates="event_sessions")
    session = relationship("Session", back_populates="event_sessions")
    speaker = relationship("Speaker")
