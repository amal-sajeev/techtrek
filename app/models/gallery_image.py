from sqlalchemy import Column, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import relationship

from app.database import Base
from app.utils import now_ist


class GalleryImage(Base):
    __tablename__ = "gallery_images"

    id = Column(Integer, primary_key=True, autoincrement=True)
    owner_type = Column(String(20), nullable=False)  # "event" or "session"
    owner_id = Column(Integer, nullable=False)
    image_id = Column(Integer, ForeignKey("uploaded_images.id", ondelete="CASCADE"), nullable=False)
    position = Column(Integer, default=0)
    created_at = Column(DateTime, default=now_ist)

    image = relationship("UploadedImage", lazy="joined")
