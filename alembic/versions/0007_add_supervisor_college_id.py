"""Add supervisor_college_id FK to users table.

Revision ID: 0007
Revises: 0006
Create Date: 2026-03-13
"""

from alembic import op
import sqlalchemy as sa

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def _column_exists(table: str, column: str) -> bool:
    conn = op.get_bind()
    result = conn.execute(
        sa.text(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_name = :t AND column_name = :c"
        ),
        {"t": table, "c": column},
    )
    return result.scalar() is not None


def upgrade() -> None:
    if not _column_exists("users", "supervisor_college_id"):
        op.add_column(
            "users",
            sa.Column("supervisor_college_id", sa.Integer(), nullable=True),
        )
        op.create_foreign_key(
            "fk_users_supervisor_college_id",
            "users",
            "colleges",
            ["supervisor_college_id"],
            ["id"],
        )


def downgrade() -> None:
    if _column_exists("users", "supervisor_college_id"):
        op.drop_constraint("fk_users_supervisor_college_id", "users", type_="foreignkey")
        op.drop_column("users", "supervisor_college_id")
