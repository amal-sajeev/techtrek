"""Add ticket_number column to bookings for human-friendly short IDs.

Revision ID: 0037
Revises: 0036
"""
import random
import string

from alembic import op
import sqlalchemy as sa

revision = "0037"
down_revision = "0036"

_CHARSET = string.ascii_uppercase + string.digits


def _random_ticket_number():
    code = "".join(random.choices(_CHARSET, k=6))
    return f"TT-{code}"


def upgrade():
    op.add_column(
        "bookings",
        sa.Column("ticket_number", sa.String(10), nullable=True),
    )

    conn = op.get_bind()
    rows = conn.execute(
        sa.text("SELECT id FROM bookings WHERE payment_status = 'paid' AND ticket_id IS NOT NULL")
    ).fetchall()

    used = set()
    for (row_id,) in rows:
        tn = _random_ticket_number()
        while tn in used:
            tn = _random_ticket_number()
        used.add(tn)
        conn.execute(
            sa.text("UPDATE bookings SET ticket_number = :tn WHERE id = :id"),
            {"tn": tn, "id": row_id},
        )

    op.create_unique_constraint("uq_bookings_ticket_number", "bookings", ["ticket_number"])
    op.create_index("ix_bookings_ticket_number", "bookings", ["ticket_number"])


def downgrade():
    op.drop_index("ix_bookings_ticket_number", table_name="bookings")
    op.drop_constraint("uq_bookings_ticket_number", "bookings", type_="unique")
    op.drop_column("bookings", "ticket_number")
