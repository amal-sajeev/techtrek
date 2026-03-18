"""Add page column to template_questions for multipage feedback forms.

Revision ID: 0022
Revises: 0021
"""
from alembic import op
import sqlalchemy as sa

revision = "0022"
down_revision = "0021"


def upgrade():
    op.add_column(
        "template_questions",
        sa.Column("page", sa.Integer, nullable=False, server_default="1"),
    )


def downgrade():
    op.drop_column("template_questions", "page")
