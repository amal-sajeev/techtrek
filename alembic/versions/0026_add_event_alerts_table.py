"""Add event_alerts table for admin-to-attendee notifications."""

from alembic import op
import sqlalchemy as sa

revision = "0026"
down_revision = "0025"


def upgrade():
    op.create_table(
        "event_alerts",
        sa.Column("id", sa.Integer, primary_key=True, index=True),
        sa.Column("event_id", sa.Integer, sa.ForeignKey("events.id", ondelete="CASCADE"), nullable=False),
        sa.Column("admin_id", sa.Integer, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("message", sa.Text, nullable=False),
        sa.Column("alert_type", sa.String(20), nullable=False, server_default="info"),
        sa.Column("created_at", sa.DateTime, nullable=True),
    )


def downgrade():
    op.drop_table("event_alerts")
