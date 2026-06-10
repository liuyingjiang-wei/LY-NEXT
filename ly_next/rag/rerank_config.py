"""Merge agent.rag.rerank overrides with a referenced config block."""

from __future__ import annotations

from typing import Any

from ly_next.core.http_url import ensure_http_base


def resolve_rerank_http_config(rerank_cfg: dict[str, Any], config_get: Any) -> dict[str, Any]:
    ref = str(rerank_cfg.get("config_ref") or "").strip() or "rag_rerank_llm"
    block: dict[str, Any] = {}
    raw = config_get(ref)
    if isinstance(raw, dict):
        block = raw

    provider = str(rerank_cfg.get("provider") or block.get("provider") or "cohere").strip().lower()
    model = str(rerank_cfg.get("model") or block.get("model") or "rerank-v3.5")
    base_raw = (
        rerank_cfg.get("base_url")
        or rerank_cfg.get("baseUrl")
        or block.get("base_url")
        or block.get("baseUrl")
    )
    default_base = {
        "cohere": "https://api.cohere.com/v2",
        "jina": "https://api.jina.ai/v1",
        "voyage": "https://api.voyageai.com/v1",
    }.get(provider, "https://api.cohere.com/v2")
    root = ensure_http_base(base_raw, default=default_base)
    api_key = str(
        rerank_cfg.get("api_key") or rerank_cfg.get("apiKey") or block.get("api_key") or ""
    )
    to = rerank_cfg.get("timeout")
    if to is None:
        to = block.get("timeout", 60)
    timeout = float(to or 60)
    auth_mode = (
        rerank_cfg.get("auth_mode")
        or rerank_cfg.get("authMode")
        or block.get("auth_mode")
        or block.get("authMode")
    )
    auth_header_name = (
        rerank_cfg.get("auth_header_name")
        or rerank_cfg.get("authHeaderName")
        or block.get("auth_header_name")
        or block.get("authHeaderName")
    )
    extra_h = rerank_cfg.get("headers") if isinstance(rerank_cfg.get("headers"), dict) else None
    if extra_h is None and isinstance(block.get("headers"), dict):
        extra_h = block["headers"]

    return {
        "provider": provider,
        "model": model,
        "api_key": api_key,
        "base_url": root,
        "timeout": timeout,
        "auth_mode": auth_mode,
        "auth_header_name": auth_header_name,
        "extra_headers": extra_h,
    }
