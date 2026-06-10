"""Load local users from config for JWT authentication."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ly_next.core.config import config
from ly_next.core.password_hash import hash_password, verify_password


@dataclass(frozen=True, slots=True)
class LocalUser:
    username: str
    password_hash: str
    role: str


def _user_rows() -> list[dict[str, Any]]:
    rows = config.get("auth.users") or []
    return [r for r in rows if isinstance(r, dict)]


def users_configured() -> bool:
    return bool(_user_rows())


def users_with_plaintext_password() -> list[str]:
    names: list[str] = []
    for row in _user_rows():
        username = str(row.get("username") or "").strip()
        if not username:
            continue
        if str(row.get("password_hash") or "").strip():
            continue
        if str(row.get("password") or "").strip():
            names.append(username)
    return names


def load_local_users() -> list[LocalUser]:
    out: list[LocalUser] = []
    for row in _user_rows():
        username = str(row.get("username") or "").strip()
        if not username:
            continue
        role = str(row.get("role") or "operator").strip().lower()
        stored = str(row.get("password_hash") or "").strip()
        if not stored:
            plain = str(row.get("password") or "").strip()
            if plain:
                stored = hash_password(plain)
        if not stored:
            continue
        out.append(LocalUser(username=username, password_hash=stored, role=role))
    return out


def authenticate_local_user(username: str, password: str) -> LocalUser | None:
    name = str(username or "").strip()
    if not name:
        return None
    for user in load_local_users():
        if user.username != name:
            continue
        if verify_password(password, user.password_hash):
            return user
        return None
    return None
