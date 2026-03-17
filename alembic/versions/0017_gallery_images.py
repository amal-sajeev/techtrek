"""Add gallery_images table for multi-image galleries on events and sessions.

Revision ID: 0017
Revises: 0016
"""
from alembic import op
import sqlalchemy as sa

revision = "0017"
down_revision = "0016"


def upgrade():
    op.create_table(
        "gallery_images",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("owner_type", sa.String(20), nullable=False),
        sa.Column("owner_id", sa.Integer, nullable=False),
        sa.Column("image_id", sa.Integer, sa.ForeignKey("uploaded_images.id", ondelete="CASCADE"), nullable=False),
        sa.Column("position", sa.Integer, default=0),
        sa.Column("created_at", sa.DateTime, nullable=True),
    )
    op.create_index("ix_gallery_owner", "gallery_images", ["owner_type", "owner_id"])


def downgrade():
    op.drop_index("ix_gallery_owner", "gallery_images")
    op.drop_table("gallery_images")
