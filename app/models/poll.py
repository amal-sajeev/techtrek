from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import relationship

from app.database import Base
from app.utils import now_ist


class Poll(Base):
    __tablename__ = "polls"

    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(Integer, ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False)
    question = Column(Text, nullable=False)
    is_active = Column(Boolean, default=False)
    allow_multiple = Column(Boolean, default=False)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=now_ist)
    closed_at = Column(DateTime, nullable=True)

    session = relationship("Session", backref="polls")
    options = relationship("PollOption", back_populates="poll", cascade="all, delete-orphan", order_by="PollOption.order")
    creator = relationship("User", backref="created_polls")


class PollOption(Base):
    __tablename__ = "poll_options"

    id = Column(Integer, primary_key=True, index=True)
    poll_id = Column(Integer, ForeignKey("polls.id", ondelete="CASCADE"), nullable=False)
    option_text = Column(String(500), nullable=False)
    order = Column(Integer, default=0)

    poll = relationship("Poll", back_populates="options")
    votes = relationship("PollVote", back_populates="option", cascade="all, delete-orphan")


class PollVote(Base):
    __tablename__ = "poll_votes"

    id = Column(Integer, primary_key=True, index=True)
    poll_id = Column(Integer, ForeignKey("polls.id", ondelete="CASCADE"), nullable=False)
    option_id = Column(Integer, ForeignKey("poll_options.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    voted_at = Column(DateTime, default=now_ist)

    __table_args__ = (
        UniqueConstraint("poll_id", "user_id", name="uq_poll_vote_user"),
    )

    poll = relationship("Poll", backref="votes")
    option = relationship("PollOption", back_populates="votes")
    user = relationship("User", backref="poll_votes")
