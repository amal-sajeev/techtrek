from sqlalchemy import Column, Integer, String, Text, JSON
from sqlalchemy.orm import relationship

from app.database import Base


class Auditorium(Base):
    __tablename__ = "auditoriums"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(200), nullable=False)
    location = Column(String(300), nullable=False)
    description = Column(Text, nullable=True)
    total_rows = Column(Integer, nullable=False, default=10)
    total_cols = Column(Integer, nullable=False, default=15)
    layout_config = Column(JSON, nullable=True)

    seats = relationship("Seat", back_populates="auditorium", cascade="all, delete-orphan")
    sessions = relationship("LectureSession", back_populates="auditorium")
