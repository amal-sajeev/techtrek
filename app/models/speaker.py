from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from app.database import Base
from app.utils import now_ist


class Speaker(Base):
    __tablename__ = "speakers"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True, unique=True)
    name = Column(String(200), nullable=False)
    title = Column(String(200), nullable=True)
    bio = Column(Text, nullable=True)
    photo_url = Column(String(500), nullable=True)
    email = Column(String(255), nullable=True)
    invite_token = Column(String(64), nullable=True, unique=True)
    invite_token_expires = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=now_ist)

    user = relationship("User", backref="speaker_profile")
    sessions = relationship("LectureSession", back_populates="speaker_rel")
    session_assignments = relationship("SessionSpeaker", back_populates="speaker", cascade="all, delete-orphan")
