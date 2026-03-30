from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from app.database import Base
from app.utils import now_ist


class CertificateTemplate(Base):
    __tablename__ = "certificate_templates"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(300), nullable=False)
    description = Column(Text, nullable=True)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)

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

    created_at = Column(DateTime, default=now_ist)
    updated_at = Column(DateTime, default=now_ist, onupdate=now_ist)

    creator = relationship("User", foreign_keys=[created_by])
    events = relationship("Event", back_populates="cert_template", foreign_keys="Event.cert_template_id")
