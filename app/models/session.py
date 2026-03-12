from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import relationship

from app.database import Base
from app.utils import now_ist


class LectureSession(Base):
    __tablename__ = "lecture_sessions"

    id = Column(Integer, primary_key=True, index=True)
    auditorium_id = Column(Integer, ForeignKey("auditoriums.id"), nullable=False)
    speaker_id = Column(Integer, ForeignKey("speakers.id"), nullable=True)
    title = Column(String(300), nullable=False)
    speaker = Column(String(200), nullable=False)
    description = Column(Text, nullable=True)
    banner_url = Column(String(500), nullable=True)
    start_time = Column(DateTime, nullable=False)
    duration_minutes = Column(Integer, default=30)
    price = Column(Numeric(10, 2), nullable=False, default=0)
    price_vip = Column(Numeric(10, 2), nullable=True)
    price_accessible = Column(Numeric(10, 2), nullable=True)
    status = Column(String(20), default="draft")
    cert_title = Column(String(300), nullable=True)
    cert_subtitle = Column(Text, nullable=True)
    cert_footer = Column(String(500), nullable=True)
    cert_signer_name = Column(String(200), nullable=True)
    cert_signer_designation = Column(String(200), nullable=True)
    cert_logo_url = Column(String(500), nullable=True)
    cert_bg_url = Column(String(500), nullable=True)
    cert_color_scheme = Column(String(20), nullable=True)
    recording_url = Column(String(500), nullable=True)
    is_recording_public = Column(Boolean, default=False)
    created_at = Column(DateTime, default=now_ist)

    auditorium = relationship("Auditorium", back_populates="sessions")
    speaker_rel = relationship("Speaker", back_populates="sessions")
    session_speakers = relationship("SessionSpeaker", back_populates="session", cascade="all, delete-orphan")
    bookings = relationship("Booking", back_populates="session")
    agenda_items = relationship("AgendaItem", back_populates="session", cascade="all, delete-orphan", order_by="AgendaItem.order")
    session_recordings = relationship("SessionRecording", back_populates="session", cascade="all, delete-orphan", order_by="SessionRecording.order")
    waitlist_entries = relationship(
        "Waitlist",
        back_populates="session",
        foreign_keys="Waitlist.session_id",
    )
