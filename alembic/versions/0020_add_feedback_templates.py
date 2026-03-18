"""Add feedback templates, questions, responses, and link to events.

Revision ID: 0020
Revises: 0019
"""
from alembic import op
import sqlalchemy as sa

revision = "0020"
down_revision = "0019"


def upgrade():
    op.create_table(
        "feedback_templates",
        sa.Column("id", sa.Integer, primary_key=True, index=True),
        sa.Column("name", sa.String(300), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("created_by", sa.Integer, sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=True),
    )

    op.create_table(
        "template_questions",
        sa.Column("id", sa.Integer, primary_key=True, index=True),
        sa.Column("template_id", sa.Integer, sa.ForeignKey("feedback_templates.id", ondelete="CASCADE"), nullable=False),
        sa.Column("order", sa.Integer, default=0),
        sa.Column("question_text", sa.Text, nullable=False),
        sa.Column("question_type", sa.String(30), nullable=False, server_default="text"),
        sa.Column("options_json", sa.JSON, nullable=True),
        sa.Column("is_required", sa.Boolean, server_default="0"),
    )

    op.create_table(
        "feedback_responses",
        sa.Column("id", sa.Integer, primary_key=True, index=True),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("event_id", sa.Integer, sa.ForeignKey("events.id"), nullable=False),
        sa.Column("template_id", sa.Integer, sa.ForeignKey("feedback_templates.id"), nullable=True),
        sa.Column("overall_rating", sa.Integer, nullable=True),
        sa.Column("comment", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=True),
    )

    op.create_table(
        "question_responses",
        sa.Column("id", sa.Integer, primary_key=True, index=True),
        sa.Column("response_id", sa.Integer, sa.ForeignKey("feedback_responses.id", ondelete="CASCADE"), nullable=False),
        sa.Column("question_id", sa.Integer, sa.ForeignKey("template_questions.id"), nullable=False),
        sa.Column("answer_text", sa.Text, nullable=True),
    )

    op.add_column("events", sa.Column("feedback_template_id", sa.Integer, sa.ForeignKey("feedback_templates.id"), nullable=True))


def downgrade():
    op.drop_column("events", "feedback_template_id")
    op.drop_table("question_responses")
    op.drop_table("feedback_responses")
    op.drop_table("template_questions")
    op.drop_table("feedback_templates")
