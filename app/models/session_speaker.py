from sqlalchemy import Column, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import relationship

from app.database import Base

SPEAKER_ROLES = ["Keynote", "Panelist", "Workshop Lead", "Moderator", "Guest"]


class SessionSpeaker(Base):
    __tablename__ = "session_speakers"

    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(Integer, ForeignKey("lecture_sessions.id", ondelete="CASCADE"), nullable=False)
    speaker_id = Column(Integer, ForeignKey("speakers.id", ondelete="CASCADE"), nullable=False)
    role = Column(String(30), nullable=False, default="Guest")

    __table_args__ = (
        UniqueConstraint("session_id", "speaker_id", name="uq_session_speaker"),
    )

    session = relationship("LectureSession", back_populates="session_speakers")
    speaker = relationship("Speaker", back_populates="session_assignments")
