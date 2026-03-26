"""Add per-event session override columns to event_sessions table."""

from alembic import op
import sqlalchemy as sa

revision = "0032"
down_revision = "0031"


def upgrade():
    op.add_column("event_sessions", sa.Column("custom_title", sa.String(300), nullable=True))
    op.add_column("event_sessions", sa.Column("custom_description", sa.Text(), nullable=True))
    op.add_column("event_sessions", sa.Column("custom_abstract", sa.Text(), nullable=True))
    op.add_column("event_sessions", sa.Column("custom_key_learning_outcomes", sa.Text(), nullable=True))
    op.add_column("event_sessions", sa.Column("custom_banner_url", sa.String(500), nullable=True))
    op.add_column("event_sessions", sa.Column("custom_duration_minutes", sa.Integer(), nullable=True))
    op.add_column("event_sessions", sa.Column("custom_recording_url", sa.String(500), nullable=True))
    op.add_column("event_sessions", sa.Column("custom_is_recording_public", sa.Boolean(), nullable=True))


def downgrade():
    op.drop_column("event_sessions", "custom_is_recording_public")
    op.drop_column("event_sessions", "custom_recording_url")
    op.drop_column("event_sessions", "custom_duration_minutes")
    op.drop_column("event_sessions", "custom_banner_url")
    op.drop_column("event_sessions", "custom_key_learning_outcomes")
    op.drop_column("event_sessions", "custom_abstract")
    op.drop_column("event_sessions", "custom_description")
    op.drop_column("event_sessions", "custom_title")
