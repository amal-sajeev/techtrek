from sqlalchemy import Column, ForeignKey, Integer, UniqueConstraint
from sqlalchemy.orm import relationship

from app.database import Base


class EventShowing(Base):
    __tablename__ = "event_showings"

    id = Column(Integer, primary_key=True, index=True)
    event_id = Column(Integer, ForeignKey("events.id", ondelete="CASCADE"), nullable=False)
    showing_id = Column(Integer, ForeignKey("showings.id", ondelete="CASCADE"), nullable=False)

    __table_args__ = (
        UniqueConstraint("event_id", "showing_id", name="uq_event_showing"),
    )

    event = relationship("Event", back_populates="event_showings")
    showing = relationship("Showing", back_populates="event_showings")
