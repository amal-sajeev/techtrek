"""Move certificate columns from sessions to events.

Copies cert data from the first session of each event into the event
row, then drops the cert columns from sessions.

Revision ID: 0013
Revises: 0012
Create Date: 2026-03-16
"""

from alembic import op
import sqlalchemy as sa

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None

CERT_COLS = [
    ("cert_title", sa.String(300)),
    ("cert_subtitle", sa.Text),
    ("cert_footer", sa.String(500)),
    ("cert_signer_name", sa.String(200)),
    ("cert_signer_designation", sa.String(200)),
    ("cert_logo_url", sa.String(500)),
    ("cert_bg_url", sa.String(500)),
    ("cert_signature_url", sa.String(500)),
    ("cert_color_scheme", sa.String(20)),
    ("cert_style", sa.Text),
]


def upgrade() -> None:
    for col_name, col_type in CERT_COLS:
        op.add_column("events", sa.Column(col_name, col_type, nullable=True))

    conn = op.get_bind()

    events = conn.execute(sa.text("SELECT id FROM events")).fetchall()
    for (event_id,) in events:
        row = conn.execute(
            sa.text(
                "SELECT cert_title, cert_subtitle, cert_footer, "
                "cert_signer_name, cert_signer_designation, cert_logo_url, "
                "cert_bg_url, cert_signature_url, cert_color_scheme, cert_style "
                "FROM sessions WHERE event_id = :eid "
                "ORDER BY \"order\", start_time LIMIT 1"
            ),
            {"eid": event_id},
        ).fetchone()
        if row and any(v is not None for v in row):
            conn.execute(
                sa.text(
                    "UPDATE events SET "
                    "cert_title = :t, cert_subtitle = :sub, cert_footer = :f, "
                    "cert_signer_name = :sn, cert_signer_designation = :sd, "
                    "cert_logo_url = :lo, cert_bg_url = :bg, "
                    "cert_signature_url = :sig, cert_color_scheme = :cs, "
                    "cert_style = :sty "
                    "WHERE id = :eid"
                ),
                {
                    "t": row[0], "sub": row[1], "f": row[2],
                    "sn": row[3], "sd": row[4], "lo": row[5],
                    "bg": row[6], "sig": row[7], "cs": row[8],
                    "sty": row[9], "eid": event_id,
                },
            )

    for col_name, _ in CERT_COLS:
        op.drop_column("sessions", col_name)


def downgrade() -> None:
    for col_name, col_type in CERT_COLS:
        op.add_column("sessions", sa.Column(col_name, col_type, nullable=True))

    for col_name, _ in CERT_COLS:
        op.drop_column("events", col_name)
