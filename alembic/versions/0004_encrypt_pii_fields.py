"""Encrypt PII fields (email, username, full_name) and add hash lookup columns.

This migration:
1. Widens email / username / full_name to TEXT (Fernet ciphertext is longer
   than the original VARCHAR limits).
2. Drops the old plaintext unique constraints / indexes on email and username
   (encrypted values are non-comparable; uniqueness is enforced via the new
   *_hash columns instead).
3. Adds email_hash and username_hash columns (VARCHAR 64, HMAC-SHA256 digests).
4. Re-encrypts every existing row in-place and populates the hash columns.
5. Applies NOT NULL + UNIQUE constraints to the hash columns.

Revision ID: 0004
Revises: 0003
Create Date: 2026-03-13
"""

from alembic import op
import sqlalchemy as sa

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


# ---------------------------------------------------------------------------
# Helpers (avoid circular imports – inline everything needed at migration time)
# ---------------------------------------------------------------------------

def _get_settings():
    from app.config import settings
    return settings


def _encrypt(value: str, key: str) -> str:
    from app.crypto import encrypt_field
    return encrypt_field(value, key)


def _hash(value: str, key: str) -> str:
    from app.crypto import hash_lookup
    return hash_lookup(value, key)


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


def _index_exists(index_name: str) -> bool:
    conn = op.get_bind()
    result = conn.execute(
        sa.text(
            "SELECT 1 FROM pg_indexes WHERE indexname = :n"
        ),
        {"n": index_name},
    )
    return result.scalar() is not None


def _constraint_exists(constraint_name: str) -> bool:
    conn = op.get_bind()
    result = conn.execute(
        sa.text(
            "SELECT 1 FROM information_schema.table_constraints "
            "WHERE constraint_name = :n"
        ),
        {"n": constraint_name},
    )
    return result.scalar() is not None


# ---------------------------------------------------------------------------
# Upgrade
# ---------------------------------------------------------------------------

def upgrade() -> None:
    cfg = _get_settings()
    key = cfg.field_encryption_key

    conn = op.get_bind()

    # ── 1. Widen columns to TEXT so they can hold Fernet ciphertext ──────────
    op.alter_column("users", "email",
                    existing_type=sa.String(255),
                    type_=sa.Text(),
                    existing_nullable=False)
    op.alter_column("users", "username",
                    existing_type=sa.String(100),
                    type_=sa.Text(),
                    existing_nullable=False)
    op.alter_column("users", "full_name",
                    existing_type=sa.String(200),
                    type_=sa.Text(),
                    existing_nullable=True)

    # ── 2. Drop old plaintext unique constraints / indexes ───────────────────
    # Encrypted values are random-nonce, so the old constraints are meaningless.
    for idx in ("ix_users_email", "ix_users_username"):
        if _index_exists(idx):
            op.drop_index(idx, table_name="users")

    for uq in ("uq_users_email", "uq_users_username",
               "users_email_key", "users_username_key"):
        if _constraint_exists(uq):
            op.drop_constraint(uq, "users", type_="unique")

    # ── 3. Add hash columns (nullable at first so existing rows don't break) ──
    if not _col_exists("users", "email_hash"):
        op.add_column("users", sa.Column("email_hash", sa.String(64), nullable=True))
    if not _col_exists("users", "username_hash"):
        op.add_column("users", sa.Column("username_hash", sa.String(64), nullable=True))

    # ── 4. Migrate existing rows ─────────────────────────────────────────────
    rows = conn.execute(
        sa.text("SELECT id, email, username, full_name FROM users")
    ).fetchall()

    for row in rows:
        user_id, email, username, full_name = row

        email_enc    = _encrypt(email,    key) if email    else None
        username_enc = _encrypt(username, key) if username else None
        fullname_enc = _encrypt(full_name, key) if full_name else None

        email_hash    = _hash(email,    key) if email    else None
        username_hash = _hash(username, key) if username else None

        conn.execute(
            sa.text(
                "UPDATE users "
                "SET email = :e, username = :u, full_name = :fn, "
                "    email_hash = :eh, username_hash = :uh "
                "WHERE id = :id"
            ),
            {
                "e":  email_enc,
                "u":  username_enc,
                "fn": fullname_enc,
                "eh": email_hash,
                "uh": username_hash,
                "id": user_id,
            },
        )

    # ── 5. Enforce NOT NULL + UNIQUE on hash columns ─────────────────────────
    op.alter_column("users", "email_hash",    nullable=False)
    op.alter_column("users", "username_hash", nullable=False)

    if not _index_exists("ix_users_email_hash"):
        op.create_index("ix_users_email_hash",    "users", ["email_hash"],    unique=True)
    if not _index_exists("ix_users_username_hash"):
        op.create_index("ix_users_username_hash", "users", ["username_hash"], unique=True)


# ---------------------------------------------------------------------------
# Downgrade  (decrypt back to plaintext and restore original schema)
# ---------------------------------------------------------------------------

def downgrade() -> None:
    cfg = _get_settings()
    key = cfg.field_encryption_key

    conn = op.get_bind()
    from app.crypto import decrypt_field

    rows = conn.execute(
        sa.text("SELECT id, email, username, full_name FROM users")
    ).fetchall()

    for row in rows:
        user_id, email_enc, username_enc, fullname_enc = row
        conn.execute(
            sa.text(
                "UPDATE users "
                "SET email = :e, username = :u, full_name = :fn "
                "WHERE id = :id"
            ),
            {
                "e":  decrypt_field(email_enc,    key) if email_enc    else None,
                "u":  decrypt_field(username_enc, key) if username_enc else None,
                "fn": decrypt_field(fullname_enc, key) if fullname_enc else None,
                "id": user_id,
            },
        )

    # Remove hash columns
    op.drop_index("ix_users_email_hash",    table_name="users")
    op.drop_index("ix_users_username_hash", table_name="users")
    op.drop_column("users", "email_hash")
    op.drop_column("users", "username_hash")

    # Restore original column sizes and unique constraints
    op.alter_column("users", "email",
                    existing_type=sa.Text(),
                    type_=sa.String(255),
                    existing_nullable=False)
    op.alter_column("users", "username",
                    existing_type=sa.Text(),
                    type_=sa.String(100),
                    existing_nullable=False)
    op.alter_column("users", "full_name",
                    existing_type=sa.Text(),
                    type_=sa.String(200),
                    existing_nullable=True)

    op.create_index("ix_users_email",    "users", ["email"],    unique=True)
    op.create_index("ix_users_username", "users", ["username"], unique=True)
