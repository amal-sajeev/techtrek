"""Add deleted_at column to users table."""

from alembic import op
import sqlalchemy as sa

revision = "0034"
down_revision = "0033"


def upgrade():
    op.add_column("users", sa.Column("deleted_at", sa.DateTime(), nullable=True))


def downgrade():
    op.drop_column("users", "deleted_at")
