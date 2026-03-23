from sqlalchemy import Column, Date, DateTime, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSON
from sqlalchemy.orm import relationship

from app.database import Base
from app.utils import now_ist


class Event(Base):
    __tablename__ = "events"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(300), nullable=False)
    description = Column(Text, nullable=True)
    banner_url = Column(String(500), nullable=True)
    college_id = Column(Integer, ForeignKey("colleges.id"), nullable=True)
    auditorium_id = Column(Integer, ForeignKey("auditoriums.id"), nullable=True)
    start_date = Column(Date, nullable=True)
    end_date = Column(Date, nullable=True)
    price = Column(Numeric(10, 2), nullable=False, default=0)
    price_vip = Column(Numeric(10, 2), nullable=True)
    price_accessible = Column(Numeric(10, 2), nullable=True)
    processing_fee_pct = Column(Numeric(5, 2), nullable=True, default=0)
    custom_prices = Column(JSON, nullable=True)
    status = Column(String(20), default="draft")
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
    feedback_template_id = Column(Integer, ForeignKey("feedback_templates.id"), nullable=True)
    created_at = Column(DateTime, default=now_ist)

    college = relationship("College")
    auditorium = relationship("Auditorium", back_populates="events")
    event_sessions = relationship("EventSession", back_populates="event", cascade="all, delete-orphan", order_by="EventSession.order, EventSession.start_time")
    bookings = relationship("Booking", back_populates="event")
    coupons = relationship("Coupon", back_populates="event")
    breaks = relationship("EventBreak", back_populates="event", cascade="all, delete-orphan", order_by="EventBreak.order, EventBreak.start_time")
    addons = relationship("EventAddOn", back_populates="event", cascade="all, delete-orphan")
    waitlist_entries = relationship("Waitlist", back_populates="event")
    feedback_template = relationship("FeedbackTemplate", back_populates="events")
