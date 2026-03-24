"""Split session description into abstract and key_learning_outcomes columns."""

from alembic import op
import sqlalchemy as sa

revision = "0030"
down_revision = "0029"


def upgrade():
    op.add_column("sessions", sa.Column("abstract", sa.Text, nullable=True))
    op.add_column("sessions", sa.Column("key_learning_outcomes", sa.Text, nullable=True))
    op.execute("UPDATE sessions SET abstract = description WHERE description IS NOT NULL AND description != ''")


def downgrade():
    op.drop_column("sessions", "key_learning_outcomes")
    op.drop_column("sessions", "abstract")
