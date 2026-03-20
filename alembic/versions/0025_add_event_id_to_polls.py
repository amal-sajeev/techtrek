"""Add event_id to polls so polls are scoped to a (session, event) pair."""

from alembic import op
import sqlalchemy as sa

revision = "0025"
down_revision = "0024"


def upgrade():
    op.add_column(
        "polls",
        sa.Column("event_id", sa.Integer, nullable=True),
    )
    op.execute(
        "UPDATE polls SET event_id = (SELECT event_id FROM sessions WHERE sessions.id = polls.session_id)"
    )
    op.alter_column("polls", "event_id", nullable=False)
    op.create_foreign_key(
        "fk_polls_event_id", "polls", "events", ["event_id"], ["id"], ondelete="CASCADE"
    )


def downgrade():
    op.drop_constraint("fk_polls_event_id", "polls", type_="foreignkey")
    op.drop_column("polls", "event_id")
