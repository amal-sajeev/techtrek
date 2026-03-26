from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import relationship

from app.database import Base


class EventSession(Base):
    __tablename__ = "event_sessions"

    id = Column(Integer, primary_key=True, index=True)
    event_id = Column(Integer, ForeignKey("events.id", ondelete="CASCADE"), nullable=False)
    session_id = Column(Integer, ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False)
    order = Column(Integer, default=0)
    start_time = Column(DateTime, nullable=True)
    speaker_id = Column(Integer, ForeignKey("speakers.id", ondelete="SET NULL"), nullable=True)
    speaker_name = Column(String(200), nullable=True)

    custom_title = Column(String(300), nullable=True)
    custom_description = Column(Text, nullable=True)
    custom_abstract = Column(Text, nullable=True)
    custom_key_learning_outcomes = Column(Text, nullable=True)
    custom_banner_url = Column(String(500), nullable=True)
    custom_duration_minutes = Column(Integer, nullable=True)
    custom_recording_url = Column(String(500), nullable=True)
    custom_is_recording_public = Column(Boolean, nullable=True)

    __table_args__ = (
        UniqueConstraint("event_id", "session_id", name="uq_event_session"),
    )

    event = relationship("Event", back_populates="event_sessions")
    session = relationship("Session", back_populates="event_sessions")
    speaker = relationship("Speaker")

    @property
    def display_title(self):
        return self.custom_title if self.custom_title is not None else self.session.title

    @property
    def display_description(self):
        return self.custom_description if self.custom_description is not None else self.session.description

    @property
    def display_abstract(self):
        return self.custom_abstract if self.custom_abstract is not None else self.session.abstract

    @property
    def display_key_learning_outcomes(self):
        return self.custom_key_learning_outcomes if self.custom_key_learning_outcomes is not None else self.session.key_learning_outcomes

    @property
    def display_banner_url(self):
        return self.custom_banner_url if self.custom_banner_url is not None else self.session.banner_url

    @property
    def display_duration_minutes(self):
        return self.custom_duration_minutes if self.custom_duration_minutes is not None else self.session.duration_minutes

    @property
    def display_recording_url(self):
        return self.custom_recording_url if self.custom_recording_url is not None else self.session.recording_url

    @property
    def display_is_recording_public(self):
        return self.custom_is_recording_public if self.custom_is_recording_public is not None else self.session.is_recording_public

    @property
    def display_speaker_name(self):
        return self.speaker_name if self.speaker_name else self.session.speaker_name

    @property
    def is_customized(self):
        return any([
            self.custom_title is not None,
            self.custom_description is not None,
            self.custom_abstract is not None,
            self.custom_key_learning_outcomes is not None,
            self.custom_banner_url is not None,
            self.custom_duration_minutes is not None,
            self.custom_recording_url is not None,
            self.custom_is_recording_public is not None,
        ])
