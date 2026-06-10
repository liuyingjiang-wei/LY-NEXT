from __future__ import annotations

import time
from typing import Any, Generic, TypeVar

MAX_SEARCH_COUNT = 10
DEFAULT_SEARCH_COUNT = 5
DEFAULT_CACHE_MAX_ENTRIES = 100

T = TypeVar("T")


class WebCache(Generic[T]):
    def __init__(self, *, max_entries: int = DEFAULT_CACHE_MAX_ENTRIES) -> None:
        self._data: dict[str, tuple[float, T]] = {}
        self._max_entries = max(1, max_entries)

    def get(self, key: str, ttl_seconds: float) -> T | None:
        if ttl_seconds <= 0:
            return None
        entry = self._data.get(key)
        if not entry:
            return None
        ts, value = entry
        if time.monotonic() - ts > ttl_seconds:
            self._data.pop(key, None)
            return None
        return value

    def set(self, key: str, value: T, ttl_seconds: float) -> None:
        if ttl_seconds <= 0:
            return
        if len(self._data) >= self._max_entries:
            oldest = next(iter(self._data), None)
            if oldest is not None:
                self._data.pop(oldest, None)
        self._data[key] = (time.monotonic(), value)


def normalize_cache_key(value: str) -> str:
    return (value or "").strip().lower()


def clamp_count(value: Any, *, default: int, maximum: int = MAX_SEARCH_COUNT) -> int:
    try:
        n = int(value)
    except (TypeError, ValueError):
        n = default
    return max(1, min(n, maximum))


def normalize_search_hit(*, title: str, url: str, snippet: str) -> dict[str, str]:
    return {
        "title": (title or "").strip(),
        "url": (url or "").strip(),
        "snippet": (snippet or "").strip(),
    }


def truncate_text(text: str, max_chars: int) -> tuple[str, bool]:
    if max_chars <= 0 or len(text) <= max_chars:
        return text, False
    return text[:max_chars] + f"\n... [truncated, {len(text)} chars]", True


def _domain_from_url(url: str) -> str:
    from urllib.parse import urlparse

    try:
        host = (urlparse(url).netloc or "").strip()
        if host.lower().startswith("www."):
            return host[4:]
        return host
    except Exception:
        return ""


def _normalize_provider_id(provider: str) -> str:
    key = (provider or "").strip().lower()
    aliases = {
        "ddg": "duckduckgo",
        "brave_search": "brave",
        "serp_api": "serpapi",
        "jina_reader": "jina",
        "reader": "jina",
        "local": "trafilatura",
        "html": "trafilatura",
    }
    return aliases.get(key, key or "unknown")


def format_web_search_text(
    *,
    query: str,
    provider: str,
    results: list[dict[str, str]],
) -> str:
    q = (query or "").strip()
    engine = _normalize_provider_id(provider)
    bar = "─" * 42
    lines = [
        bar,
        "联网搜索",
        f"关键词：{q}",
        f"引擎：{engine} · 结果数：{len(results)}",
        bar,
        "",
    ]
    if not results:
        lines.append("（未找到相关结果，可换关键词或调大 count）")
        return "\n".join(lines)
    for i, hit in enumerate(results, 1):
        title = (hit.get("title") or "（无标题）").strip()
        url = (hit.get("url") or "").strip()
        snippet = (hit.get("snippet") or "").strip()
        domain = _domain_from_url(url)
        head = f"[{i}] {title}"
        if domain:
            head += f"  ·  {domain}"
        lines.append(head)
        if url:
            lines.append(f"    {url}")
        if snippet:
            compact = " ".join(snippet.split())
            if len(compact) > 300:
                compact = compact[:297] + "…"
            lines.append(f"    {compact}")
        if i < len(results):
            lines.append("")
    return "\n".join(lines).rstrip()


def format_web_fetch_text(
    *,
    url: str,
    final_url: str,
    provider: str,
    content: str,
    truncated: bool,
    fmt: str,
    length: int | None = None,
) -> str:
    engine = _normalize_provider_id(provider)
    bar = "─" * 42
    lines = [
        bar,
        "网页正文",
        f"请求 URL：{url}",
    ]
    if final_url and final_url != url:
        lines.append(f"实际 URL：{final_url}")
    meta: list[str] = [f"引擎 {engine}", f"格式 {fmt}"]
    if length is not None:
        meta.append(f"{length} 字")
    if truncated:
        meta.append("已截断")
    lines.append(" · ".join(meta))
    lines.extend([bar, "", (content or "").strip() or "（页面无正文）"])
    return "\n".join(lines)
