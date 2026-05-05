"""Authentication headers for OpenAI-compatible HTTP APIs (multiple vendor styles)."""

from __future__ import annotations

from typing import Any


def openai_compat_auth_headers(
    api_key: str,
    *,
    auth_mode: str | None = None,
    auth_header_name: str | None = None,
) -> dict[str, str]:
    """
    Build default request headers for chat/embeddings.

    ``auth_mode`` (also accepts camelCase via merged config): ``bearer`` | ``api-key`` |
    ``header`` | ``x-dashscope-api-key``.
    """
    key = (api_key or "").strip()
    raw = (auth_mode or "bearer").strip().lower().replace("_", "-")
    out: dict[str, str] = {}
    if not key:
        return out
    if raw in ("api-key", "apikey"):
        out["api-key"] = key
    elif raw in ("dashscope", "dashscope-dual"):
        out["Authorization"] = f"Bearer {key}"
        out["X-DashScope-API-Key"] = key
    elif raw == "header":
        name = (auth_header_name or "").strip()
        if not name:
            raise ValueError("auth_mode 'header' requires auth_header_name")
        out[name] = key
    elif raw in ("x-dashscope-api-key", "dashscope-api-key"):
        out["X-DashScope-API-Key"] = key
    else:
        out["Authorization"] = f"Bearer {key}"
    return out


def merge_optional_headers(
    base: dict[str, str],
    extra: dict[str, Any] | None,
) -> dict[str, str]:
    if not extra:
        return base
    merged = dict(base)
    for k, v in extra.items():
        if v is None:
            continue
        merged[str(k)] = str(v)
    return merged


def require_remote_api_key(
    api_key: str,
    base_url: str,
    *,
    auth_mode: str | None,
    auth_header_name: str | None,
) -> None:
    """Raise if a remote (non-loopback) base URL would send no auth headers."""
    if openai_compat_auth_headers(api_key, auth_mode=auth_mode, auth_header_name=auth_header_name):
        return
    u = (base_url or "").lower()
    if "localhost" in u or "127.0.0.1" in u:
        return
    raise ValueError(
        "API key is missing for this LLM endpoint (set the matching *_llm.api_key or env var)."
    )
