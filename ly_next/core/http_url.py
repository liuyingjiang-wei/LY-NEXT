"""Normalize HTTP(S) base URLs for httpx clients."""

from __future__ import annotations

from typing import Any

# Common mis-copy: ``coding.dashscope`` is not the OpenAI-compatible endpoint (404/400 on /v1/*).
_DASHSCOPE_OPENAI_COMPAT = "https://dashscope.aliyuncs.com/compatible-mode/v1"


def rewrite_known_bad_api_base(url: str) -> str:
    u = str(url or "").strip().rstrip("/")
    if not u:
        return u
    low = u.lower()
    if "coding.dashscope.aliyuncs.com" in low:
        return _DASHSCOPE_OPENAI_COMPAT.rstrip("/")
    return u


def ensure_http_base(raw: Any, *, default: str) -> str:
    """Return a non-empty absolute ``http://`` or ``https://`` base URL for httpx ``base_url``."""
    d = rewrite_known_bad_api_base(str(default or "").strip().rstrip("/"))
    u = str(raw or "").strip().rstrip("/")
    if not u:
        return d
    if u.startswith("http://") or u.startswith("https://"):
        return rewrite_known_bad_api_base(u)
    return rewrite_known_bad_api_base(f"https://{u.lstrip('/')}".rstrip("/"))
