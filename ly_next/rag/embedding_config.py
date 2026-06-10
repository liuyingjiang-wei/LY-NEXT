"""Merge agent.rag.embedding overrides with a referenced config block (default rag_embedding_llm)."""

from __future__ import annotations

from typing import Any

from ly_next.core.http_url import ensure_http_base


def resolve_embedding_http_config(emb_cfg: dict[str, Any], config_get: Any) -> dict[str, Any]:
    ref = str(emb_cfg.get("config_ref") or "").strip() or "rag_embedding_llm"
    block: dict[str, Any] = {}
    raw = config_get(ref)
    if isinstance(raw, dict):
        block = raw

    model = str(emb_cfg.get("model") or block.get("model") or "text-embedding-3-small")
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

    extra_body = emb_cfg.get("extra_body")
    if extra_body is None and isinstance(block.get("extra_body"), dict):
        extra_body = block["extra_body"]

    return {
        "model": model,
        "api_key": api_key,
        "base_url": root,
        "timeout": timeout,
        "auth_mode": auth_mode,
        "auth_header_name": auth_header_name,
        "extra_headers": extra_h,
        "task_query": emb_cfg.get("task_query") or block.get("task_query"),
        "task_passage": emb_cfg.get("task_passage") or block.get("task_passage"),
        "dimensions": emb_cfg.get("dimensions")
        if emb_cfg.get("dimensions") is not None
        else block.get("dimensions"),
        "extra_body": extra_body if isinstance(extra_body, dict) else None,
    }
