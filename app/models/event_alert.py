from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from app.database import Base
from app.utils import now_ist


class EventAlert(Base):
    __tablename__ = "event_alerts"

    id = Column(Integer, primary_key=True, index=True)
    event_id = Column(Integer, ForeignKey("events.id", ondelete="CASCADE"), nullable=False)
    admin_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    message = Column(Text, nullable=False)
    alert_type = Column(String(20), nullable=False, default="info")
    created_at = Column(DateTime, default=now_ist)

    event = relationship("Event")
    admin = relationship("User")
