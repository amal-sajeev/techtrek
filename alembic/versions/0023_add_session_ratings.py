"""Add session ratings: template flags, submitted_at on feedback, session_ratings table.

Revision ID: 0023
Revises: 0022
"""
from alembic import op
import sqlalchemy as sa

revision = "0023"
down_revision = "0022"


def upgrade():
    op.add_column(
        "feedback_templates",
        sa.Column("session_ratings_enabled", sa.Boolean, nullable=False, server_default="true"),
    )
    op.add_column(
        "feedback_templates",
        sa.Column("session_ratings_required", sa.Boolean, nullable=False, server_default="false"),
    )
    op.add_column(
        "feedback",
        sa.Column("submitted_at", sa.DateTime, nullable=True),
    )
    op.create_table(
        "session_ratings",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("feedback_id", sa.Integer, sa.ForeignKey("feedback.id", ondelete="CASCADE"), nullable=False),
        sa.Column("session_id", sa.Integer, sa.ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("rating", sa.Integer, nullable=False),
    )
    # Backfill: mark existing rated feedback as submitted
    op.execute("UPDATE feedback SET submitted_at = created_at WHERE rating IS NOT NULL")


def downgrade():
    op.drop_table("session_ratings")
    op.drop_column("feedback", "submitted_at")
    op.drop_column("feedback_templates", "session_ratings_required")
    op.drop_column("feedback_templates", "session_ratings_enabled")
