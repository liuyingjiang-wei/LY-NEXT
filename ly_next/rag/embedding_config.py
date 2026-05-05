"""Resolve HTTP settings for embedding requests (may differ from chat LLM)."""

from __future__ import annotations

from typing import Any

from ly_next.core.http_url import ensure_http_base


def resolve_embedding_http_config(emb_cfg: dict[str, Any], config_get: Any) -> dict[str, Any]:
    """
    Merge ``agent.rag.embedding`` with the referenced LLM block.

    Explicit keys on ``emb_cfg`` override the referenced block: ``base_url``, ``api_key``,
    ``auth_mode``, ``headers``, ``timeout``.
    """
    ref = str(emb_cfg.get("config_ref") or "openai_compat_llm")
    block: dict[str, Any] = {}
    raw = config_get(ref)
    if isinstance(raw, dict):
        block = raw

    model = str(emb_cfg.get("model") or "text-embedding-3-small")
    base_raw = (
        emb_cfg.get("base_url")
        or emb_cfg.get("baseUrl")
        or block.get("base_url")
        or block.get("baseUrl")
    )
    root = ensure_http_base(base_raw, default="https://api.openai.com/v1")
    api_key = str(emb_cfg.get("api_key") or emb_cfg.get("apiKey") or block.get("api_key") or "")
    to = emb_cfg.get("timeout")
    if to is None:
        to = block.get("timeout", 60)
    timeout = float(to or 60)
    auth_mode = (
        emb_cfg.get("auth_mode")
        or emb_cfg.get("authMode")
        or block.get("auth_mode")
        or block.get("authMode")
    )
    auth_header_name = (
        emb_cfg.get("auth_header_name")
        or emb_cfg.get("authHeaderName")
        or block.get("auth_header_name")
        or block.get("authHeaderName")
    )
    extra_h = emb_cfg.get("headers") if isinstance(emb_cfg.get("headers"), dict) else None
    if extra_h is None and isinstance(block.get("headers"), dict):
        extra_h = block["headers"]

    return {
        "model": model,
        "api_key": api_key,
        "base_url": root,
        "timeout": timeout,
        "auth_mode": auth_mode,
        "auth_header_name": auth_header_name,
        "extra_headers": extra_h,
    }
