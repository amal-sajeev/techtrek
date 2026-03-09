from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import relationship

from app.database import Base
from app.dependencies import now_ist


class College(Base):
    __tablename__ = "colleges"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(300), nullable=False)
    city_id = Column(Integer, ForeignKey("cities.id"), nullable=False)
    address = Column(String(500), nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=now_ist)

    city = relationship("City", back_populates="colleges")
    auditoriums = relationship("Auditorium", back_populates="college")
