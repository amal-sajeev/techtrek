"""Add poll_type to polls, rating_value and text_answer to poll_votes."""

from alembic import op
import sqlalchemy as sa

revision = "0024"
down_revision = "0023"


def upgrade():
    op.add_column(
        "polls",
        sa.Column("poll_type", sa.String(30), nullable=False, server_default="multiple_choice"),
    )
    op.add_column(
        "poll_votes",
        sa.Column("rating_value", sa.Integer, nullable=True),
    )
    op.add_column(
        "poll_votes",
        sa.Column("text_answer", sa.Text, nullable=True),
    )
    op.alter_column("poll_votes", "option_id", existing_type=sa.Integer(), nullable=True)


def downgrade():
    op.alter_column("poll_votes", "option_id", existing_type=sa.Integer(), nullable=False)
    op.drop_column("poll_votes", "text_answer")
    op.drop_column("poll_votes", "rating_value")
    op.drop_column("polls", "poll_type")
