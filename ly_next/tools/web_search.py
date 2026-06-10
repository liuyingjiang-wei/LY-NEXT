from __future__ import annotations

import asyncio
import importlib
from typing import Any

import httpx

from ly_next.core.config import config
from ly_next.tools.base import ToolResult, tool
from ly_next.tools.web_shared import (
    DEFAULT_SEARCH_COUNT,
    WebCache,
    clamp_count,
    format_web_search_text,
    normalize_cache_key,
    normalize_search_hit,
    truncate_text,
)

_SEARCH_CACHE: WebCache[list[dict[str, str]]] = WebCache()

WEB_SEARCH_SCHEMA = {
    "type": "object",
    "required": ["query"],
    "properties": {
        "query": {"type": "string", "description": "Search query."},
        "count": {
            "type": "integer",
            "description": "Result count.",
            "minimum": 1,
            "maximum": 10,
        },
    },
}


def _cfg() -> dict[str, Any]:
    tools = config.get("tools") or {}
    if not isinstance(tools, dict):
        return {}
    ws = tools.get("web_search") or {}
    return ws if isinstance(ws, dict) else {}


def _resolve_provider() -> tuple[str, str]:
    ws = _cfg()
    provider = str(ws.get("provider") or "duckduckgo").strip().lower()
    api_key = str(ws.get("api_key") or "").strip()
    if not api_key and provider == "tavily":
        tools = config.get("tools") or {}
        image = tools.get("image") if isinstance(tools, dict) else {}
        if isinstance(image, dict):
            api_key = str(image.get("tavily_api_key") or "").strip()
    return provider, api_key


def _default_count() -> int:
    ws = _cfg()
    raw = ws.get("default_num_results") or ws.get("count") or DEFAULT_SEARCH_COUNT
    return clamp_count(raw, default=DEFAULT_SEARCH_COUNT)


def _cache_ttl_seconds() -> int:
    ws = _cfg()
    minutes = ws.get("cache_ttl_minutes")
    if minutes is not None:
        return max(0, int(float(minutes) * 60))
    return max(0, int(ws.get("cache_ttl_seconds") or 900))


def _missing_key_error(provider: str) -> str:
    return f"web_search: configure tools.web_search.api_key for provider '{provider}'"


async def _search_duckduckgo(query: str, count: int) -> list[dict[str, str]]:
    try:
        from duckduckgo_search import AsyncDDGS  # type: ignore

        out: list[dict[str, str]] = []
        async with AsyncDDGS() as ddgs:
            async for row in ddgs.atext(query, max_results=count):
                out.append(
                    normalize_search_hit(
                        title=row.get("title", "") or "",
                        url=row.get("href", "") or "",
                        snippet=row.get("body", "") or "",
                    )
                )
        return out
    except ImportError:
        module = importlib.import_module("duckduckgo_search")

        def _sync() -> list[dict[str, str]]:
            rows: list[dict[str, str]] = []
            with module.DDGS() as ddgs:
                for row in ddgs.text(query, max_results=count):
                    rows.append(
                        normalize_search_hit(
                            title=row.get("title", "") or "",
                            url=row.get("href", "") or "",
                            snippet=row.get("body", "") or "",
                        )
                    )
            return rows

        return await asyncio.to_thread(_sync)


async def _search_brave(query: str, count: int, api_key: str) -> list[dict[str, str]]:
    if not api_key:
        raise ValueError(_missing_key_error("brave"))
    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.get(
            "https://api.search.brave.com/res/v1/web/search",
            headers={"Accept": "application/json", "X-Subscription-Token": api_key},
            params={"q": query, "count": str(count)},
        )
        r.raise_for_status()
        data = r.json()
    web = (data.get("web") or {}) if isinstance(data, dict) else {}
    return [
        normalize_search_hit(
            title=str(item.get("title") or ""),
            url=str(item.get("url") or ""),
            snippet=str(item.get("description") or ""),
        )
        for item in (web.get("results") or [])[:count]
        if isinstance(item, dict)
    ]


async def _search_serpapi(query: str, count: int, api_key: str) -> list[dict[str, str]]:
    if not api_key:
        raise ValueError(_missing_key_error("serpapi"))
    async with httpx.AsyncClient(timeout=45.0) as client:
        r = await client.get(
            "https://serpapi.com/search.json",
            params={"engine": "google", "q": query, "num": count, "api_key": api_key},
        )
        r.raise_for_status()
        data = r.json()
    organic = data.get("organic_results") or [] if isinstance(data, dict) else []
    return [
        normalize_search_hit(
            title=str(item.get("title") or ""),
            url=str(item.get("link") or ""),
            snippet=str(item.get("snippet") or ""),
        )
        for item in organic[:count]
        if isinstance(item, dict)
    ]


async def _search_tavily(query: str, count: int, api_key: str) -> list[dict[str, str]]:
    if not api_key:
        raise ValueError(_missing_key_error("tavily"))
    async with httpx.AsyncClient(timeout=45.0) as client:
        r = await client.post(
            "https://api.tavily.com/search",
            json={
                "api_key": api_key,
                "query": query,
                "search_depth": "basic",
                "max_results": count,
            },
        )
        r.raise_for_status()
        data = r.json()
    raw = data.get("results") or [] if isinstance(data, dict) else []
    return [
        normalize_search_hit(
            title=str(item.get("title") or ""),
            url=str(item.get("url") or ""),
            snippet=str(item.get("content") or ""),
        )
        for item in raw[:count]
        if isinstance(item, dict)
    ]


async def run_web_search(query: str, count: int | None = None) -> tuple[str, list[dict[str, str]]]:
    q = (query or "").strip()
    if not q:
        raise ValueError("query is required")
    provider, api_key = _resolve_provider()
    n = clamp_count(count, default=_default_count())
    cache_key = f"{provider}:{n}:{normalize_cache_key(q)}"
    cached = _SEARCH_CACHE.get(cache_key, _cache_ttl_seconds())
    if cached is not None:
        return provider, cached

    if provider in ("duckduckgo", "ddg", ""):
        try:
            results = await _search_duckduckgo(q, n)
        except ImportError as e:
            raise ImportError("install duckduckgo-search") from e
    elif provider in ("brave", "brave_search"):
        results = await _search_brave(q, n, api_key)
    elif provider in ("serpapi", "serp_api"):
        results = await _search_serpapi(q, n, api_key)
    elif provider == "tavily":
        results = await _search_tavily(q, n, api_key)
    else:
        raise ValueError(f"unknown web_search provider: {provider}")

    _SEARCH_CACHE.set(cache_key, results, _cache_ttl_seconds())
    return provider, results


async def web_search(
    query: str, count: int | None = None, num_results: int | None = None
) -> ToolResult:
    try:
        n = count if count is not None else num_results
        provider, results = await run_web_search(query, n)
        payload = {
            "query": query,
            "provider": provider,
            "results": results,
            "count": len(results),
        }
        payload["text"] = format_web_search_text(
            query=str(query or ""),
            provider=provider,
            results=results,
        )
        return ToolResult(success=True, result=payload)
    except ImportError as e:
        return ToolResult(success=False, error=str(e))
    except httpx.HTTPStatusError as e:
        return ToolResult(
            success=False,
            error=f"HTTP {e.response.status_code}: {(e.response.text or '')[:500]}",
        )
    except Exception as e:
        return ToolResult(success=False, error=str(e))


async def web_scrape(url: str, query: str = "") -> ToolResult:
    from ly_next.tools.http_fetch import _url_allowed

    ok, err = _url_allowed(url)
    if not ok:
        return ToolResult(success=False, error=err)

    try:
        from selectolax.parser import HTMLParser

        async with httpx.AsyncClient(
            timeout=30,
            follow_redirects=True,
            max_redirects=8,
            trust_env=False,
        ) as client:
            response = await client.get(url)
            response.raise_for_status()

        final = str(response.url)
        ok2, err2 = _url_allowed(final)
        if not ok2:
            return ToolResult(success=False, error=f"redirect blocked: {err2}")

        parser = HTMLParser(response.text)
        content = parser.text()
        if query:
            nodes = parser.css(query)
            if nodes:
                content = "\n".join(m.text() for m in nodes[:5] if m.text())

        text, truncated = truncate_text(content, 4000)
        title_node = parser.css_first("title")
        return ToolResult(
            success=True,
            result={
                "url": url,
                "title": title_node.text() if title_node else "",
                "content": text,
                "truncated": truncated,
            },
        )
    except ImportError:
        return ToolResult(success=False, error="install selectolax")
    except httpx.HTTPStatusError as e:
        code = e.response.status_code if e.response is not None else "?"
        return ToolResult(success=False, error=f"HTTP {code}")
    except Exception as e:
        return ToolResult(success=False, error=str(e))


web_search_tool = tool(
    name="web_search",
    description=(
        "Search the live web for current facts, news, or prices. "
        "Not for local project docs (use knowledge_search). "
        "Follow with web_fetch on 1–3 result URLs."
    ),
    category="network",
    parameters=WEB_SEARCH_SCHEMA,
)(web_search)

web_scrape_tool = tool(
    name="web_scrape",
    description=(
        "Legacy HTML fetch; prefer web_fetch for readable article text. "
        "Private IPs, loopback, and cloud metadata hosts are blocked."
    ),
    category="network",
    parameters={
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "HTTP(S) URL."},
            "query": {"type": "string", "description": "Optional CSS selector."},
        },
        "required": ["url"],
    },
)(web_scrape)
