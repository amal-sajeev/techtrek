"""Event-centric refactoring.

Move pricing/venue/dates from Showing to Event. Sessions become
agenda items within events. Introduce coupons. Deprecate Showing
and EventShowing tables. Waitlist and Feedback now reference events.

Revision ID: 0009
Revises: 0008
Create Date: 2026-03-15
"""

from alembic import op
import sqlalchemy as sa

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


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


def _table_exists(table: str) -> bool:
    conn = op.get_bind()
    result = conn.execute(
        sa.text(
            "SELECT 1 FROM information_schema.tables "
            "WHERE table_name = :t"
        ),
        {"t": table},
    )
    return result.scalar() is not None


def upgrade() -> None:
    # -- 1. Events: add venue, dates, pricing --
    if not _col_exists("events", "auditorium_id"):
        op.add_column("events", sa.Column("auditorium_id", sa.Integer(), nullable=True))
        op.create_foreign_key("fk_events_auditorium", "events", "auditoriums", ["auditorium_id"], ["id"])

    if not _col_exists("events", "start_date"):
        op.add_column("events", sa.Column("start_date", sa.Date(), nullable=True))

    if not _col_exists("events", "end_date"):
        op.add_column("events", sa.Column("end_date", sa.Date(), nullable=True))

    if not _col_exists("events", "price"):
        op.add_column("events", sa.Column("price", sa.Numeric(10, 2), server_default="0", nullable=False))

    if not _col_exists("events", "price_vip"):
        op.add_column("events", sa.Column("price_vip", sa.Numeric(10, 2), nullable=True))

    if not _col_exists("events", "price_accessible"):
        op.add_column("events", sa.Column("price_accessible", sa.Numeric(10, 2), nullable=True))

    if not _col_exists("events", "processing_fee_pct"):
        op.add_column("events", sa.Column("processing_fee_pct", sa.Numeric(5, 2), server_default="0", nullable=True))

    if _col_exists("events", "discount_pct"):
        op.drop_column("events", "discount_pct")

    # -- 2. Sessions: add event_id, start_time, order --
    if not _col_exists("sessions", "event_id"):
        op.add_column("sessions", sa.Column("event_id", sa.Integer(), nullable=True))
        op.create_foreign_key("fk_sessions_event", "sessions", "events", ["event_id"], ["id"], ondelete="CASCADE")

    if not _col_exists("sessions", "start_time"):
        op.add_column("sessions", sa.Column("start_time", sa.DateTime(), nullable=True))

    if not _col_exists("sessions", "order"):
        op.add_column("sessions", sa.Column("order", sa.Integer(), server_default="0"))

    # -- 3. Create coupons table --
    if not _table_exists("coupons"):
        op.create_table(
            "coupons",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("code", sa.String(50), unique=True, nullable=False),
            sa.Column("discount_pct", sa.Numeric(5, 2), nullable=True),
            sa.Column("discount_amount", sa.Numeric(10, 2), nullable=True),
            sa.Column("event_id", sa.Integer(), sa.ForeignKey("events.id", ondelete="CASCADE"), nullable=True),
            sa.Column("max_uses", sa.Integer(), nullable=True),
            sa.Column("used_count", sa.Integer(), server_default="0"),
            sa.Column("valid_from", sa.DateTime(), nullable=True),
            sa.Column("valid_until", sa.DateTime(), nullable=True),
            sa.Column("is_active", sa.Boolean(), server_default="true"),
            sa.Column("created_at", sa.DateTime(), nullable=True),
        )

    # -- 4. Bookings: showing_id nullable, coupon_id --
    if _col_exists("bookings", "showing_id"):
        op.alter_column("bookings", "showing_id", existing_type=sa.Integer(), nullable=True)

    if not _col_exists("bookings", "coupon_id"):
        op.add_column("bookings", sa.Column("coupon_id", sa.Integer(), nullable=True))
        op.create_foreign_key("fk_bookings_coupon", "bookings", "coupons", ["coupon_id"], ["id"], ondelete="SET NULL")

    # -- 5. Waitlist: add event_id, make showing_id nullable --
    if not _col_exists("waitlist", "event_id"):
        op.add_column("waitlist", sa.Column("event_id", sa.Integer(), nullable=True))
        op.create_foreign_key("fk_waitlist_event", "waitlist", "events", ["event_id"], ["id"])

    if _col_exists("waitlist", "showing_id"):
        op.alter_column("waitlist", "showing_id", existing_type=sa.Integer(), nullable=True)

    if _col_exists("waitlist", "priority_showing_id"):
        op.alter_column("waitlist", "priority_showing_id", existing_type=sa.Integer(), nullable=True)

    # -- 6. Feedback: add event_id, make showing_id nullable --
    if not _col_exists("feedback", "event_id"):
        op.add_column("feedback", sa.Column("event_id", sa.Integer(), nullable=True))
        op.create_foreign_key("fk_feedback_event", "feedback", "events", ["event_id"], ["id"])

    if _col_exists("feedback", "showing_id"):
        op.alter_column("feedback", "showing_id", existing_type=sa.Integer(), nullable=True)

    # -- 7. Drop event_showings table --
    if _table_exists("event_showings"):
        op.drop_table("event_showings")


def downgrade() -> None:
    if not _table_exists("event_showings"):
        op.create_table(
            "event_showings",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("event_id", sa.Integer(), sa.ForeignKey("events.id", ondelete="CASCADE"), nullable=False),
            sa.Column("showing_id", sa.Integer(), sa.ForeignKey("showings.id", ondelete="CASCADE"), nullable=False),
            sa.UniqueConstraint("event_id", "showing_id", name="uq_event_showing"),
        )

    if _col_exists("feedback", "event_id"):
        op.drop_column("feedback", "event_id")

    if _col_exists("waitlist", "event_id"):
        op.drop_column("waitlist", "event_id")

    if _col_exists("bookings", "coupon_id"):
        op.drop_column("bookings", "coupon_id")

    if _table_exists("coupons"):
        op.drop_table("coupons")

    for col in ("order", "start_time", "event_id"):
        if _col_exists("sessions", col):
            op.drop_column("sessions", col)

    if not _col_exists("events", "discount_pct"):
        op.add_column("events", sa.Column("discount_pct", sa.Numeric(5, 2), nullable=True))

    for col in ("processing_fee_pct", "price_accessible", "price_vip", "price", "end_date", "start_date", "auditorium_id"):
        if _col_exists("events", col):
            op.drop_column("events", col)
