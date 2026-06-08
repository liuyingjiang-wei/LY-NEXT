from __future__ import annotations

from typing import Any

import httpx

from ly_next.core.config import config
from ly_next.tools.base import ToolResult, tool
from ly_next.tools.http_fetch import _url_allowed
from ly_next.tools.web_fetch_local import fetch_local

WEB_FETCH_PROVIDERS = ("trafilatura", "jina", "tavily", "firecrawl", "local")


def _cfg() -> dict[str, Any]:
    tools = config.get("tools") or {}
    if not isinstance(tools, dict):
        return {}
    wf = tools.get("web_fetch") or {}
    return wf if isinstance(wf, dict) else {}


def _settings() -> dict[str, Any]:
    wf = _cfg()
    provider = str(wf.get("provider") or "jina").strip().lower()
    output_format = str(wf.get("output_format") or "txt").strip().lower()
    if output_format not in ("txt", "markdown"):
        output_format = "txt"
    depth = str(wf.get("extract_depth") or "basic").strip().lower()
    if depth not in ("basic", "advanced"):
        depth = "basic"
    return {
        "provider": provider,
        "api_key": str(wf.get("api_key") or "").strip(),
        "base_url": str(wf.get("base_url") or "").strip().rstrip("/"),
        "timeout": max(5.0, min(float(wf.get("timeout_seconds") or 30), 120.0)),
        "default_max": max(500, min(int(wf.get("default_max_length") or 8000), 200_000)),
        "max_bytes": max(50_000, min(int(wf.get("max_response_bytes") or 2_000_000), 10_000_000)),
        "user_agent": str(wf.get("user_agent") or "").strip(),
        "extract_depth": depth,
        "output_format": output_format,
        "favor_recall": wf.get("favor_recall", True) is not False,
        "include_tables": wf.get("include_tables", True) is not False,
        "jina_proxy": str(wf.get("jina_proxy") or "").strip(),
    }


def _clamp_chars(n: int, ceiling: int = 200_000) -> int:
    return max(500, min(int(n), ceiling))


def _truncate(text: str, max_length: int) -> tuple[str, bool]:
    if len(text) <= max_length:
        return text, False
    return text[:max_length] + f"\n\n... [truncated, {len(text)} chars total]", True


async def _http_json(
    method: str,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    json_body: dict[str, Any] | None = None,
    timeout: float,
) -> dict[str, Any]:
    async with httpx.AsyncClient(
        follow_redirects=True,
        max_redirects=5,
        timeout=httpx.Timeout(timeout),
        trust_env=False,
    ) as client:
        r = await client.request(method, url, headers=headers, json=json_body)
        r.raise_for_status()
        data = r.json()
    return data if isinstance(data, dict) else {}


async def _fetch_jina(
    url: str, api_key: str, timeout: float, jina_proxy: str = ""
) -> tuple[str, str, str]:
    headers = {"Accept": "text/markdown", "X-Return-Format": "markdown"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    if jina_proxy:
        headers["X-Proxy"] = jina_proxy
    async with httpx.AsyncClient(
        follow_redirects=True,
        max_redirects=5,
        timeout=httpx.Timeout(timeout),
        trust_env=False,
    ) as client:
        r = await client.get(f"https://r.jina.ai/{url}", headers=headers)
        r.raise_for_status()
        text = (r.text or "").strip()
    if not text:
        raise ValueError("Empty response from reader service")
    return url, text, "markdown"


async def _fetch_tavily(
    url: str, api_key: str, timeout: float, extract_depth: str
) -> tuple[str, str, str]:
    if not api_key:
        raise ValueError("tools.web_fetch.api_key is required for tavily")
    payload: dict[str, Any] = {
        "urls": url,
        "format": "markdown",
        "extract_depth": extract_depth,
        "timeout": min(max(timeout, 1.0), 60.0),
    }
    data = await _http_json(
        "POST",
        "https://api.tavily.com/extract",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json_body=payload,
        timeout=timeout + 5,
    )
    results = data.get("results") or []
    if not results or not isinstance(results[0], dict):
        failed = data.get("failed_results") or []
        err = ""
        if failed and isinstance(failed[0], dict):
            err = str(failed[0].get("error") or "")
        raise ValueError(err or "Tavily extract returned no content")
    item = results[0]
    text = str(item.get("raw_content") or "").strip()
    if not text:
        raise ValueError("Tavily extract returned empty content")
    return str(item.get("url") or url), text, "markdown"


async def _fetch_firecrawl(
    url: str, api_key: str, base_url: str, timeout: float
) -> tuple[str, str, str]:
    if not api_key:
        raise ValueError("tools.web_fetch.api_key is required for firecrawl")
    root = base_url or "https://api.firecrawl.dev/v2"
    data = await _http_json(
        "POST",
        f"{root}/scrape",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json_body={"url": url, "formats": ["markdown"], "onlyMainContent": True},
        timeout=timeout + 10,
    )
    if not data.get("success", True):
        raise ValueError(str(data.get("error") or "Firecrawl scrape failed"))
    inner = data.get("data") if isinstance(data.get("data"), dict) else {}
    text = str(inner.get("markdown") or "").strip()
    if not text:
        raise ValueError("Firecrawl returned empty markdown")
    return url, text, "markdown"


async def _dispatch(url: str, opts: dict[str, Any]) -> tuple[str, str, str]:
    provider = opts["provider"]
    if provider in ("trafilatura", "local", "html"):
        return await fetch_local(
            url,
            timeout=opts["timeout"],
            max_bytes=opts["max_bytes"],
            user_agent=opts["user_agent"],
            output_format=opts["output_format"],
            favor_recall=opts["favor_recall"],
            include_tables=opts["include_tables"],
        )
    if provider in ("jina", "jina_reader", "reader"):
        return await _fetch_jina(url, opts["api_key"], opts["timeout"], opts["jina_proxy"])
    if provider == "tavily":
        return await _fetch_tavily(url, opts["api_key"], opts["timeout"], opts["extract_depth"])
    if provider == "firecrawl":
        return await _fetch_firecrawl(url, opts["api_key"], opts["base_url"], opts["timeout"])
    raise ValueError(
        f"Unknown web_fetch provider: {provider}. Choose one of: {', '.join(WEB_FETCH_PROVIDERS)}"
    )


async def web_fetch(url: str, max_length: int | None = None) -> ToolResult:
    raw_url = (url or "").strip()
    if not raw_url.startswith(("http://", "https://")):
        return ToolResult(success=False, error="URL must start with http:// or https://")

    ok, err = _url_allowed(raw_url)
    if not ok:
        return ToolResult(success=False, error=err)

    opts = _settings()
    cap = _clamp_chars(max_length if max_length is not None else opts["default_max"])

    try:
        final_url, content, fmt = await _dispatch(raw_url, opts)
        text, truncated = _truncate(content, cap)
        return ToolResult(
            success=True,
            result={
                "url": raw_url,
                "final_url": final_url,
                "provider": opts["provider"],
                "content": text,
                "length": len(text),
                "truncated": truncated,
                "format": fmt,
            },
        )
    except httpx.TimeoutException:
        return ToolResult(success=False, error=f"Request timed out: {raw_url}")
    except httpx.HTTPStatusError as e:
        code = e.response.status_code if e.response is not None else "?"
        return ToolResult(success=False, error=f"HTTP {code}")
    except ValueError as e:
        return ToolResult(success=False, error=str(e))
    except Exception as e:
        return ToolResult(success=False, error=f"{type(e).__name__}: {e}")


web_fetch_tool = tool(
    name="web_fetch",
    description=(
        "Fetch a URL and return clean page text (markdown when supported). "
        "Use after web_search to read full articles. Respects SSRF allowlist."
    ),
    category="network",
    parameters={
        "type": "object",
        "required": ["url"],
        "properties": {
            "url": {"type": "string", "description": "HTTP(S) URL."},
            "max_length": {
                "type": "integer",
                "description": "Max characters returned; truncates.",
            },
        },
    },
)(web_fetch)
