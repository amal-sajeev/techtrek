from sqlalchemy import Boolean, Column, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import relationship

from app.database import Base


class EventAddOn(Base):
    __tablename__ = "event_addons"

    id = Column(Integer, primary_key=True, index=True)
    event_id = Column(Integer, ForeignKey("events.id", ondelete="CASCADE"), nullable=False)
    title = Column(String(300), nullable=False)
    description = Column(Text, nullable=True)
    price = Column(Numeric(10, 2), nullable=False, default=0)
    max_quantity = Column(Integer, nullable=True)
    is_active = Column(Boolean, default=True)

    event = relationship("Event", back_populates="addons")
    booking_addons = relationship("BookingAddOn", back_populates="addon", cascade="all, delete-orphan")


class BookingAddOn(Base):
    __tablename__ = "booking_addons"

    id = Column(Integer, primary_key=True, index=True)
    booking_group = Column(String(36), nullable=False, index=True)
    addon_id = Column(Integer, ForeignKey("event_addons.id", ondelete="CASCADE"), nullable=False)
    quantity = Column(Integer, default=1)

    addon = relationship("EventAddOn", back_populates="booking_addons")
