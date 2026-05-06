from __future__ import annotations

from contextlib import suppress
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
    task: str | None = None,
    dimensions: int | None = None,
    extra_body: dict[str, Any] | None = None,
) -> list[list[float]]:
    if not texts:
        return []
    root = ensure_http_base(base_url, default="https://api.openai.com/v1")
    auth = openai_compat_auth_headers(
        api_key, auth_mode=auth_mode, auth_header_name=auth_header_name
    )
    headers = merge_optional_headers(auth, extra_headers)
    headers.setdefault("Content-Type", "application/json")

    body: dict[str, Any] = {"model": model, "input": texts}
    if task:
        body["task"] = task
    if dimensions is not None and dimensions > 0:
        body["dimensions"] = dimensions
    if extra_body:
        body.update(extra_body)

    async with httpx.AsyncClient(base_url=root, headers=headers, timeout=timeout) as client:
        try:
            response = await client.post("/embeddings", json=body)
            response.raise_for_status()
        except httpx.HTTPStatusError as e:
            snippet = ""
            if e.response is not None:
                with suppress(Exception):
                    snippet = (e.response.text or "")[:2000]
            url = str(e.request.url) if e.request else root
            raise RuntimeError(
                f"Embeddings request failed HTTP {e.response.status_code} for {url}: {snippet}"
            ) from e
        except httpx.RequestError as e:
            raise RuntimeError(f"Embeddings transport error to {root}: {e!r}") from e

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
    return out
