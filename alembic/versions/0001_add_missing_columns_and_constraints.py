"""Add missing columns from startup DDL and seat-hold uniqueness constraint

Revision ID: 0001
Revises:
Create Date: 2026-03-13
"""
from alembic import op
import sqlalchemy as sa


revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def _col_exists(table: str, col: str) -> bool:
    """Return True if the column already exists (idempotent check)."""
    conn = op.get_bind()
    result = conn.execute(
        sa.text(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_name=:t AND column_name=:c"
        ),
        {"t": table, "c": col},
    )
    return result.fetchone() is not None


def _index_exists(name: str) -> bool:
    conn = op.get_bind()
    result = conn.execute(
        sa.text("SELECT 1 FROM pg_indexes WHERE indexname = :n"),
        {"n": name},
    )
    return result.fetchone() is not None


def upgrade() -> None:
    # lecture_sessions — pricing columns
    if not _col_exists("lecture_sessions", "price_vip"):
        op.add_column("lecture_sessions", sa.Column("price_vip", sa.Numeric(10, 2), nullable=True))
    if not _col_exists("lecture_sessions", "price_accessible"):
        op.add_column("lecture_sessions", sa.Column("price_accessible", sa.Numeric(10, 2), nullable=True))

    # bookings — group and Razorpay columns (widened for UUID)
    if not _col_exists("bookings", "booking_group"):
        op.add_column("bookings", sa.Column("booking_group", sa.String(36), nullable=True, index=True))
    if not _col_exists("bookings", "group_qr_data"):
        op.add_column("bookings", sa.Column("group_qr_data", sa.Text, nullable=True))
    if not _col_exists("bookings", "razorpay_order_id"):
        op.add_column("bookings", sa.Column("razorpay_order_id", sa.String(50), nullable=True))
    if not _col_exists("bookings", "razorpay_payment_id"):
        op.add_column("bookings", sa.Column("razorpay_payment_id", sa.String(50), nullable=True))
    if not _col_exists("bookings", "razorpay_signature"):
        op.add_column("bookings", sa.Column("razorpay_signature", sa.String(128), nullable=True))
    if not _col_exists("bookings", "refund_id"):
        op.add_column("bookings", sa.Column("refund_id", sa.String(50), nullable=True))
    if not _col_exists("bookings", "refund_status"):
        op.add_column("bookings", sa.Column("refund_status", sa.String(30), nullable=True))
    if not _col_exists("bookings", "refund_processed_at"):
        op.add_column("bookings", sa.Column("refund_processed_at", sa.DateTime, nullable=True))

    # Widen ticket_id and booking_group to accommodate UUIDs
    op.execute(
        sa.text(
            "ALTER TABLE bookings ALTER COLUMN ticket_id TYPE VARCHAR(36)"
        )
    )
    op.execute(
        sa.text(
            "ALTER TABLE bookings ALTER COLUMN booking_group TYPE VARCHAR(36)"
        )
    )

    # users — supervisor flag
    if not _col_exists("users", "is_supervisor"):
        op.add_column("users", sa.Column("is_supervisor", sa.Boolean, nullable=False,
                                         server_default=sa.false()))

    # speakers — user link and invite token
    if not _col_exists("speakers", "user_id"):
        op.add_column("speakers", sa.Column("user_id", sa.Integer,
                                             sa.ForeignKey("users.id"), nullable=True, unique=True))
    if not _col_exists("speakers", "invite_token"):
        op.add_column("speakers", sa.Column("invite_token", sa.String(64), nullable=True, unique=True))
    if not _col_exists("speakers", "invite_token_expires"):
        op.add_column("speakers", sa.Column("invite_token_expires", sa.DateTime, nullable=True))

    # lecture_sessions — certificate fields
    for col, col_type in [
        ("cert_title", sa.String(300)),
        ("cert_subtitle", sa.Text),
        ("cert_footer", sa.String(500)),
        ("cert_signer_name", sa.String(200)),
        ("cert_signer_designation", sa.String(200)),
        ("cert_logo_url", sa.String(500)),
        ("cert_bg_url", sa.String(500)),
        ("cert_color_scheme", sa.String(20)),
        ("cert_style", sa.Text),
        ("cert_signature_url", sa.String(500)),
        ("recording_url", sa.String(500)),
        ("processing_fee_pct", sa.Numeric(5, 2)),
    ]:
        if not _col_exists("lecture_sessions", col):
            op.add_column("lecture_sessions", sa.Column(col, col_type, nullable=True))

    if not _col_exists("lecture_sessions", "is_recording_public"):
        op.add_column("lecture_sessions", sa.Column("is_recording_public", sa.Boolean,
                                                      nullable=False, server_default=sa.false()))

    # agenda_items — speaker_id
    if not _col_exists("agenda_items", "speaker_id"):
        op.add_column("agenda_items", sa.Column("speaker_id", sa.Integer,
                                                  sa.ForeignKey("speakers.id"), nullable=True))

    # seat_types — price
    if not _col_exists("seat_types", "price"):
        op.add_column("seat_types", sa.Column("price", sa.Numeric(10, 2), nullable=True))

    # Drop deprecated column if it still exists
    if _col_exists("lecture_sessions", "recording_file"):
        op.drop_column("lecture_sessions", "recording_file")

    # Partial unique index to prevent double-booking (race condition fix)
    if not _index_exists("uix_active_booking_seat"):
        op.execute(sa.text(
            "CREATE UNIQUE INDEX uix_active_booking_seat "
            "ON bookings (session_id, seat_id) "
            "WHERE payment_status IN ('hold', 'paid')"
        ))


def downgrade() -> None:
    if _index_exists("uix_active_booking_seat"):
        op.execute(sa.text("DROP INDEX IF EXISTS uix_active_booking_seat"))
