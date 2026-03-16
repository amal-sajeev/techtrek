"""Add newsletters table and unsubscribe_token to newsletter_subscribers.

Revision ID: 0011
Revises: 0010
Create Date: 2026-03-16
"""

from alembic import op
import sqlalchemy as sa

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if "newsletters" not in insp.get_table_names():
        op.create_table(
            "newsletters",
            sa.Column("id", sa.Integer(), primary_key=True, index=True),
            sa.Column("subject", sa.String(500), nullable=False),
            sa.Column("body_html", sa.Text(), nullable=False, server_default=""),
            sa.Column("status", sa.String(20), nullable=False, server_default="draft"),
            sa.Column("total_recipients", sa.Integer(), server_default="0"),
            sa.Column("sent_count", sa.Integer(), server_default="0"),
            sa.Column("failed_count", sa.Integer(), server_default="0"),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("sent_at", sa.DateTime(), nullable=True),
        )

    existing = [c["name"] for c in insp.get_columns("newsletter_subscribers")]
    if "unsubscribe_token" not in existing:
        with op.batch_alter_table("newsletter_subscribers") as batch_op:
            batch_op.add_column(
                sa.Column("unsubscribe_token", sa.String(64), unique=True, nullable=True)
            )


def downgrade() -> None:
    with op.batch_alter_table("newsletter_subscribers") as batch_op:
        batch_op.drop_column("unsubscribe_token")

    op.drop_table("newsletters")
