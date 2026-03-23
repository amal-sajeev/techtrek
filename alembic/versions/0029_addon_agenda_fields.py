"""Add in_agenda, order, start_time columns to event_addons so add-ons
can optionally appear in the event agenda alongside sessions and breaks."""

from alembic import op
import sqlalchemy as sa

revision = "0029"
down_revision = "0028"


def upgrade():
    op.add_column("event_addons", sa.Column("in_agenda", sa.Boolean, server_default="false", nullable=False))
    op.add_column("event_addons", sa.Column("order", sa.Integer, server_default="0", nullable=False))
    op.add_column("event_addons", sa.Column("start_time", sa.DateTime, nullable=True))


def downgrade():
    op.drop_column("event_addons", "start_time")
    op.drop_column("event_addons", "order")
    op.drop_column("event_addons", "in_agenda")
