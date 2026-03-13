from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Text, TypeDecorator
from sqlalchemy.orm import relationship

from app.database import Base
from app.utils import now_ist


# ---------------------------------------------------------------------------
# Encrypted column type
# ---------------------------------------------------------------------------

class EncryptedStr(TypeDecorator):
    """
    SQLAlchemy column type that transparently encrypts values on write and
    decrypts them on read using Fernet symmetric encryption.

    The underlying database column is Text (unbounded) because Fernet
    ciphertext is longer than the original plaintext.

    Lookups must NOT use ``User.email == value`` – the stored value is
    ciphertext and the comparison would always fail.  Instead, query the
    companion ``*_hash`` column (an HMAC digest of the normalised plaintext).
    """

    impl = Text
    cache_ok = True

    def process_bind_param(self, value, dialect):
        """Encrypt before writing to the database."""
        if value is None:
            return None
        from app.config import settings
        from app.crypto import encrypt_field
        return encrypt_field(str(value), settings.field_encryption_key)

    def process_result_value(self, value, dialect):
        """Decrypt after reading from the database."""
        if value is None:
            return None
        from app.config import settings
        from app.crypto import decrypt_field
        return decrypt_field(str(value), settings.field_encryption_key)


# ---------------------------------------------------------------------------
# User model
# ---------------------------------------------------------------------------

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)

    # --- Encrypted PII fields ---
    # Stored as Fernet ciphertext.  Read/write through Python as plaintext.
    # Do NOT use these columns in SQLAlchemy filter() comparisons; use the
    # *_hash companion columns instead.
    email = Column(EncryptedStr, nullable=False)
    username = Column(EncryptedStr, nullable=False)
    full_name = Column(EncryptedStr, nullable=True)

    # --- Searchable HMAC hashes ---
    # HMAC-SHA256 of the normalised (lower-cased, stripped) plaintext.
    # Used for exact-match lookups (login, uniqueness checks).
    email_hash = Column(String(64), unique=True, nullable=False, index=True)
    username_hash = Column(String(64), unique=True, nullable=False, index=True)

    # --- Non-sensitive fields (stored as plain text) ---
    password_hash = Column(String(255), nullable=False)
    college = Column(String(300), nullable=True)
    discipline = Column(String(100), nullable=True)
    domain = Column(String(100), nullable=True)
    year_of_study = Column(Integer, nullable=True)
    is_admin = Column(Boolean, default=False)
    is_supervisor = Column(Boolean, default=False)
    supervisor_college_id = Column(Integer, ForeignKey("colleges.id"), nullable=True)
    created_at = Column(DateTime, default=now_ist)

    bookings = relationship("Booking", back_populates="user")
    waitlist_entries = relationship("Waitlist", back_populates="user")
    supervised_college = relationship("College", foreign_keys=[supervisor_college_id])
