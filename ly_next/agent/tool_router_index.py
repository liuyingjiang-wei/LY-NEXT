from __future__ import annotations

import hashlib
from typing import Any

from ly_next.agent.tool_router import semantic_select_enabled, tool_document
from ly_next.core.config import config
from ly_next.core.logger import get_logger
from ly_next.rag.embedding_config import resolve_embedding_http_config
from ly_next.rag.embeddings import fetch_embeddings
from ly_next.rag.similarity import cosine_similarity

logger = get_logger(__name__)

_TOOL_VEC_CACHE: dict[str, list[float]] = {}
_TOOL_VEC_SIG: str = ""


def _embedding_http() -> dict[str, Any] | None:
    policy = config.get("agent.tool_policy", {}) or {}
    if not isinstance(policy, dict):
        policy = {}
    emb_cfg = policy.get("embedding")
    if not isinstance(emb_cfg, dict) or not emb_cfg:
        emb_cfg = config.get("agent.rag.embedding", {}) or {}
    if not isinstance(emb_cfg, dict):
        emb_cfg = {}
    hp = resolve_embedding_http_config(emb_cfg, config.get)
    if not str(hp.get("api_key") or "").strip():
        return None
    return hp


def _tools_signature(tools: list[Any]) -> str:
    parts = [tool_document(t) for t in tools]
    raw = "\x1e".join(parts)
    return hashlib.sha256(raw.encode()).hexdigest()[:24]


async def _embed_texts(texts: list[str], hp: dict[str, Any], *, task: str | None) -> list[list[float]]:
    dims = hp.get("dimensions")
    dim_opt: int | None = None
    if dims is not None:
        try:
            di = int(dims)
            dim_opt = di if di > 0 else None
        except (TypeError, ValueError):
            dim_opt = None
    xbody = hp.get("extra_body") if isinstance(hp.get("extra_body"), dict) else None
    return await fetch_embeddings(
        texts,
        model=str(hp["model"]),
        api_key=str(hp["api_key"]),
        base_url=str(hp["base_url"]),
        timeout=float(hp.get("timeout") or 60),
        auth_mode=hp.get("auth_mode"),
        auth_header_name=hp.get("auth_header_name"),
        extra_headers=hp.get("extra_headers"),
        task=task,
        dimensions=dim_opt,
        extra_body=xbody,
    )


async def ensure_tool_vectors(tools: list[Any]) -> dict[str, list[float]] | None:
    hp = _embedding_http()
    if not hp or not tools:
        return None

    global _TOOL_VEC_SIG
    sig = _tools_signature(tools)
    if _TOOL_VEC_SIG == sig and _TOOL_VEC_CACHE:
        return _TOOL_VEC_CACHE

    docs = [tool_document(t) for t in tools]
    batch = 32
    merged: dict[str, list[float]] = {}
    task_p = hp.get("task_passage")
    try:
        for i in range(0, len(docs), batch):
            sub_docs = docs[i : i + batch]
            sub_tools = tools[i : i + batch]
            vecs = await _embed_texts(sub_docs, hp, task=str(task_p) if task_p else None)
            for tool, vec in zip(sub_tools, vecs, strict=False):
                merged[tool.definition.name] = vec
    except Exception as e:
        logger.warning("[tool_router] tool embedding failed: %s", e)
        return None

    if not merged:
        return None

    _TOOL_VEC_CACHE.clear()
    _TOOL_VEC_CACHE.update(merged)
    _TOOL_VEC_SIG = sig
    return _TOOL_VEC_CACHE


async def embed_router_query(query: str) -> list[float] | None:
    q = (query or "").strip()
    if not q:
        return None
    hp = _embedding_http()
    if not hp:
        return None
    task_q = hp.get("task_query")
    try:
        rows = await _embed_texts([q], hp, task=str(task_q) if task_q else None)
    except Exception as e:
        logger.warning("[tool_router] query embedding failed: %s", e)
        return None
    return rows[0] if rows else None


def score_tools_by_embedding(
    tools: list[Any],
    query_vec: list[float],
    tool_vectors: dict[str, list[float]],
) -> list[tuple[float, Any]]:
    scored: list[tuple[float, Any]] = []
    for tool in tools:
        vec = tool_vectors.get(tool.definition.name)
        if not vec:
            continue
        scored.append((cosine_similarity(query_vec, vec), tool))
    scored.sort(key=lambda x: x[0], reverse=True)
    return scored


async def prepare_tool_router_context(deps: Any, tools: list[Any]) -> None:
    if not semantic_select_enabled():
        return
    query = str(getattr(deps, "tool_router_query", None) or "").strip()
    if not query or not tools:
        return

    policy = config.get("agent.tool_policy", {}) or {}
    if not isinstance(policy, dict):
        policy = {}
    method = str(policy.get("semantic_method") or "embedding").strip().lower()
    if method not in ("embedding", "lexical", "hybrid"):
        method = "embedding"

    deps.tool_router_method = method
    deps.tool_router_query_vec = None
    deps.tool_router_tool_vectors = None

    if method in ("embedding", "hybrid"):
        tool_vectors = await ensure_tool_vectors(tools)
        query_vec = await embed_router_query(query)
        if tool_vectors and query_vec:
            deps.tool_router_tool_vectors = tool_vectors
            deps.tool_router_query_vec = query_vec
            deps.tool_router_method = "embedding" if method == "embedding" else "hybrid"
            return
        if method == "embedding":
            deps.tool_router_method = "lexical"
            logger.debug("[tool_router] embedding unavailable; falling back to lexical routing")
