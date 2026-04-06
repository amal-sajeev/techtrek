import secrets

from sqlalchemy import Column, DateTime, Integer, LargeBinary, String, func

from app.database import Base


def _generate_access_token() -> str:
    return secrets.token_hex(32)


class UploadedImage(Base):
    __tablename__ = "uploaded_images"

    id = Column(Integer, primary_key=True, autoincrement=True)
    filename = Column(String(255), nullable=False)
    content_type = Column(String(100), nullable=False)
    data = Column(LargeBinary, nullable=False)
    access_token = Column(String(64), default=_generate_access_token, unique=True, index=True)
    created_at = Column(DateTime, default=func.now())
