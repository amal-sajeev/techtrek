"""Add certificate_templates table and cert_template_id FK on events.

Revision ID: 0035
Revises: 0034
"""
from alembic import op
import sqlalchemy as sa

revision = "0035"
down_revision = "0034"


def upgrade():
    op.create_table(
        "certificate_templates",
        sa.Column("id", sa.Integer, primary_key=True, index=True),
        sa.Column("name", sa.String(300), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("created_by", sa.Integer, sa.ForeignKey("users.id"), nullable=True),
        sa.Column("cert_title", sa.String(300), nullable=True),
        sa.Column("cert_subtitle", sa.Text, nullable=True),
        sa.Column("cert_footer", sa.String(500), nullable=True),
        sa.Column("cert_signer_name", sa.String(200), nullable=True),
        sa.Column("cert_signer_designation", sa.String(200), nullable=True),
        sa.Column("cert_logo_url", sa.String(500), nullable=True),
        sa.Column("cert_bg_url", sa.String(500), nullable=True),
        sa.Column("cert_signature_url", sa.String(500), nullable=True),
        sa.Column("cert_color_scheme", sa.String(20), nullable=True),
        sa.Column("cert_style", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=True),
        sa.Column("updated_at", sa.DateTime, nullable=True),
    )

    op.add_column(
        "events",
        sa.Column("cert_template_id", sa.Integer, sa.ForeignKey("certificate_templates.id"), nullable=True),
    )


def downgrade():
    op.drop_column("events", "cert_template_id")
    op.drop_table("certificate_templates")
