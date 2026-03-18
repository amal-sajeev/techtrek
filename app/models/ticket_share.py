from sqlalchemy import Column, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import relationship

from app.database import Base
from app.utils import now_ist


class TicketShare(Base):
    __tablename__ = "ticket_shares"

    id = Column(Integer, primary_key=True, index=True)
    ticket_id = Column(String(100), nullable=False, index=True)
    recipient_name = Column(String(200), nullable=False)
    recipient_email = Column(String(300), nullable=False)
    shared_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    shared_at = Column(DateTime, default=now_ist)

    sender = relationship("User", backref="ticket_shares")
