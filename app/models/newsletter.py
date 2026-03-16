from sqlalchemy import Column, DateTime, Integer, String, Text

from app.database import Base
from app.utils import now_ist


class Newsletter(Base):
    __tablename__ = "newsletters"

    id = Column(Integer, primary_key=True, index=True)
    subject = Column(String(500), nullable=False)
    body_html = Column(Text, nullable=False, default="")
    status = Column(String(20), nullable=False, default="draft")
    total_recipients = Column(Integer, default=0)
    sent_count = Column(Integer, default=0)
    failed_count = Column(Integer, default=0)
    created_at = Column(DateTime, default=now_ist)
    sent_at = Column(DateTime, nullable=True)
