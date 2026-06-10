from __future__ import annotations

from typing import Any

import httpx

from ly_next.core.config import config
from ly_next.core.logger import get_logger
from ly_next.models.openai_compat_auth import merge_optional_headers, openai_compat_auth_headers
from ly_next.rag.rerank_config import resolve_rerank_http_config

logger = get_logger(__name__)


def _rerank_cfg() -> dict[str, Any]:
    raw = config.get("agent.rag.rerank", {}) or {}
    return raw if isinstance(raw, dict) else {}


def rerank_enabled() -> bool:
    return bool(_rerank_cfg().get("enabled", False))


async def rerank_chunks(
    query: str,
    ranked: list[tuple[float, str]],
    *,
    top_k: int,
) -> list[tuple[float, str]]:
    """Re-score candidate chunks; on failure returns the input order truncated to top_k."""
    if not ranked or top_k <= 0:
        return ranked[:top_k]

    cfg = _rerank_cfg()
    if not cfg.get("enabled", False):
        return ranked[:top_k]

    q = (query or "").strip()
    if not q:
        return ranked[:top_k]

    hp = resolve_rerank_http_config(cfg, config.get)
    provider = str(hp.get("provider") or "cohere").strip().lower()
    api_key = str(hp.get("api_key") or "").strip()
    if not api_key:
        logger.warning("[rag.rerank] enabled but api_key missing; skipping rerank")
        return ranked[:top_k]

    documents = [ch for _sc, ch in ranked if ch]
    if not documents:
        return ranked[:top_k]

    try:
        if provider == "cohere":
            scores = await _cohere_rerank(q, documents, hp=hp, top_n=top_k)
        elif provider == "jina":
            scores = await _jina_rerank(q, documents, hp=hp, top_n=top_k)
        elif provider == "voyage":
            scores = await _voyage_rerank(q, documents, hp=hp, top_n=top_k)
        else:
            logger.warning("[rag.rerank] unknown provider %s; skipping", provider)
            return ranked[:top_k]
    except Exception as e:
        logger.warning("[rag.rerank] failed (%s): %s", type(e).__name__, e)
        return ranked[:top_k]

    if not scores:
        return ranked[:top_k]

    out: list[tuple[float, str]] = []
    seen: set[str] = set()
    for idx, score in scores:
        if idx < 0 or idx >= len(documents):
            continue
        ch = documents[idx]
        if ch in seen:
            continue
        seen.add(ch)
        out.append((float(score), ch))
        if len(out) >= top_k:
            break
    return out or ranked[:top_k]


def _auth_headers(hp: dict[str, Any]) -> dict[str, str]:
    api_key = str(hp.get("api_key") or "")
    auth = openai_compat_auth_headers(
        api_key,
        auth_mode=hp.get("auth_mode"),
        auth_header_name=hp.get("auth_header_name"),
    )
    headers = merge_optional_headers(auth, hp.get("extra_headers"))
    headers.setdefault("Content-Type", "application/json")
    provider = str(hp.get("provider") or "").lower()
    if provider == "cohere" and api_key and "Authorization" not in headers:
        headers["Authorization"] = f"Bearer {api_key}"
    return headers


async def _post_json(
    url: str, *, headers: dict[str, str], body: dict[str, Any], timeout: float
) -> dict[str, Any]:
    read_timeout = float(timeout) if timeout else 60.0
    connect_timeout = min(10.0, read_timeout)
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(connect=connect_timeout, read=read_timeout, write=30.0, pool=5.0),
    ) as client:
        response = await client.post(url, headers=headers, json=body)
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise RuntimeError("rerank response is not a JSON object")
        return payload


async def _cohere_rerank(
    query: str,
    documents: list[str],
    *,
    hp: dict[str, Any],
    top_n: int,
) -> list[tuple[int, float]]:
    base = str(hp.get("base_url") or "https://api.cohere.com/v2").rstrip("/")
    url = f"{base}/rerank"
    body = {
        "model": hp.get("model") or "rerank-v3.5",
        "query": query,
        "documents": documents,
        "top_n": min(top_n, len(documents)),
    }
    payload = await _post_json(
        url, headers=_auth_headers(hp), body=body, timeout=float(hp.get("timeout") or 60)
    )
    rows = list(payload.get("results") or [])
    out: list[tuple[int, float]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        idx = row.get("index")
        score = row.get("relevance_score", row.get("score"))
        if idx is None or score is None:
            continue
        out.append((int(idx), float(score)))
    return out


async def _jina_rerank(
    query: str,
    documents: list[str],
    *,
    hp: dict[str, Any],
    top_n: int,
) -> list[tuple[int, float]]:
    base = str(hp.get("base_url") or "https://api.jina.ai/v1").rstrip("/")
    url = f"{base}/rerank"
    body = {
        "model": hp.get("model") or "jina-reranker-v2-base-multilingual",
        "query": query,
        "documents": documents,
        "top_n": min(top_n, len(documents)),
    }
    headers = _auth_headers(hp)
    if hp.get("api_key"):
        headers["Authorization"] = f"Bearer {hp['api_key']}"
    payload = await _post_json(
        url, headers=headers, body=body, timeout=float(hp.get("timeout") or 60)
    )
    rows = list(payload.get("results") or payload.get("data") or [])
    out: list[tuple[int, float]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        idx = row.get("index")
        score = row.get("relevance_score", row.get("score"))
        if idx is None or score is None:
            continue
        out.append((int(idx), float(score)))
    return out


async def _voyage_rerank(
    query: str,
    documents: list[str],
    *,
    hp: dict[str, Any],
    top_n: int,
) -> list[tuple[int, float]]:
    base = str(hp.get("base_url") or "https://api.voyageai.com/v1").rstrip("/")
    url = f"{base}/rerank"
    body = {
        "model": hp.get("model") or "rerank-2",
        "query": query,
        "documents": documents,
        "top_k": min(top_n, len(documents)),
    }
    payload = await _post_json(
        url, headers=_auth_headers(hp), body=body, timeout=float(hp.get("timeout") or 60)
    )
    rows = list(payload.get("data") or payload.get("results") or [])
    out: list[tuple[int, float]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        idx = row.get("index")
        score = row.get("relevance_score", row.get("score"))
        if idx is None or score is None:
            continue
        out.append((int(idx), float(score)))
    return out
