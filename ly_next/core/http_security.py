"""HTTP security helpers: client IP, path rules, rate-limit parsing."""

from __future__ import annotations

import re
from typing import Any

from starlette.requests import Request

_LIMIT_RE = re.compile(
    r"^\s*(\d+)\s*/\s*(second|minute|hour|day)s?\s*$",
    re.IGNORECASE,
)


def security_config() -> dict[str, Any]:
    from ly_next.core.config import config

    raw = config.get("security")
    return raw if isinstance(raw, dict) else {}


def headers_config() -> dict[str, Any]:
    raw = security_config().get("headers")
    return raw if isinstance(raw, dict) else {}


def rate_limit_config() -> dict[str, Any]:
    raw = security_config().get("rate_limit")
    return raw if isinstance(raw, dict) else {}


def parse_limit(expr: str) -> tuple[int, int] | None:
    """Parse ``count/window`` (e.g. ``120/minute``) -> (count, window_seconds)."""
    m = _LIMIT_RE.match(str(expr or "").strip())
    if not m:
        return None
    count = int(m.group(1))
    if count <= 0:
        return None
    unit = m.group(2).lower()
    window = {"second": 1, "minute": 60, "hour": 3600, "day": 86400}.get(unit)
    if window is None:
        return None
    return count, window


def path_matches_rule(path: str, rule: str) -> bool:
    r = str(rule or "").strip()
    if not r:
        return False
    if r.endswith("*"):
        return path.startswith(r[:-1])
    return path == r


def path_matches_any(path: str, rules: list[str]) -> bool:
    return any(path_matches_rule(path, r) for r in rules)


def client_ip(request: Request, *, trust_proxy_headers: bool) -> str:
    if trust_proxy_headers:
        xff = request.headers.get("x-forwarded-for")
        if xff:
            first = xff.split(",")[0].strip()
            if first:
                return first
        xri = request.headers.get("x-real-ip")
        if xri and xri.strip():
            return xri.strip()
    if request.client and request.client.host:
        return request.client.host
    return "unknown"


def request_is_https(request: Request) -> bool:
    if request.url.scheme == "https":
        return True
    forwarded = (request.headers.get("x-forwarded-proto") or "").split(",")[0].strip().lower()
    return forwarded == "https"


def rate_limit_bucket(request: Request) -> str:
    path = request.url.path
    method = request.method.upper()
    rl = rate_limit_config()
    login_paths = [str(p) for p in (rl.get("login_paths") or ["/ly/login", "/api/auth/login"])]
    agent_prefixes = [str(p) for p in (rl.get("agent_path_prefixes") or [])]

    if method == "POST" and path_matches_any(path, login_paths):
        return "login"
    if any(path.startswith(prefix) for prefix in agent_prefixes if prefix):
        return "agent"
    return "default"


def limit_for_bucket(bucket: str) -> tuple[int, int] | None:
    rl = rate_limit_config()
    key = {
        "login": "login_limit",
        "agent": "agent_limit",
        "default": "default_limit",
    }.get(bucket, "default_limit")
    raw = str(rl.get(key) or rl.get("default_limit") or "120/minute")
    return parse_limit(raw)


def default_content_security_policy() -> str:
    return (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline'; "
        "style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data: https: blob:; "
        "font-src 'self' data:; "
        "connect-src 'self' ws: wss:; "
        "frame-ancestors 'none'; "
        "base-uri 'self'; "
        "form-action 'self'"
    )
