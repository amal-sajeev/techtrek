from sqlalchemy import Boolean, Column, ForeignKey, Integer, String
from sqlalchemy.orm import relationship

from app.database import Base


class SessionRecording(Base):
    __tablename__ = "session_recordings"

    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(Integer, ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False)
    url = Column(String(500), nullable=False)
    title = Column(String(300), nullable=True)
    order = Column(Integer, default=0)
    is_public = Column(Boolean, default=False)

    session = relationship("Session", back_populates="session_recordings")
