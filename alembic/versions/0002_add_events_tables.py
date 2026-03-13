"""Add events and event_sessions tables

Revision ID: 0002
Revises: 0001
Create Date: 2026-03-13
"""
from alembic import op
import sqlalchemy as sa


revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def _table_exists(name: str) -> bool:
    conn = op.get_bind()
    result = conn.execute(
        sa.text("SELECT 1 FROM information_schema.tables WHERE table_name = :t"),
        {"t": name},
    )
    return result.scalar() is not None


def upgrade() -> None:
    if not _table_exists("events"):
        op.create_table(
            "events",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("name", sa.String(300), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("banner_url", sa.String(500), nullable=True),
            sa.Column("college_id", sa.Integer(), sa.ForeignKey("colleges.id"), nullable=True),
            sa.Column("discount_pct", sa.Numeric(5, 2), nullable=True),
            sa.Column("status", sa.String(20), server_default="draft"),
            sa.Column("created_at", sa.DateTime(), nullable=True),
        )
        op.create_index("ix_events_id", "events", ["id"])

    if not _table_exists("event_sessions"):
        op.create_table(
            "event_sessions",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("event_id", sa.Integer(), sa.ForeignKey("events.id", ondelete="CASCADE"), nullable=False),
            sa.Column("session_id", sa.Integer(), sa.ForeignKey("lecture_sessions.id", ondelete="CASCADE"), nullable=False),
            sa.UniqueConstraint("event_id", "session_id", name="uq_event_session"),
        )
        op.create_index("ix_event_sessions_id", "event_sessions", ["id"])


def downgrade() -> None:
    op.drop_table("event_sessions")
    op.drop_table("events")
