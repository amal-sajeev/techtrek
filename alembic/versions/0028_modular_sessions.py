"""Make sessions modular: add event_sessions join table, move event-specific
fields from sessions to event_sessions, add event_id to session_recordings."""

from alembic import op
import sqlalchemy as sa

revision = "0028"
down_revision = "0027"


def upgrade():
    op.create_table(
        "event_sessions",
        sa.Column("id", sa.Integer, primary_key=True, index=True),
        sa.Column("event_id", sa.Integer, sa.ForeignKey("events.id", ondelete="CASCADE"), nullable=False),
        sa.Column("session_id", sa.Integer, sa.ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("order", sa.Integer, default=0),
        sa.Column("start_time", sa.DateTime, nullable=True),
        sa.Column("speaker_id", sa.Integer, sa.ForeignKey("speakers.id", ondelete="SET NULL"), nullable=True),
        sa.Column("speaker_name", sa.String(200), nullable=True),
        sa.UniqueConstraint("event_id", "session_id", name="uq_event_session"),
    )

    op.add_column("session_recordings", sa.Column("event_id", sa.Integer, sa.ForeignKey("events.id", ondelete="CASCADE"), nullable=True))

    conn = op.get_bind()
    rows = conn.execute(sa.text(
        "SELECT id, event_id, start_time, \"order\", speaker_id, speaker_name "
        "FROM sessions WHERE event_id IS NOT NULL"
    )).fetchall()
    for row in rows:
        conn.execute(
            sa.text(
                "INSERT INTO event_sessions (event_id, session_id, \"order\", start_time, speaker_id, speaker_name) "
                "VALUES (:event_id, :session_id, :ord, :start_time, :speaker_id, :speaker_name)"
            ),
            {
                "event_id": row[1],
                "session_id": row[0],
                "ord": row[3] or 0,
                "start_time": row[2],
                "speaker_id": row[4],
                "speaker_name": row[5],
            },
        )
        conn.execute(
            sa.text("UPDATE session_recordings SET event_id = :eid WHERE session_id = :sid"),
            {"eid": row[1], "sid": row[0]},
        )

    op.drop_constraint("sessions_event_id_fkey", "sessions", type_="foreignkey")
    op.drop_column("sessions", "event_id")
    op.drop_column("sessions", "start_time")
    op.drop_column("sessions", "order")


def downgrade():
    op.add_column("sessions", sa.Column("order", sa.Integer, server_default="0"))
    op.add_column("sessions", sa.Column("start_time", sa.DateTime, nullable=True))
    op.add_column("sessions", sa.Column("event_id", sa.Integer, nullable=True))
    op.create_foreign_key("sessions_event_id_fkey", "sessions", "events", ["event_id"], ["id"], ondelete="CASCADE")

    conn = op.get_bind()
    rows = conn.execute(sa.text(
        "SELECT event_id, session_id, \"order\", start_time, speaker_id, speaker_name FROM event_sessions"
    )).fetchall()
    for row in rows:
        conn.execute(
            sa.text(
                "UPDATE sessions SET event_id = :eid, \"order\" = :ord, start_time = :st "
                "WHERE id = :sid"
            ),
            {"eid": row[0], "sid": row[1], "ord": row[2], "st": row[3]},
        )

    op.drop_column("session_recordings", "event_id")
    op.drop_table("event_sessions")
