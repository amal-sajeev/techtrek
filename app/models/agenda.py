from sqlalchemy import Column, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from app.database import Base


class AgendaItem(Base):
    __tablename__ = "agenda_items"

    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(Integer, ForeignKey("sessions.id"), nullable=False)
    order = Column(Integer, default=0)
    title = Column(String(300), nullable=False)
    speaker_id = Column(Integer, ForeignKey("speakers.id", ondelete="SET NULL"), nullable=True)
    speaker_name = Column(String(200), nullable=True)
    duration_minutes = Column(Integer, default=20)
    description = Column(Text, nullable=True)

    session = relationship("Session", back_populates="agenda_items")
    speaker = relationship("Speaker")
