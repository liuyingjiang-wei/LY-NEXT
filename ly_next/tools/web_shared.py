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


def domain_from_url(url: str) -> str:
    return _domain_from_url(url)


def _normalize_domain_pattern(value: str) -> str:
    raw = (value or "").strip().lower()
    for prefix in ("https://", "http://"):
        if raw.startswith(prefix):
            raw = raw[len(prefix) :]
    return raw.strip("/").split("/", 1)[0]


def domain_matches(host: str, pattern: str) -> bool:
    h = _normalize_domain_pattern(host)
    p = _normalize_domain_pattern(pattern)
    if not h or not p:
        return False
    return h == p or h.endswith(f".{p}")


def filter_results_by_domains(
    results: list[dict[str, str]],
    *,
    allowed_domains: list[str] | None = None,
    blocked_domains: list[str] | None = None,
) -> list[dict[str, str]]:
    allow = [_normalize_domain_pattern(x) for x in (allowed_domains or []) if str(x).strip()]
    block = [_normalize_domain_pattern(x) for x in (blocked_domains or []) if str(x).strip()]
    if not allow and not block:
        return results

    kept: list[dict[str, str]] = []
    for hit in results:
        host = hit.get("domain") or domain_from_url(str(hit.get("url") or ""))
        if block and any(domain_matches(host, b) for b in block):
            continue
        if allow and not any(domain_matches(host, a) for a in allow):
            continue
        kept.append(hit)
    return kept


def suggest_fetch_urls(results: list[dict[str, str]], *, max_urls: int = 3) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for hit in results:
        url = (hit.get("url") or "").strip()
        if not url or not url.startswith("http") or url in seen:
            continue
        seen.add(url)
        out.append(url)
        if len(out) >= max(1, max_urls):
            break
    return out


def normalize_search_hit(
    *,
    title: str,
    url: str,
    snippet: str,
    score: float | None = None,
    published: str | None = None,
) -> dict[str, str]:
    clean_url = (url or "").strip()
    hit: dict[str, str] = {
        "title": (title or "").strip(),
        "url": clean_url,
        "snippet": (snippet or "").strip(),
    }
    if clean_url:
        hit["domain"] = domain_from_url(clean_url)
    if score is not None:
        hit["score"] = f"{float(score):.4f}".rstrip("0").rstrip(".")
    if published:
        hit["published"] = str(published).strip()
    return hit


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
        lines.append("（未找到相关结果：缩短 query、换关键词、放宽域名过滤或调大 count）")
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
    fetch_urls = suggest_fetch_urls(results, max_urls=3)
    if fetch_urls:
        lines.extend(["", "下一步：对以下 1–3 条 URL 调用 web_fetch 读取正文后再回答："])
        for u in fetch_urls:
            lines.append(f"  · {u}")
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
