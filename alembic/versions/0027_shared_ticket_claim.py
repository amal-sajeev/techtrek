"""Add share_token, claimed_by, claimed_at to ticket_shares and
is_shared_ticket, original_user_id to bookings for the shared ticket claim flow."""

from alembic import op
import sqlalchemy as sa

revision = "0027"
down_revision = "0026"


def upgrade():
    op.add_column("ticket_shares", sa.Column("share_token", sa.String(64), nullable=True, unique=True, index=True))
    op.add_column("ticket_shares", sa.Column("claimed_by", sa.Integer, sa.ForeignKey("users.id"), nullable=True))
    op.add_column("ticket_shares", sa.Column("claimed_at", sa.DateTime, nullable=True))

    # Backfill existing rows with a token so the NOT NULL constraint can be applied
    from secrets import token_urlsafe
    conn = op.get_bind()
    rows = conn.execute(sa.text("SELECT id FROM ticket_shares WHERE share_token IS NULL")).fetchall()
    for row in rows:
        conn.execute(
            sa.text("UPDATE ticket_shares SET share_token = :tok WHERE id = :id"),
            {"tok": token_urlsafe(32), "id": row[0]},
        )
    op.alter_column("ticket_shares", "share_token", nullable=False)

    op.add_column("bookings", sa.Column("is_shared_ticket", sa.Boolean, server_default=sa.text("false"), nullable=False))
    op.add_column("bookings", sa.Column("original_user_id", sa.Integer, nullable=True))


def downgrade():
    op.drop_column("bookings", "original_user_id")
    op.drop_column("bookings", "is_shared_ticket")
    op.drop_column("ticket_shares", "claimed_at")
    op.drop_column("ticket_shares", "claimed_by")
    op.drop_column("ticket_shares", "share_token")
