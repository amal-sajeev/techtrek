"""Add access_token column to uploaded_images for non-guessable URLs.

Revision ID: 0036
Revises: 0035
"""
import secrets

from alembic import op
import sqlalchemy as sa

revision = "0036"
down_revision = "0035"


def upgrade():
    op.add_column(
        "uploaded_images",
        sa.Column("access_token", sa.String(64), nullable=True),
    )

    conn = op.get_bind()
    rows = conn.execute(sa.text("SELECT id FROM uploaded_images")).fetchall()
    for (row_id,) in rows:
        token = secrets.token_hex(32)
        conn.execute(
            sa.text("UPDATE uploaded_images SET access_token = :token WHERE id = :id"),
            {"token": token, "id": row_id},
        )

    op.alter_column("uploaded_images", "access_token", nullable=True)
    op.create_unique_constraint("uq_uploaded_images_access_token", "uploaded_images", ["access_token"])
    op.create_index("ix_uploaded_images_access_token", "uploaded_images", ["access_token"])


def downgrade():
    op.drop_index("ix_uploaded_images_access_token", table_name="uploaded_images")
    op.drop_constraint("uq_uploaded_images_access_token", "uploaded_images", type_="unique")
    op.drop_column("uploaded_images", "access_token")
