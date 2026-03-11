from sqlalchemy import Boolean, Column, DateTime, Integer, String, Text

from app.database import Base
from app.utils import now_ist


class WebhookLog(Base):
    __tablename__ = "webhook_logs"

    id = Column(Integer, primary_key=True, index=True)
    event_type = Column(String(100), nullable=False)
    razorpay_event_id = Column(String(100), nullable=True)
    payload = Column(Text, nullable=False)
    received_at = Column(DateTime, default=now_ist, nullable=False)
    processed = Column(Boolean, default=False)
