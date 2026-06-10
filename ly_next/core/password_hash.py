"""Password hashing (stdlib PBKDF2, no extra deps)."""

from __future__ import annotations

import hashlib
import hmac
import secrets

_PREFIX = "pbkdf2_sha256"
_ITERATIONS = 260_000


def hash_password(password: str, *, salt: bytes | None = None) -> str:
    raw = str(password or "")
    if not raw:
        raise ValueError("password must not be empty")
    salt_bytes = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", raw.encode("utf-8"), salt_bytes, _ITERATIONS)
    return f"{_PREFIX}${salt_bytes.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    raw = str(password or "")
    text = str(stored or "").strip()
    if not raw or not text:
        return False
    parts = text.split("$")
    if len(parts) != 3 or parts[0] != _PREFIX:
        return False
    try:
        salt = bytes.fromhex(parts[1])
        expected = bytes.fromhex(parts[2])
    except ValueError:
        return False
    actual = hashlib.pbkdf2_hmac("sha256", raw.encode("utf-8"), salt, _ITERATIONS)
    return hmac.compare_digest(actual, expected)
