"""Add feedback table for post-session ratings and testimonials.

Revision ID: 0006
Revises: 0005
Create Date: 2026-03-13
"""

from alembic import op
import sqlalchemy as sa

revision = "0006"
down_revision = "0005"
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
    if not _table_exists("feedback"):
        op.create_table(
            "feedback",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("user_id", sa.Integer(),
                      sa.ForeignKey("users.id"), nullable=False),
            sa.Column("showing_id", sa.Integer(),
                      sa.ForeignKey("showings.id"), nullable=False),
            sa.Column("rating", sa.Integer(), nullable=True),
            sa.Column("comment", sa.Text(), nullable=True),
            sa.Column("allow_public", sa.Boolean(), server_default="false"),
            sa.Column("is_featured", sa.Boolean(), server_default="false"),
            sa.Column("dismissed", sa.Boolean(), server_default="false"),
            sa.Column("email_sent", sa.Boolean(), server_default="false"),
            sa.Column("email_sent_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.UniqueConstraint("user_id", "showing_id", name="uq_feedback_user_showing"),
        )
        op.create_index("ix_feedback_id", "feedback", ["id"])


def downgrade() -> None:
    op.drop_table("feedback")
