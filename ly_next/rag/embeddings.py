from __future__ import annotations

from typing import Any

import httpx

from ly_next.core.http_url import ensure_http_base
from ly_next.core.logger import get_logger
from ly_next.models.openai_compat_auth import merge_optional_headers, openai_compat_auth_headers

logger = get_logger(__name__)


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
) -> list[list[float]]:
    if not texts:
        return []
    root = ensure_http_base(base_url, default="https://api.openai.com/v1")
    auth = openai_compat_auth_headers(
        api_key, auth_mode=auth_mode, auth_header_name=auth_header_name
    )
    headers = merge_optional_headers(auth, extra_headers)
    headers.setdefault("Content-Type", "application/json")
    async with httpx.AsyncClient(base_url=root, headers=headers, timeout=timeout) as client:
        response = await client.post("/embeddings", json={"model": model, "input": texts})
        response.raise_for_status()
        payload: dict[str, Any] = response.json()
    rows = list(payload.get("data") or [])
    rows.sort(key=lambda x: int(x.get("index", 0)))
    return [list(r["embedding"]) for r in rows if isinstance(r.get("embedding"), list)]
