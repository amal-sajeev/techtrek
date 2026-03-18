from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from app.database import Base


class EventBreak(Base):
    __tablename__ = "event_breaks"

    id = Column(Integer, primary_key=True, index=True)
    event_id = Column(Integer, ForeignKey("events.id", ondelete="CASCADE"), nullable=False)
    title = Column(String(300), nullable=False)
    description = Column(Text, nullable=True)
    duration_minutes = Column(Integer, default=15)
    start_time = Column(DateTime, nullable=True)
    order = Column(Integer, default=0)

    event = relationship("Event", back_populates="breaks")
