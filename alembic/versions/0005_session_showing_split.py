"""Split lecture_sessions into sessions (content) and showings (occurrences).

Each existing lecture_sessions row becomes one sessions row (content) plus one
showings row (scheduling).  IDs are preserved: sessions.id = showings.id =
old lecture_sessions.id, so FK values in child tables only need their target
table changed, not their values.

Revision ID: 0005
Revises: 0004
Create Date: 2026-03-13
"""

from alembic import op
import sqlalchemy as sa

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def _table_exists(name: str) -> bool:
    conn = op.get_bind()
    result = conn.execute(
        sa.text("SELECT 1 FROM information_schema.tables WHERE table_name = :t"),
        {"t": name},
    )
    return result.scalar() is not None


def _col_exists(table: str, col: str) -> bool:
    conn = op.get_bind()
    result = conn.execute(
        sa.text(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_name = :t AND column_name = :c"
        ),
        {"t": table, "c": col},
    )
    return result.scalar() is not None


def _fk_exists(constraint_name: str) -> bool:
    conn = op.get_bind()
    result = conn.execute(
        sa.text(
            "SELECT 1 FROM information_schema.table_constraints "
            "WHERE constraint_name = :n AND constraint_type = 'FOREIGN KEY'"
        ),
        {"n": constraint_name},
    )
    return result.scalar() is not None


def upgrade() -> None:
    conn = op.get_bind()

    # ── 1. Create sessions table (content) ────────────────────────────────
    if not _table_exists("sessions"):
        op.create_table(
            "sessions",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("speaker_id", sa.Integer(),
                      sa.ForeignKey("speakers.id", ondelete="SET NULL"), nullable=True),
            sa.Column("title", sa.String(300), nullable=False),
            sa.Column("speaker_name", sa.String(200), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("banner_url", sa.String(500), nullable=True),
            sa.Column("duration_minutes", sa.Integer(), server_default="30"),
            sa.Column("cert_title", sa.String(300), nullable=True),
            sa.Column("cert_subtitle", sa.Text(), nullable=True),
            sa.Column("cert_footer", sa.String(500), nullable=True),
            sa.Column("cert_signer_name", sa.String(200), nullable=True),
            sa.Column("cert_signer_designation", sa.String(200), nullable=True),
            sa.Column("cert_logo_url", sa.String(500), nullable=True),
            sa.Column("cert_bg_url", sa.String(500), nullable=True),
            sa.Column("cert_signature_url", sa.String(500), nullable=True),
            sa.Column("cert_color_scheme", sa.String(20), nullable=True),
            sa.Column("cert_style", sa.Text(), nullable=True),
            sa.Column("recording_url", sa.String(500), nullable=True),
            sa.Column("is_recording_public", sa.Boolean(), server_default="false"),
            sa.Column("created_at", sa.DateTime(), nullable=True),
        )
        op.create_index("ix_sessions_id", "sessions", ["id"])

    # ── 2. Create showings table (scheduling) ─────────────────────────────
    if not _table_exists("showings"):
        op.create_table(
            "showings",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("session_id", sa.Integer(),
                      sa.ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False),
            sa.Column("auditorium_id", sa.Integer(),
                      sa.ForeignKey("auditoriums.id"), nullable=False),
            sa.Column("start_time", sa.DateTime(), nullable=False),
            sa.Column("duration_minutes", sa.Integer(), nullable=True),
            sa.Column("price", sa.Numeric(10, 2), nullable=False, server_default="0"),
            sa.Column("price_vip", sa.Numeric(10, 2), nullable=True),
            sa.Column("price_accessible", sa.Numeric(10, 2), nullable=True),
            sa.Column("processing_fee_pct", sa.Numeric(5, 2), nullable=True, server_default="0"),
            sa.Column("status", sa.String(20), server_default="draft"),
            sa.Column("created_at", sa.DateTime(), nullable=True),
        )
        op.create_index("ix_showings_id", "showings", ["id"])

    # ── 3. Migrate lecture_sessions data ──────────────────────────────────
    if _table_exists("lecture_sessions"):
        conn.execute(sa.text("""
            INSERT INTO sessions (id, speaker_id, title, speaker_name, description,
                banner_url, duration_minutes, cert_title, cert_subtitle, cert_footer,
                cert_signer_name, cert_signer_designation, cert_logo_url, cert_bg_url,
                cert_signature_url, cert_color_scheme, cert_style, recording_url,
                is_recording_public, created_at)
            SELECT id, speaker_id, title, speaker, description,
                banner_url, duration_minutes, cert_title, cert_subtitle, cert_footer,
                cert_signer_name, cert_signer_designation, cert_logo_url, cert_bg_url,
                cert_signature_url, cert_color_scheme, cert_style, recording_url,
                is_recording_public, created_at
            FROM lecture_sessions
        """))

        conn.execute(sa.text("""
            INSERT INTO showings (id, session_id, auditorium_id, start_time,
                duration_minutes, price, price_vip, price_accessible,
                processing_fee_pct, status, created_at)
            SELECT id, id, auditorium_id, start_time,
                duration_minutes, price, price_vip, price_accessible,
                processing_fee_pct, status, created_at
            FROM lecture_sessions
        """))

        # Reset sequences so new rows get correct IDs
        conn.execute(sa.text(
            "SELECT setval(pg_get_serial_sequence('sessions', 'id'), "
            "COALESCE((SELECT MAX(id) FROM sessions), 0) + 1, false)"
        ))
        conn.execute(sa.text(
            "SELECT setval(pg_get_serial_sequence('showings', 'id'), "
            "COALESCE((SELECT MAX(id) FROM showings), 0) + 1, false)"
        ))

    # ── 4. Create event_showings table and migrate event_sessions ─────────
    if not _table_exists("event_showings"):
        op.create_table(
            "event_showings",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("event_id", sa.Integer(),
                      sa.ForeignKey("events.id", ondelete="CASCADE"), nullable=False),
            sa.Column("showing_id", sa.Integer(),
                      sa.ForeignKey("showings.id", ondelete="CASCADE"), nullable=False),
            sa.UniqueConstraint("event_id", "showing_id", name="uq_event_showing"),
        )
        op.create_index("ix_event_showings_id", "event_showings", ["id"])

    if _table_exists("event_sessions"):
        conn.execute(sa.text("""
            INSERT INTO event_showings (event_id, showing_id)
            SELECT event_id, session_id
            FROM event_sessions
        """))

    # ── 5. Update bookings: session_id → showing_id ───────────────────────
    if not _col_exists("bookings", "showing_id"):
        op.add_column("bookings", sa.Column("showing_id", sa.Integer(), nullable=True))

        conn.execute(sa.text("UPDATE bookings SET showing_id = session_id"))

        op.alter_column("bookings", "showing_id", nullable=False)
        op.create_foreign_key(
            "fk_bookings_showing_id", "bookings", "showings",
            ["showing_id"], ["id"],
        )

    # Drop old session_id FK and column from bookings
    if _col_exists("bookings", "session_id"):
        # Drop the partial unique index first (references session_id)
        try:
            op.drop_index("uix_active_booking_seat", table_name="bookings")
        except Exception:
            pass

        # Drop FK (name may vary by database)
        for fk_name in ("bookings_session_id_fkey", "fk_bookings_session_id"):
            if _fk_exists(fk_name):
                op.drop_constraint(fk_name, "bookings", type_="foreignkey")

        op.drop_column("bookings", "session_id")

        # Recreate partial unique index with showing_id
        op.execute(sa.text(
            "CREATE UNIQUE INDEX uix_active_booking_seat "
            "ON bookings (showing_id, seat_id) "
            "WHERE payment_status IN ('hold', 'paid')"
        ))

    # ── 6. Update waitlist: session_id → showing_id, priority too ─────────
    if not _col_exists("waitlist", "showing_id"):
        op.add_column("waitlist", sa.Column("showing_id", sa.Integer(), nullable=True))
        conn.execute(sa.text("UPDATE waitlist SET showing_id = session_id"))
        op.alter_column("waitlist", "showing_id", nullable=False)
        op.create_foreign_key(
            "fk_waitlist_showing_id", "waitlist", "showings",
            ["showing_id"], ["id"],
        )

    if not _col_exists("waitlist", "priority_showing_id"):
        op.add_column("waitlist", sa.Column("priority_showing_id", sa.Integer(), nullable=True))
        conn.execute(sa.text("UPDATE waitlist SET priority_showing_id = priority_session_id"))
        op.create_foreign_key(
            "fk_waitlist_priority_showing_id", "waitlist", "showings",
            ["priority_showing_id"], ["id"],
        )

    if _col_exists("waitlist", "session_id"):
        for fk_name in ("waitlist_session_id_fkey", "fk_waitlist_session_id"):
            if _fk_exists(fk_name):
                op.drop_constraint(fk_name, "waitlist", type_="foreignkey")
        op.drop_column("waitlist", "session_id")

    if _col_exists("waitlist", "priority_session_id"):
        for fk_name in ("waitlist_priority_session_id_fkey", "fk_waitlist_priority_session_id"):
            if _fk_exists(fk_name):
                op.drop_constraint(fk_name, "waitlist", type_="foreignkey")
        op.drop_column("waitlist", "priority_session_id")

    # ── 7. Re-point FKs in content-linked tables to sessions ──────────────
    # agenda_items, session_speakers, session_recordings already use session_id
    # which has the same values, just need to swap the FK target table.
    for table, fk_candidates in [
        ("agenda_items", ["agenda_items_session_id_fkey", "fk_agenda_items_session_id"]),
        ("session_speakers", ["session_speakers_session_id_fkey", "fk_session_speakers_session_id"]),
        ("session_recordings", ["session_recordings_session_id_fkey", "fk_session_recordings_session_id"]),
    ]:
        for fk_name in fk_candidates:
            if _fk_exists(fk_name):
                op.drop_constraint(fk_name, table, type_="foreignkey")
        ondelete = "CASCADE" if table != "agenda_items" else None
        op.create_foreign_key(
            f"fk_{table}_session_id", table, "sessions",
            ["session_id"], ["id"],
            ondelete=ondelete,
        )

    # ── 8. Drop old tables ────────────────────────────────────────────────
    if _table_exists("event_sessions"):
        op.drop_table("event_sessions")

    if _table_exists("lecture_sessions"):
        op.drop_table("lecture_sessions")


def downgrade() -> None:
    conn = op.get_bind()

    # Recreate lecture_sessions from sessions + showings
    op.create_table(
        "lecture_sessions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("auditorium_id", sa.Integer(), sa.ForeignKey("auditoriums.id"), nullable=False),
        sa.Column("speaker_id", sa.Integer(), sa.ForeignKey("speakers.id", ondelete="SET NULL"), nullable=True),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("speaker", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("banner_url", sa.String(500), nullable=True),
        sa.Column("start_time", sa.DateTime(), nullable=False),
        sa.Column("duration_minutes", sa.Integer(), server_default="30"),
        sa.Column("price", sa.Numeric(10, 2), nullable=False, server_default="0"),
        sa.Column("price_vip", sa.Numeric(10, 2), nullable=True),
        sa.Column("price_accessible", sa.Numeric(10, 2), nullable=True),
        sa.Column("processing_fee_pct", sa.Numeric(5, 2), nullable=True, server_default="0"),
        sa.Column("status", sa.String(20), server_default="draft"),
        sa.Column("cert_title", sa.String(300), nullable=True),
        sa.Column("cert_subtitle", sa.Text(), nullable=True),
        sa.Column("cert_footer", sa.String(500), nullable=True),
        sa.Column("cert_signer_name", sa.String(200), nullable=True),
        sa.Column("cert_signer_designation", sa.String(200), nullable=True),
        sa.Column("cert_logo_url", sa.String(500), nullable=True),
        sa.Column("cert_bg_url", sa.String(500), nullable=True),
        sa.Column("cert_signature_url", sa.String(500), nullable=True),
        sa.Column("cert_color_scheme", sa.String(20), nullable=True),
        sa.Column("cert_style", sa.Text(), nullable=True),
        sa.Column("recording_url", sa.String(500), nullable=True),
        sa.Column("is_recording_public", sa.Boolean(), server_default="false"),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )

    conn.execute(sa.text("""
        INSERT INTO lecture_sessions (id, auditorium_id, speaker_id, title, speaker,
            description, banner_url, start_time, duration_minutes, price, price_vip,
            price_accessible, processing_fee_pct, status, cert_title, cert_subtitle,
            cert_footer, cert_signer_name, cert_signer_designation, cert_logo_url,
            cert_bg_url, cert_signature_url, cert_color_scheme, cert_style,
            recording_url, is_recording_public, created_at)
        SELECT sh.id, sh.auditorium_id, s.speaker_id, s.title, s.speaker_name,
            s.description, s.banner_url, sh.start_time,
            COALESCE(sh.duration_minutes, s.duration_minutes), sh.price, sh.price_vip,
            sh.price_accessible, sh.processing_fee_pct, sh.status, s.cert_title,
            s.cert_subtitle, s.cert_footer, s.cert_signer_name,
            s.cert_signer_designation, s.cert_logo_url, s.cert_bg_url,
            s.cert_signature_url, s.cert_color_scheme, s.cert_style,
            s.recording_url, s.is_recording_public, sh.created_at
        FROM showings sh JOIN sessions s ON sh.session_id = s.id
    """))

    # Recreate event_sessions
    op.create_table(
        "event_sessions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("event_id", sa.Integer(), sa.ForeignKey("events.id", ondelete="CASCADE"), nullable=False),
        sa.Column("session_id", sa.Integer(), sa.ForeignKey("lecture_sessions.id", ondelete="CASCADE"), nullable=False),
        sa.UniqueConstraint("event_id", "session_id", name="uq_event_session"),
    )
    conn.execute(sa.text("""
        INSERT INTO event_sessions (event_id, session_id)
        SELECT event_id, showing_id FROM event_showings
    """))

    # Re-point content-table FKs back to lecture_sessions
    for table in ("agenda_items", "session_speakers", "session_recordings"):
        try:
            op.drop_constraint(f"fk_{table}_session_id", table, type_="foreignkey")
        except Exception:
            pass
        ondelete = "CASCADE" if table != "agenda_items" else None
        op.create_foreign_key(
            f"{table}_session_id_fkey", table, "lecture_sessions",
            ["session_id"], ["id"],
            ondelete=ondelete,
        )

    # Restore bookings.session_id
    op.add_column("bookings", sa.Column("session_id", sa.Integer(), nullable=True))
    conn.execute(sa.text("UPDATE bookings SET session_id = showing_id"))
    op.alter_column("bookings", "session_id", nullable=False)
    op.create_foreign_key(
        "bookings_session_id_fkey", "bookings", "lecture_sessions",
        ["session_id"], ["id"],
    )
    try:
        op.drop_index("uix_active_booking_seat", table_name="bookings")
    except Exception:
        pass
    op.drop_constraint("fk_bookings_showing_id", "bookings", type_="foreignkey")
    op.drop_column("bookings", "showing_id")
    op.execute(sa.text(
        "CREATE UNIQUE INDEX uix_active_booking_seat "
        "ON bookings (session_id, seat_id) "
        "WHERE payment_status IN ('hold', 'paid')"
    ))

    # Restore waitlist columns
    op.add_column("waitlist", sa.Column("session_id", sa.Integer(), nullable=True))
    conn.execute(sa.text("UPDATE waitlist SET session_id = showing_id"))
    op.alter_column("waitlist", "session_id", nullable=False)
    op.create_foreign_key(
        "waitlist_session_id_fkey", "waitlist", "lecture_sessions",
        ["session_id"], ["id"],
    )
    op.add_column("waitlist", sa.Column("priority_session_id", sa.Integer(), nullable=True))
    conn.execute(sa.text("UPDATE waitlist SET priority_session_id = priority_showing_id"))
    op.create_foreign_key(
        "waitlist_priority_session_id_fkey", "waitlist", "lecture_sessions",
        ["priority_session_id"], ["id"],
    )
    op.drop_constraint("fk_waitlist_showing_id", "waitlist", type_="foreignkey")
    op.drop_column("waitlist", "showing_id")
    op.drop_constraint("fk_waitlist_priority_showing_id", "waitlist", type_="foreignkey")
    op.drop_column("waitlist", "priority_showing_id")

    # Drop new tables
    op.drop_table("event_showings")
    op.drop_table("showings")
    op.drop_table("sessions")
