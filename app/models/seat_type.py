from sqlalchemy import Boolean, Column, DateTime, Integer, String

from app.database import Base
from app.utils import now_ist


class SeatType(Base):
    __tablename__ = "seat_types"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(50), unique=True, nullable=False)
    colour = Column(String(7), nullable=False, default="#6366f1")
    icon = Column(String(30), nullable=True)
    is_custom = Column(Boolean, default=True)
    created_at = Column(DateTime, default=now_ist)
