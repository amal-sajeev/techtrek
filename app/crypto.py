"""
Cryptographic helpers for PII field encryption and searchable hashing.

- encrypt_field / decrypt_field  : Fernet symmetric encryption (reversible).
  Used for email, username, full_name stored in the database.

- hash_lookup : HMAC-SHA256 of the normalised value using the Fernet key
  material as the HMAC key.  Used to produce short, fixed-length tokens that
  allow exact-match DB lookups without storing plaintext or requiring
  decryption of every row.

All functions take the raw FIELD_ENCRYPTION_KEY string (a URL-safe base64
Fernet key) as an explicit parameter so they remain fully testable and free of
module-level side-effects.
"""

from __future__ import annotations

import base64
import hashlib
import hmac as _hmac_module

from cryptography.fernet import Fernet, InvalidToken


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _fernet(key: str) -> Fernet:
    """Return a Fernet instance for *key* (URL-safe base64 string, 44 chars)."""
    return Fernet(key.encode() if isinstance(key, str) else key)


def _hmac_key(fernet_key: str) -> bytes:
    """Derive a 32-byte HMAC key from the Fernet key material."""
    # A Fernet key is 32 bytes encoded as URL-safe base64.
    # urlsafe_b64decode handles the standard 44-char Fernet key directly.
    return base64.urlsafe_b64decode(fernet_key)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def encrypt_field(value: str, key: str) -> str:
    """
    Encrypt *value* with Fernet and return the ciphertext as an ASCII string.
    Returns an empty string for empty/None input (no-op).
    """
    if not value:
        return value
    return _fernet(key).encrypt(value.encode("utf-8")).decode("ascii")


def decrypt_field(value: str, key: str) -> str:
    """
    Decrypt a Fernet-encrypted *value* and return the plaintext.

    Falls back to returning *value* unchanged if decryption fails so that
    legacy plaintext rows (before the migration) are still readable during a
    rolling upgrade.
    """
    if not value:
        return value
    try:
        return _fernet(key).decrypt(value.encode("ascii")).decode("utf-8")
    except (InvalidToken, Exception):
        # Value is not valid Fernet ciphertext – assume it is still plaintext
        # (e.g., a row not yet migrated).  Return as-is.
        return value


def hash_lookup(value: str, key: str) -> str:
    """
    Return a hex HMAC-SHA256 digest of the *normalised* (lower-cased, stripped)
    value.  Used as a deterministic search key for encrypted fields so that
    exact-match queries can be executed without decrypting every row.
    """
    raw_key = _hmac_key(key)
    normalised = value.lower().strip().encode("utf-8")
    return _hmac_module.new(raw_key, normalised, hashlib.sha256).hexdigest()
