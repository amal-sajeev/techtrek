from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text, Boolean
from sqlalchemy.dialects.postgresql import JSON
from sqlalchemy.orm import relationship

from app.database import Base
from app.utils import now_ist


class FeedbackTemplate(Base):
    __tablename__ = "feedback_templates"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(300), nullable=False)
    description = Column(Text, nullable=True)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=now_ist)

    questions = relationship(
        "TemplateQuestion",
        back_populates="template",
        cascade="all, delete-orphan",
        order_by="TemplateQuestion.order",
    )
    events = relationship("Event", back_populates="feedback_template")


class TemplateQuestion(Base):
    __tablename__ = "template_questions"

    id = Column(Integer, primary_key=True, index=True)
    template_id = Column(Integer, ForeignKey("feedback_templates.id", ondelete="CASCADE"), nullable=False)
    order = Column(Integer, default=0)
    question_text = Column(Text, nullable=False)
    question_type = Column(String(30), nullable=False, default="text")
    options_json = Column(JSON, nullable=True)
    is_required = Column(Boolean, default=False)

    template = relationship("FeedbackTemplate", back_populates="questions")


class FeedbackResponse(Base):
    __tablename__ = "feedback_responses"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    event_id = Column(Integer, ForeignKey("events.id"), nullable=False)
    template_id = Column(Integer, ForeignKey("feedback_templates.id"), nullable=True)
    overall_rating = Column(Integer, nullable=True)
    comment = Column(Text, nullable=True)
    created_at = Column(DateTime, default=now_ist)

    user = relationship("User", backref="feedback_responses")
    event = relationship("Event", backref="feedback_responses")
    template = relationship("FeedbackTemplate")
    answers = relationship(
        "QuestionResponse",
        back_populates="response",
        cascade="all, delete-orphan",
    )


class QuestionResponse(Base):
    __tablename__ = "question_responses"

    id = Column(Integer, primary_key=True, index=True)
    response_id = Column(Integer, ForeignKey("feedback_responses.id", ondelete="CASCADE"), nullable=False)
    question_id = Column(Integer, ForeignKey("template_questions.id"), nullable=False)
    answer_text = Column(Text, nullable=True)

    response = relationship("FeedbackResponse", back_populates="answers")
    question = relationship("TemplateQuestion")
