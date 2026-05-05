"""Web search and scrape tools (provider from tools.web_search in config)."""

from __future__ import annotations

from typing import Any

import httpx

from ly_next.core.config import config
from ly_next.tools.base import ToolResult, tool


def _web_search_config() -> dict[str, Any]:
    tools = config.get("tools") or {}
    if not isinstance(tools, dict):
        return {}
    ws = tools.get("web_search") or {}
    return ws if isinstance(ws, dict) else {}


def _provider_and_key() -> tuple[str, str]:
    ws = _web_search_config()
    provider = str(ws.get("provider") or "duckduckgo").strip().lower()
    api_key = str(ws.get("api_key") or "").strip()
    return provider, api_key


async def _search_duckduckgo(query: str, num_results: int) -> list[dict[str, str]]:
    from duckduckgo_search import AsyncDDGS

    results: list[dict[str, str]] = []
    async with AsyncDDGS() as ddgs:
        async for r in ddgs.atext(query, max_results=num_results):
            results.append(
                {
                    "title": r.get("title", "") or "",
                    "href": r.get("href", "") or "",
                    "body": r.get("body", "") or "",
                }
            )
    return results


async def _search_brave(query: str, num_results: int, api_key: str) -> list[dict[str, str]]:
    if not api_key:
        raise ValueError("Brave Search 需要在配置中填写 tools.web_search.api_key")
    count = max(1, min(int(num_results), 20))
    url = "https://api.search.brave.com/res/v1/web/search"
    headers = {
        "Accept": "application/json",
        "X-Subscription-Token": api_key,
    }
    params = {"q": query, "count": str(count)}
    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.get(url, headers=headers, params=params)
        r.raise_for_status()
        data = r.json()
    web = (data.get("web") or {}) if isinstance(data, dict) else {}
    raw = web.get("results") or []
    out: list[dict[str, str]] = []
    for item in raw[:count]:
        if not isinstance(item, dict):
            continue
        out.append(
            {
                "title": str(item.get("title") or ""),
                "href": str(item.get("url") or ""),
                "body": str(item.get("description") or ""),
            }
        )
    return out


async def _search_serpapi(query: str, num_results: int, api_key: str) -> list[dict[str, str]]:
    if not api_key:
        raise ValueError("SerpAPI 需要在配置中填写 tools.web_search.api_key")
    num = max(1, min(int(num_results), 20))
    url = "https://serpapi.com/search.json"
    params = {"engine": "google", "q": query, "num": num, "api_key": api_key}
    async with httpx.AsyncClient(timeout=45.0) as client:
        r = await client.get(url, params=params)
        r.raise_for_status()
        data = r.json()
    organic = data.get("organic_results") or [] if isinstance(data, dict) else []
    out: list[dict[str, str]] = []
    for item in organic[:num]:
        if not isinstance(item, dict):
            continue
        out.append(
            {
                "title": str(item.get("title") or ""),
                "href": str(item.get("link") or ""),
                "body": str(item.get("snippet") or ""),
            }
        )
    return out


async def _search_tavily(query: str, num_results: int, api_key: str) -> list[dict[str, str]]:
    if not api_key:
        raise ValueError("Tavily 需要在配置中填写 tools.web_search.api_key")
    max_r = max(1, min(int(num_results), 20))
    url = "https://api.tavily.com/search"
    payload = {
        "api_key": api_key,
        "query": query,
        "search_depth": "basic",
        "max_results": max_r,
    }
    async with httpx.AsyncClient(timeout=45.0) as client:
        r = await client.post(url, json=payload)
        r.raise_for_status()
        data = r.json()
    raw = data.get("results") or [] if isinstance(data, dict) else []
    out: list[dict[str, str]] = []
    for item in raw[:max_r]:
        if not isinstance(item, dict):
            continue
        out.append(
            {
                "title": str(item.get("title") or ""),
                "href": str(item.get("url") or ""),
                "body": str(item.get("content") or ""),
            }
        )
    return out


async def web_search(query: str, num_results: int = 5) -> ToolResult:
    """Search the web; provider and API key from server config (tools.web_search)."""
    try:
        provider, api_key = _provider_and_key()
        n = max(1, min(int(num_results), 20))

        if provider in ("duckduckgo", "ddg", ""):
            try:
                results = await _search_duckduckgo(query, n)
            except ImportError:
                return ToolResult(
                    success=False,
                    error="请安装 duckduckgo-search: pip install duckduckgo-search",
                )
        elif provider in ("brave", "brave_search"):
            results = await _search_brave(query, n, api_key)
        elif provider in ("serpapi", "serp_api"):
            results = await _search_serpapi(query, n, api_key)
        elif provider in ("tavily",):
            results = await _search_tavily(query, n, api_key)
        else:
            return ToolResult(
                success=False,
                error=f"未知搜索厂商: {provider}。可选: duckduckgo, brave, serpapi, tavily",
            )

        return ToolResult(
            success=True,
            result={
                "query": query,
                "provider": provider or "duckduckgo",
                "results": results,
                "count": len(results),
            },
        )
    except httpx.HTTPStatusError as e:
        return ToolResult(
            success=False,
            error=f"搜索 API HTTP {e.response.status_code}: {e.response.text[:500]}",
        )
    except Exception as e:
        return ToolResult(success=False, error=str(e))


async def web_scrape(url: str, query: str = "") -> ToolResult:
    """Scrape content from a webpage."""
    try:
        from selectolax.parser import HTMLParser

        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(url)
            response.raise_for_status()

        parser = HTMLParser(response.text)
        content = parser.text()

        if query:
            matches = parser.css(query)
            if matches:
                content = "\n".join([m.text() for m in matches[:5] if m.text()])

        if len(content) > 4000:
            content = content[:4000] + "..."

        return ToolResult(
            success=True,
            result={
                "url": url,
                "title": parser.css_first("title").text() if parser.css_first("title") else "",
                "content": content,
                "length": len(content),
            },
        )

    except ImportError:
        return ToolResult(success=False, error="请安装 selectolax: pip install selectolax")
    except Exception as e:
        return ToolResult(success=False, error=str(e))


web_search_tool = tool(
    name="web_search",
    description=(
        "Search the public web. Provider is configured on the server "
        "(tools.web_search: duckduckgo needs no key; brave / serpapi / tavily need api_key)."
    ),
    parameters={
        "type": "object",
        "properties": {
            "query": {"type": "string"},
            "num_results": {"type": "integer", "default": 5},
        },
        "required": ["query"],
    },
)(web_search)

web_scrape_tool = tool(
    name="web_scrape",
    description="Fetch a URL and return main text content (HTML stripped).",
    parameters={
        "type": "object",
        "properties": {
            "url": {"type": "string"},
            "query": {"type": "string"},
        },
        "required": ["url"],
    },
)(web_scrape)
