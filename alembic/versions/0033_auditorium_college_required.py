"""Make auditorium.college_id non-nullable."""

from alembic import op
import sqlalchemy as sa

revision = "0033"
down_revision = "0032"


def upgrade():
    op.execute(
        "DELETE FROM auditoriums WHERE college_id IS NULL"
    )
    op.alter_column(
        "auditoriums",
        "college_id",
        existing_type=sa.Integer(),
        nullable=False,
    )


def downgrade():
    op.alter_column(
        "auditoriums",
        "college_id",
        existing_type=sa.Integer(),
        nullable=True,
    )
