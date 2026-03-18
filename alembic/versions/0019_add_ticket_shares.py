"""Add ticket_shares table for tracking shared tickets.

Revision ID: 0019
Revises: 0018
"""
from alembic import op
import sqlalchemy as sa

revision = "0019"
down_revision = "0018"


def upgrade():
    op.create_table(
        "ticket_shares",
        sa.Column("id", sa.Integer, primary_key=True, index=True),
        sa.Column("ticket_id", sa.String(100), nullable=False, index=True),
        sa.Column("recipient_name", sa.String(200), nullable=False),
        sa.Column("recipient_email", sa.String(300), nullable=False),
        sa.Column("shared_by", sa.Integer, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("shared_at", sa.DateTime, nullable=True),
    )


def downgrade():
    op.drop_table("ticket_shares")
