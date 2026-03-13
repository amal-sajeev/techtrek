from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from app.database import Base
from app.utils import now_ist


class Session(Base):
    __tablename__ = "sessions"

    id = Column(Integer, primary_key=True, index=True)
    speaker_id = Column(Integer, ForeignKey("speakers.id", ondelete="SET NULL"), nullable=True)
    title = Column(String(300), nullable=False)
    speaker_name = Column(String(200), nullable=False)
    description = Column(Text, nullable=True)
    banner_url = Column(String(500), nullable=True)
    duration_minutes = Column(Integer, default=30)
    cert_title = Column(String(300), nullable=True)
    cert_subtitle = Column(Text, nullable=True)
    cert_footer = Column(String(500), nullable=True)
    cert_signer_name = Column(String(200), nullable=True)
    cert_signer_designation = Column(String(200), nullable=True)
    cert_logo_url = Column(String(500), nullable=True)
    cert_bg_url = Column(String(500), nullable=True)
    cert_signature_url = Column(String(500), nullable=True)
    cert_color_scheme = Column(String(20), nullable=True)
    cert_style = Column(Text, nullable=True)
    recording_url = Column(String(500), nullable=True)
    is_recording_public = Column(Boolean, default=False)
    created_at = Column(DateTime, default=now_ist)

    speaker_rel = relationship("Speaker", back_populates="sessions")
    session_speakers = relationship("SessionSpeaker", back_populates="session", cascade="all, delete-orphan")
    agenda_items = relationship("AgendaItem", back_populates="session", cascade="all, delete-orphan", order_by="AgendaItem.order")
    session_recordings = relationship("SessionRecording", back_populates="session", cascade="all, delete-orphan", order_by="SessionRecording.order")
    showings = relationship("Showing", back_populates="session", cascade="all, delete-orphan")
