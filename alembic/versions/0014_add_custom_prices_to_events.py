"""Add custom_prices JSON column to events.

Revision ID: 0014
Revises: 0013
Create Date: 2026-03-17
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSON

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("events", sa.Column("custom_prices", JSON, nullable=True))


def downgrade():
    op.drop_column("events", "custom_prices")
