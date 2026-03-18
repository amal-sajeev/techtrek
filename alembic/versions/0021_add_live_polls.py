"""Add polls, poll_options, poll_votes tables for live polling.

Revision ID: 0021
Revises: 0020
"""
from alembic import op
import sqlalchemy as sa

revision = "0021"
down_revision = "0020"


def upgrade():
    op.create_table(
        "polls",
        sa.Column("id", sa.Integer, primary_key=True, index=True),
        sa.Column("session_id", sa.Integer, sa.ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("question", sa.Text, nullable=False),
        sa.Column("is_active", sa.Boolean, server_default="0"),
        sa.Column("allow_multiple", sa.Boolean, server_default="0"),
        sa.Column("created_by", sa.Integer, sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=True),
        sa.Column("closed_at", sa.DateTime, nullable=True),
    )

    op.create_table(
        "poll_options",
        sa.Column("id", sa.Integer, primary_key=True, index=True),
        sa.Column("poll_id", sa.Integer, sa.ForeignKey("polls.id", ondelete="CASCADE"), nullable=False),
        sa.Column("option_text", sa.String(500), nullable=False),
        sa.Column("order", sa.Integer, server_default="0"),
    )

    op.create_table(
        "poll_votes",
        sa.Column("id", sa.Integer, primary_key=True, index=True),
        sa.Column("poll_id", sa.Integer, sa.ForeignKey("polls.id", ondelete="CASCADE"), nullable=False),
        sa.Column("option_id", sa.Integer, sa.ForeignKey("poll_options.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("voted_at", sa.DateTime, nullable=True),
        sa.UniqueConstraint("poll_id", "user_id", name="uq_poll_vote_user"),
    )


def downgrade():
    op.drop_table("poll_votes")
    op.drop_table("poll_options")
    op.drop_table("polls")
