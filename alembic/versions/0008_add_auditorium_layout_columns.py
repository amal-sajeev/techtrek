"""Add stage/layout columns to auditoriums table.

The Auditorium model gained stage_cols, stage_offset, stage_label,
row_gaps, col_gaps, layout_config, and entry_exit_config but no
migration was created, causing ProgrammingError on any auditorium query.

Revision ID: 0008
Revises: 0007
Create Date: 2026-03-14
"""

from alembic import op
import sqlalchemy as sa

revision = "0008"
down_revision = "0007"
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


def upgrade() -> None:
    if not _col_exists("auditoriums", "stage_cols"):
        op.add_column("auditoriums", sa.Column("stage_cols", sa.Integer(), nullable=True))

    if not _col_exists("auditoriums", "stage_offset"):
        op.add_column(
            "auditoriums",
            sa.Column("stage_offset", sa.Integer(), server_default="0"),
        )

    if not _col_exists("auditoriums", "stage_label"):
        op.add_column(
            "auditoriums",
            sa.Column("stage_label", sa.String(100), server_default="Stage"),
        )

    if not _col_exists("auditoriums", "row_gaps"):
        op.add_column("auditoriums", sa.Column("row_gaps", sa.Text(), nullable=True))

    if not _col_exists("auditoriums", "col_gaps"):
        op.add_column("auditoriums", sa.Column("col_gaps", sa.Text(), nullable=True))

    if not _col_exists("auditoriums", "layout_config"):
        op.add_column("auditoriums", sa.Column("layout_config", sa.JSON(), nullable=True))

    if not _col_exists("auditoriums", "entry_exit_config"):
        op.add_column("auditoriums", sa.Column("entry_exit_config", sa.JSON(), nullable=True))


def downgrade() -> None:
    for col in (
        "entry_exit_config",
        "layout_config",
        "col_gaps",
        "row_gaps",
        "stage_label",
        "stage_offset",
        "stage_cols",
    ):
        if _col_exists("auditoriums", col):
            op.drop_column("auditoriums", col)
