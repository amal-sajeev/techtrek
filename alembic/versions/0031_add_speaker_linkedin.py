"""Add linkedin_url column to speakers table."""

from alembic import op
import sqlalchemy as sa

revision = "0031"
down_revision = "0030"


def upgrade():
    op.add_column("speakers", sa.Column("linkedin_url", sa.String(500), nullable=True))


def downgrade():
    op.drop_column("speakers", "linkedin_url")
