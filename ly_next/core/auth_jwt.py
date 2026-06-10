"""JWT access token issue and verification."""

from __future__ import annotations

import secrets
import time
from typing import Any

import jwt

from ly_next.core.config import config


def jwt_config() -> dict[str, Any]:
    auth = config.get("auth") or {}
    block = auth.get("jwt") if isinstance(auth, dict) else {}
    return block if isinstance(block, dict) else {}


def jwt_secret_configured() -> bool:
    raw = str(jwt_config().get("secret") or config.get("auth.jwt_secret") or "").strip()
    return bool(raw)


def jwt_enabled() -> bool:
    from ly_next.core.auth_users import users_configured

    if not users_configured():
        return False
    jc = jwt_config()
    if jc.get("enabled") is False:
        return False
    mode = str(config.get("auth.mode") or "api_key").strip().lower()
    if mode in ("jwt", "hybrid"):
        return True
    return bool(jc.get("enabled"))


def _secret() -> str:
    raw = str(jwt_config().get("secret") or config.get("auth.jwt_secret") or "").strip()
    if raw:
        return raw
    generated = secrets.token_urlsafe(48)
    config.set("auth.jwt.secret", generated, save=True)
    return generated


def _algorithm() -> str:
    algo = str(jwt_config().get("algorithm") or "HS256").strip().upper()
    return algo if algo in ("HS256", "HS384", "HS512") else "HS256"


def access_ttl_seconds() -> int:
    minutes = int(jwt_config().get("access_ttl_minutes") or 60)
    return max(5, min(minutes, 24 * 60)) * 60


def issue_access_token(*, username: str, role: str) -> tuple[str, int]:
    now = int(time.time())
    ttl = access_ttl_seconds()
    payload = {
        "sub": username,
        "role": role,
        "typ": "access",
        "iat": now,
        "exp": now + ttl,
        "iss": str(jwt_config().get("issuer") or "ly-next"),
    }
    token = jwt.encode(payload, _secret(), algorithm=_algorithm())
    if isinstance(token, bytes):
        token = token.decode("utf-8")
    return token, ttl


def verify_access_token(token: str) -> dict[str, Any] | None:
    raw = str(token or "").strip()
    if not raw:
        return None
    try:
        payload = jwt.decode(
            raw,
            _secret(),
            algorithms=[_algorithm()],
            options={"require": ["exp", "sub", "typ"]},
        )
    except jwt.PyJWTError:
        return None
    if str(payload.get("typ") or "") != "access":
        return None
    sub = str(payload.get("sub") or "").strip()
    if not sub:
        return None
    return payload
