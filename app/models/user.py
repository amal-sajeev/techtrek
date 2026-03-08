from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, DateTime, Integer, String
from sqlalchemy.orm import relationship

from app.database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(255), unique=True, nullable=False, index=True)
    username = Column(String(100), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    full_name = Column(String(200), nullable=True)
    college = Column(String(300), nullable=True)
    discipline = Column(String(100), nullable=True)
    domain = Column(String(100), nullable=True)
    year_of_study = Column(Integer, nullable=True)
    is_admin = Column(Boolean, default=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    bookings = relationship("Booking", back_populates="user")
    waitlist_entries = relationship("Waitlist", back_populates="user")
