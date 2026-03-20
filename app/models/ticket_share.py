import secrets

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import relationship

from app.database import Base
from app.utils import now_ist


def _generate_share_token():
    return secrets.token_urlsafe(32)


class TicketShare(Base):
    __tablename__ = "ticket_shares"

    id = Column(Integer, primary_key=True, index=True)
    ticket_id = Column(String(100), nullable=False, index=True)
    recipient_name = Column(String(200), nullable=False)
    recipient_email = Column(String(300), nullable=False)
    shared_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    shared_at = Column(DateTime, default=now_ist)
    share_token = Column(String(64), unique=True, nullable=False, index=True, default=_generate_share_token)
    claimed_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    claimed_at = Column(DateTime, nullable=True)

    sender = relationship("User", foreign_keys=[shared_by], backref="ticket_shares")
    claimer = relationship("User", foreign_keys=[claimed_by])
