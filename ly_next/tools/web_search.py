from __future__ import annotations

import asyncio
import importlib
from typing import Any

import httpx

from ly_next.core.config import config
from ly_next.core.logger import get_logger
from ly_next.tools.base import ToolResult, tool
from ly_next.tools.web_shared import (
    DEFAULT_SEARCH_COUNT,
    WebCache,
    clamp_count,
    filter_results_by_domains,
    format_web_search_text,
    normalize_cache_key,
    normalize_search_hit,
    suggest_fetch_urls,
    truncate_text,
)

logger = get_logger(__name__)

_SEARCH_CACHE: WebCache[list[dict[str, str]]] = WebCache()

WEB_SEARCH_SCHEMA = {
    "type": "object",
    "required": ["query"],
    "properties": {
        "query": {
            "type": "string",
            "description": (
                "Short focused search keywords (2–12 words). "
                "Not a full question — e.g. 'OpenAI GPT-5 release date' not "
                "'When did OpenAI release GPT-5?'."
            ),
        },
        "count": {
            "type": "integer",
            "description": "Number of results (1–10). Default from config.",
            "minimum": 1,
            "maximum": 10,
        },
        "allowed_domains": {
            "type": "array",
            "items": {"type": "string"},
            "description": (
                "Optional allowlist (max 20). Omit http/https — e.g. "
                "'arxiv.org', 'github.com'. Subdomains included."
            ),
        },
        "blocked_domains": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Optional blocklist (max 20). Same format as allowed_domains.",
        },
        "recency_days": {
            "type": "integer",
            "description": (
                "Best-effort: only recent pages (Tavily/Brave). 1=today-ish, 7=week, 30=month."
            ),
            "minimum": 1,
            "maximum": 365,
        },
    },
}

_PROVIDER_ALIASES = {
    "ddg": "duckduckgo",
    "brave_search": "brave",
    "serp_api": "serpapi",
}


def _cfg() -> dict[str, Any]:
    tools = config.get("tools") or {}
    if not isinstance(tools, dict):
        return {}
    ws = tools.get("web_search") or {}
    return ws if isinstance(ws, dict) else {}


def _image_cfg() -> dict[str, Any]:
    tools = config.get("tools") or {}
    if not isinstance(tools, dict):
        return {}
    image = tools.get("image") or {}
    return image if isinstance(image, dict) else {}


def _normalize_provider_id(provider: str) -> str:
    key = (provider or "").strip().lower()
    return _PROVIDER_ALIASES.get(key, key or "duckduckgo")


def _resolve_provider_chain() -> list[str]:
    ws = _cfg()
    primary = _normalize_provider_id(str(ws.get("provider") or "duckduckgo"))
    raw_fallback = ws.get("fallback_providers") or ws.get("fallback") or []
    fallbacks: list[str] = []
    if isinstance(raw_fallback, list):
        for item in raw_fallback:
            pid = _normalize_provider_id(str(item))
            if pid and pid != primary and pid not in fallbacks:
                fallbacks.append(pid)
    return [primary, *fallbacks]


def _api_key_for_provider(provider: str) -> str:
    ws = _cfg()
    image = _image_cfg()
    pid = _normalize_provider_id(provider)
    shared = str(ws.get("api_key") or "").strip()
    if shared:
        return shared
    if pid == "tavily":
        return str(image.get("tavily_api_key") or "").strip()
    if pid == "brave":
        return str(image.get("brave_search_api_key") or image.get("brave_api_key") or "").strip()
    if pid == "serpapi":
        return str(image.get("serpapi_api_key") or "").strip()
    if pid == "bing":
        return str(image.get("bing_search_api_key") or "").strip()
    return ""


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


def _search_depth() -> str:
    depth = str(_cfg().get("search_depth") or "basic").strip().lower()
    return "advanced" if depth == "advanced" else "basic"


def _default_domain_filters() -> tuple[list[str], list[str]]:
    ws = _cfg()
    allow = ws.get("allowed_domains") if isinstance(ws.get("allowed_domains"), list) else []
    block = ws.get("blocked_domains") if isinstance(ws.get("blocked_domains"), list) else []
    return [str(x).strip() for x in allow if str(x).strip()], [
        str(x).strip() for x in block if str(x).strip()
    ]


def _merge_domain_lists(
    runtime: list[str] | None,
    defaults: list[str],
    *,
    limit: int = 20,
) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for raw in list(runtime or []) + list(defaults):
        item = str(raw).strip()
        if not item:
            continue
        key = item.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
        if len(out) >= limit:
            break
    return out


def _missing_key_error(provider: str) -> str:
    return f"web_search: configure tools.web_search.api_key for provider '{provider}'"


def _brave_freshness(recency_days: int | None) -> str | None:
    if recency_days is None:
        return None
    if recency_days <= 1:
        return "pd"
    if recency_days <= 7:
        return "pw"
    if recency_days <= 31:
        return "pm"
    if recency_days <= 365:
        return "py"
    return None


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


async def _search_brave(
    query: str,
    count: int,
    api_key: str,
    *,
    recency_days: int | None = None,
) -> list[dict[str, str]]:
    if not api_key:
        raise ValueError(_missing_key_error("brave"))
    params: dict[str, str] = {"q": query, "count": str(count)}
    freshness = _brave_freshness(recency_days)
    if freshness:
        params["freshness"] = freshness
    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.get(
            "https://api.search.brave.com/res/v1/web/search",
            headers={"Accept": "application/json", "X-Subscription-Token": api_key},
            params=params,
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


async def _search_tavily(
    query: str,
    count: int,
    api_key: str,
    *,
    allowed_domains: list[str] | None = None,
    blocked_domains: list[str] | None = None,
    recency_days: int | None = None,
    search_depth: str = "basic",
) -> list[dict[str, str]]:
    if not api_key:
        raise ValueError(_missing_key_error("tavily"))
    body: dict[str, Any] = {
        "api_key": api_key,
        "query": query,
        "search_depth": search_depth,
        "max_results": count,
    }
    if allowed_domains:
        body["include_domains"] = allowed_domains[:20]
    if blocked_domains:
        body["exclude_domains"] = blocked_domains[:20]
    if recency_days is not None:
        body["days"] = max(1, min(int(recency_days), 365))
    async with httpx.AsyncClient(timeout=45.0) as client:
        r = await client.post("https://api.tavily.com/search", json=body)
        r.raise_for_status()
        data = r.json()
    raw = data.get("results") or [] if isinstance(data, dict) else []
    out: list[dict[str, str]] = []
    for item in raw[:count]:
        if not isinstance(item, dict):
            continue
        out.append(
            normalize_search_hit(
                title=str(item.get("title") or ""),
                url=str(item.get("url") or ""),
                snippet=str(item.get("content") or ""),
                score=float(item["score"]) if item.get("score") is not None else None,
                published=str(item.get("published_date") or "") or None,
            )
        )
    return out


async def _search_with_provider(
    provider: str,
    query: str,
    count: int,
    *,
    allowed_domains: list[str] | None = None,
    blocked_domains: list[str] | None = None,
    recency_days: int | None = None,
) -> list[dict[str, str]]:
    pid = _normalize_provider_id(provider)
    api_key = _api_key_for_provider(pid)
    depth = _search_depth()

    if pid in ("duckduckgo", ""):
        try:
            results = await _search_duckduckgo(query, count)
        except ImportError as e:
            raise ImportError("install duckduckgo-search") from e
    elif pid == "brave":
        results = await _search_brave(query, count, api_key, recency_days=recency_days)
    elif pid == "serpapi":
        results = await _search_serpapi(query, count, api_key)
    elif pid == "tavily":
        results = await _search_tavily(
            query,
            count,
            api_key,
            allowed_domains=allowed_domains,
            blocked_domains=blocked_domains,
            recency_days=recency_days,
            search_depth=depth,
        )
    else:
        raise ValueError(f"unknown web_search provider: {pid}")

    return filter_results_by_domains(
        results,
        allowed_domains=allowed_domains,
        blocked_domains=blocked_domains,
    )


async def run_web_search(
    query: str,
    count: int | None = None,
    *,
    allowed_domains: list[str] | None = None,
    blocked_domains: list[str] | None = None,
    recency_days: int | None = None,
) -> tuple[str, list[dict[str, str]], list[str]]:
    q = (query or "").strip()
    if not q:
        raise ValueError("query is required")
    n = clamp_count(count, default=_default_count())
    default_allow, default_block = _default_domain_filters()
    allow = _merge_domain_lists(allowed_domains, default_allow)
    block = _merge_domain_lists(blocked_domains, default_block)

    cache_key = (
        f"{':'.join(_resolve_provider_chain())}:{n}:"
        f"a={','.join(allow)}:b={','.join(block)}:r={recency_days or 0}:"
        f"{normalize_cache_key(q)}"
    )
    cached = _SEARCH_CACHE.get(cache_key, _cache_ttl_seconds())
    if cached is not None:
        provider = _resolve_provider_chain()[0]
        return provider, cached, [provider]

    providers = _resolve_provider_chain()
    tried: list[str] = []
    last_error: Exception | None = None

    for provider in providers:
        tried.append(provider)
        try:
            results = await _search_with_provider(
                provider,
                q,
                n,
                allowed_domains=allow or None,
                blocked_domains=block or None,
                recency_days=recency_days,
            )
            if results:
                _SEARCH_CACHE.set(cache_key, results, _cache_ttl_seconds())
                return provider, results, tried
            logger.info("[web_search] %s returned 0 results for %r", provider, q[:80])
        except ImportError:
            raise
        except Exception as exc:
            last_error = exc
            logger.warning("[web_search] %s failed: %s", provider, exc)

    if last_error is not None:
        raise last_error
    return providers[-1], [], tried


async def web_search(
    query: str,
    count: int | None = None,
    num_results: int | None = None,
    allowed_domains: list[str] | None = None,
    blocked_domains: list[str] | None = None,
    recency_days: int | None = None,
) -> ToolResult:
    try:
        n = count if count is not None else num_results
        provider, results, tried = await run_web_search(
            query,
            n,
            allowed_domains=allowed_domains,
            blocked_domains=blocked_domains,
            recency_days=recency_days,
        )
        fetch_suggestions = suggest_fetch_urls(results, max_urls=3)
        payload: dict[str, Any] = {
            "query": query,
            "provider": provider,
            "providers_tried": tried,
            "results": results,
            "count": len(results),
            "fetch_suggestions": fetch_suggestions,
        }
        if allowed_domains:
            payload["allowed_domains"] = allowed_domains
        if blocked_domains:
            payload["blocked_domains"] = blocked_domains
        if recency_days is not None:
            payload["recency_days"] = recency_days
        payload["text"] = format_web_search_text(
            query=str(query or ""),
            provider=provider,
            results=results,
        )
        if not results:
            payload["text"] += (
                "\n\n提示：可缩短 query、放宽域名过滤、设置 recency_days，"
                "或检查 tools.web_search.fallback_providers。"
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
        "Search the live web for current facts, news, prices, and docs not in local files. "
        "Use short keyword queries (2–12 words), not full sentences. "
        "Returns title, url, snippet, domain. "
        "Then call web_fetch on fetch_suggestions (1–3 URLs). "
        "Optional allowed_domains/blocked_domains (Anthropic/OpenAI-style). "
        "Not for project docs (knowledge_search) or known URLs (web_fetch)."
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
