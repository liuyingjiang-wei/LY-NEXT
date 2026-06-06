"""Image search backends (multi-vendor)."""

from __future__ import annotations

import asyncio
import importlib
from typing import Any

import httpx

from ly_next.core.config import config
from ly_next.core.logger import get_logger

logger = get_logger(__name__)

SEARCH_PROVIDER_IDS = (
    "tavily",
    "bing",
    "unsplash",
    "pexels",
    "pixabay",
    "serpapi",
    "brave",
    "duckduckgo",
)


def image_cfg() -> dict[str, Any]:
    raw = config.get("tools.image") or {}
    return raw if isinstance(raw, dict) else {}


def _tavily_api_key(cfg: dict[str, Any]) -> str:
    key = str(cfg.get("tavily_api_key") or "").strip()
    if key:
        return key
    ws = config.get("tools.web_search") or {}
    if isinstance(ws, dict):
        k = str(ws.get("api_key") or "").strip()
        if k:
            return k
    return ""


def _collect_tavily_image_urls(data: dict[str, Any], *, limit: int) -> list[str]:
    urls: list[str] = []
    seen: set[str] = set()

    def add(u: Any) -> None:
        if not isinstance(u, str) or not u.startswith("http") or u in seen:
            return
        seen.add(u)
        urls.append(u)

    for u in data.get("images") or []:
        if isinstance(u, str):
            add(u)
        elif isinstance(u, dict):
            add(u.get("url"))
        if len(urls) >= limit:
            return urls[:limit]

    for item in data.get("results") or []:
        if not isinstance(item, dict):
            continue
        for u in item.get("images") or []:
            if isinstance(u, str):
                add(u)
            elif isinstance(u, dict):
                add(u.get("url"))
            if len(urls) >= limit:
                return urls[:limit]
    return urls[:limit]


async def search_tavily(query: str, count: int, api_key: str) -> list[str]:
    if not api_key:
        raise ValueError("未配置 tavily_api_key（可在 tools.image 或 tools.web_search.api_key 填写）")
    payload = {
        "api_key": api_key,
        "query": query,
        "search_depth": "basic",
        "max_results": max(3, min(int(count), 10)),
        "include_images": True,
    }
    async with httpx.AsyncClient(timeout=45.0) as client:
        r = await client.post("https://api.tavily.com/search", json=payload)
        r.raise_for_status()
        data = r.json()
    if not isinstance(data, dict):
        raise RuntimeError("Tavily 响应格式异常")
    return _collect_tavily_image_urls(data, limit=count)


async def search_bing(query: str, count: int, api_key: str) -> list[str]:
    if not api_key:
        raise ValueError("未配置 bing_search_api_key")
    url = "https://api.bing.microsoft.com/v7.0/images/search"
    headers = {"Ocp-Apim-Subscription-Key": api_key}
    params = {"q": query, "count": str(count), "safeSearch": "Moderate"}
    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.get(url, headers=headers, params=params)
        r.raise_for_status()
        data = r.json()
    urls: list[str] = []
    for item in (data.get("value") or [])[:count]:
        if not isinstance(item, dict):
            continue
        u = item.get("contentUrl") or item.get("thumbnailUrl")
        if isinstance(u, str) and u.startswith("http"):
            urls.append(u)
    return urls


async def search_unsplash(query: str, count: int, access_key: str) -> list[str]:
    if not access_key:
        raise ValueError("未配置 unsplash_access_key")
    url = "https://api.unsplash.com/search/photos"
    params = {"query": query, "per_page": str(count)}
    headers = {"Authorization": f"Client-ID {access_key}"}
    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.get(url, headers=headers, params=params)
        r.raise_for_status()
        data = r.json()
    urls: list[str] = []
    for item in (data.get("results") or [])[:count]:
        u = (item.get("urls") or {}) if isinstance(item, dict) else {}
        link = u.get("regular") or u.get("small") or u.get("full")
        if isinstance(link, str) and link.startswith("http"):
            urls.append(link)
    return urls


async def search_pexels(query: str, count: int, api_key: str) -> list[str]:
    if not api_key:
        raise ValueError("未配置 pexels_api_key")
    url = "https://api.pexels.com/v1/search"
    headers = {"Authorization": api_key}
    params = {"query": query, "per_page": str(count)}
    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.get(url, headers=headers, params=params)
        r.raise_for_status()
        data = r.json()
    urls: list[str] = []
    for item in (data.get("photos") or [])[:count]:
        if not isinstance(item, dict):
            continue
        src = item.get("src") or {}
        u = src.get("large") or src.get("medium") or src.get("original")
        if isinstance(u, str) and u.startswith("http"):
            urls.append(u)
    return urls


async def search_pixabay(query: str, count: int, api_key: str) -> list[str]:
    if not api_key:
        raise ValueError("未配置 pixabay_api_key")
    url = "https://pixabay.com/api/"
    params = {"key": api_key, "q": query, "image_type": "photo", "per_page": str(count)}
    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.get(url, params=params)
        r.raise_for_status()
        data = r.json()
    urls: list[str] = []
    for item in (data.get("hits") or [])[:count]:
        if isinstance(item, dict):
            u = item.get("largeImageURL") or item.get("webformatURL")
            if isinstance(u, str) and u.startswith("http"):
                urls.append(u)
    return urls


async def search_serpapi(query: str, count: int, api_key: str) -> list[str]:
    if not api_key:
        raise ValueError("未配置 serpapi_api_key")
    url = "https://serpapi.com/search.json"
    params = {"engine": "google_images", "q": query, "api_key": api_key, "num": str(count)}
    async with httpx.AsyncClient(timeout=45.0) as client:
        r = await client.get(url, params=params)
        r.raise_for_status()
        data = r.json()
    urls: list[str] = []
    for item in (data.get("images_results") or [])[:count]:
        if isinstance(item, dict):
            u = item.get("original") or item.get("thumbnail")
            if isinstance(u, str) and u.startswith("http"):
                urls.append(u)
    return urls


async def search_brave(query: str, count: int, api_key: str) -> list[str]:
    if not api_key:
        raise ValueError("未配置 brave_search_api_key")
    url = "https://api.search.brave.com/res/v1/images/search"
    headers = {"Accept": "application/json", "X-Subscription-Token": api_key}
    params = {"q": query, "count": str(count)}
    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.get(url, headers=headers, params=params)
        r.raise_for_status()
        data = r.json()
    urls: list[str] = []
    for item in (data.get("results") or [])[:count]:
        if isinstance(item, dict):
            u = item.get("url")
            if not isinstance(u, str) or not u.startswith("http"):
                thumb = item.get("thumbnail")
                if isinstance(thumb, dict):
                    u = thumb.get("src")
                elif isinstance(thumb, str):
                    u = thumb
            if isinstance(u, str) and u.startswith("http"):
                urls.append(u)
    return urls


async def search_duckduckgo(query: str, count: int) -> list[str]:
    try:
        from duckduckgo_search import AsyncDDGS  # type: ignore

        urls: list[str] = []
        async with AsyncDDGS() as ddgs:
            async for r in ddgs.aimages(query, max_results=count):
                u = r.get("image") or r.get("url") or r.get("thumbnail")
                if isinstance(u, str) and u.startswith("http"):
                    urls.append(u)
        return urls[:count]
    except ImportError:
        module = importlib.import_module("duckduckgo_search")
        ddgs_cls = module.DDGS

        def _sync() -> list[str]:
            out: list[str] = []
            with ddgs_cls() as ddgs:
                for r in ddgs.images(query, max_results=count):
                    u = r.get("image") or r.get("url") or r.get("thumbnail")
                    if isinstance(u, str) and u.startswith("http"):
                        out.append(u)
            return out[:count]

        return await asyncio.to_thread(_sync)


async def search_with_provider(query: str, *, count: int = 3, provider: str | None = None) -> list[str]:
    cfg = image_cfg()
    pid = (provider or str(cfg.get("search_provider") or "bing")).strip().lower()
    query = (query or "").strip()
    if not query:
        return []

    async def _try(fn, *args) -> list[str]:
        try:
            return await fn(query, count, *args)
        except Exception as e:
            logger.warning("[search_images] %s failed: %s", pid, e)
            return []

    if pid == "tavily":
        urls = await _try(search_tavily, _tavily_api_key(cfg))
        if urls:
            return urls
    elif pid == "bing":
        urls = await _try(search_bing, str(cfg.get("bing_search_api_key") or "").strip())
        if urls:
            return urls
    elif pid == "unsplash":
        urls = await _try(search_unsplash, str(cfg.get("unsplash_access_key") or "").strip())
        if urls:
            return urls
    elif pid == "pexels":
        urls = await _try(search_pexels, str(cfg.get("pexels_api_key") or "").strip())
        if urls:
            return urls
    elif pid == "pixabay":
        urls = await _try(search_pixabay, str(cfg.get("pixabay_api_key") or "").strip())
        if urls:
            return urls
    elif pid == "serpapi":
        urls = await _try(search_serpapi, str(cfg.get("serpapi_api_key") or "").strip())
        if urls:
            return urls
    elif pid == "brave":
        key = str(cfg.get("brave_search_api_key") or cfg.get("brave_api_key") or "").strip()
        urls = await _try(search_brave, key)
        if urls:
            return urls
    elif pid == "duckduckgo":
        return await search_duckduckgo(query, count)

    return await search_duckduckgo(query, count)
