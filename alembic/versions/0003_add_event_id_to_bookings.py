"""Add event_id column to bookings table

Revision ID: 0003
Revises: 0002
Create Date: 2026-03-13
"""
from alembic import op
import sqlalchemy as sa


revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def _col_exists(table: str, col: str) -> bool:
    conn = op.get_bind()
    result = conn.execute(
        sa.text(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_name = :t AND column_name = :c"
        ),
        {"t": table, "c": col},
    )
    return result.scalar() is not None


def upgrade() -> None:
    if not _col_exists("bookings", "event_id"):
        op.add_column("bookings", sa.Column("event_id", sa.Integer(), nullable=True))
        op.create_foreign_key(
            "fk_bookings_event_id", "bookings", "events",
            ["event_id"], ["id"], ondelete="SET NULL",
        )


def downgrade() -> None:
    op.drop_constraint("fk_bookings_event_id", "bookings", type_="foreignkey")
    op.drop_column("bookings", "event_id")
