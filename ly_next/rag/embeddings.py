from __future__ import annotations

import hashlib
import json
import time
from contextlib import suppress
from typing import Any

import httpx

from ly_next.core.http_url import ensure_http_base
from ly_next.core.logger import get_logger
from ly_next.models.openai_compat_auth import merge_optional_headers, openai_compat_auth_headers

logger = get_logger(__name__)

_EMBED_CLIENTS: dict[str, httpx.AsyncClient] = {}
_QUERY_VEC_CACHE: dict[str, tuple[float, list[float]]] = {}
_QUERY_VEC_TTL_SEC = 300.0
_QUERY_VEC_MAX = 256


def _embed_client_key(
    *,
    base_url: str,
    api_key: str,
    auth_mode: str | None,
    auth_header_name: str | None,
    extra_headers: dict[str, Any] | None,
) -> str:
    auth = openai_compat_auth_headers(
        api_key, auth_mode=auth_mode, auth_header_name=auth_header_name
    )
    headers = merge_optional_headers(auth, extra_headers)
    payload = {
        "base_url": ensure_http_base(base_url, default="https://api.openai.com/v1"),
        "headers": sorted(headers.items()),
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:24]


def _get_embedding_client(
    *,
    base_url: str,
    api_key: str,
    timeout: float,
    auth_mode: str | None,
    auth_header_name: str | None,
    extra_headers: dict[str, Any] | None,
) -> httpx.AsyncClient:
    key = _embed_client_key(
        base_url=base_url,
        api_key=api_key,
        auth_mode=auth_mode,
        auth_header_name=auth_header_name,
        extra_headers=extra_headers,
    )
    existing = _EMBED_CLIENTS.get(key)
    if existing is not None and not existing.is_closed:
        return existing

    root = ensure_http_base(base_url, default="https://api.openai.com/v1")
    auth = openai_compat_auth_headers(
        api_key, auth_mode=auth_mode, auth_header_name=auth_header_name
    )
    headers = merge_optional_headers(auth, extra_headers)
    headers.setdefault("Content-Type", "application/json")
    read_timeout = float(timeout) if timeout else 120.0
    connect_timeout = min(10.0, read_timeout)
    client = httpx.AsyncClient(
        base_url=root,
        headers=headers,
        timeout=httpx.Timeout(connect=connect_timeout, read=read_timeout, write=30.0, pool=5.0),
        limits=httpx.Limits(max_connections=16, max_keepalive_connections=8),
    )
    _EMBED_CLIENTS[key] = client
    return client


def _query_cache_key(model: str, text: str) -> str:
    norm = " ".join(str(text or "").strip().lower().split())
    digest = hashlib.sha256(norm.encode("utf-8")).hexdigest()[:32]
    return f"{model}:{digest}"


def _cache_get_query_vector(key: str) -> list[float] | None:
    row = _QUERY_VEC_CACHE.get(key)
    if row is None:
        return None
    ts, vec = row
    if time.monotonic() - ts > _QUERY_VEC_TTL_SEC:
        _QUERY_VEC_CACHE.pop(key, None)
        return None
    return vec


def _cache_put_query_vector(key: str, vec: list[float]) -> None:
    if len(_QUERY_VEC_CACHE) >= _QUERY_VEC_MAX:
        oldest = min(_QUERY_VEC_CACHE.items(), key=lambda item: item[1][0])[0]
        _QUERY_VEC_CACHE.pop(oldest, None)
    _QUERY_VEC_CACHE[key] = (time.monotonic(), vec)


async def fetch_embeddings(
    texts: list[str],
    *,
    model: str,
    api_key: str,
    base_url: str,
    timeout: float = 120.0,
    auth_mode: str | None = None,
    auth_header_name: str | None = None,
    extra_headers: dict[str, Any] | None = None,
    task: str | None = None,
    dimensions: int | None = None,
    extra_body: dict[str, Any] | None = None,
) -> list[list[float]]:
    if not texts:
        return []

    use_query_cache = len(texts) == 1
    cache_key = _query_cache_key(model, texts[0]) if use_query_cache else ""
    if use_query_cache:
        cached = _cache_get_query_vector(cache_key)
        if cached is not None:
            return [cached]

    client = _get_embedding_client(
        base_url=base_url,
        api_key=api_key,
        timeout=timeout,
        auth_mode=auth_mode,
        auth_header_name=auth_header_name,
        extra_headers=extra_headers,
    )

    body: dict[str, Any] = {"model": model, "input": texts}
    if task:
        body["task"] = task
    if dimensions is not None and dimensions > 0:
        body["dimensions"] = dimensions
    if extra_body:
        body.update(extra_body)

    try:
        response = await client.post("/embeddings", json=body)
        response.raise_for_status()
    except httpx.HTTPStatusError as e:
        snippet = ""
        if e.response is not None:
            with suppress(Exception):
                snippet = (e.response.text or "")[:2000]
        url = str(e.request.url) if e.request else client.base_url
        raise RuntimeError(
            f"Embeddings request failed HTTP {e.response.status_code} for {url}: {snippet}"
        ) from e
    except httpx.RequestError as e:
        raise RuntimeError(f"Embeddings transport error to {client.base_url}: {e!r}") from e

    try:
        payload: dict[str, Any] = response.json()
    except Exception as e:
        txt = (response.text or "")[:2000]
        raise RuntimeError(
            f"Embeddings response is not JSON (status {response.status_code}): {txt}"
        ) from e

    rows = list(payload.get("data") or [])
    rows.sort(key=lambda x: int(x.get("index", 0)))
    out = [list(r["embedding"]) for r in rows if isinstance(r.get("embedding"), list)]
    if not out and rows:
        logger.warning(
            "[embeddings] Response had %s rows but no usable embedding vectors; keys sample=%s",
            len(rows),
            list(rows[0].keys()) if rows and isinstance(rows[0], dict) else None,
        )
    if use_query_cache and out:
        _cache_put_query_vector(cache_key, out[0])
    return out
