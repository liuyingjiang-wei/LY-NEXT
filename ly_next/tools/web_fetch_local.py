from __future__ import annotations

import asyncio

import httpx
import trafilatura

from ly_next.tools.http_fetch import _url_allowed

_DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)


def looks_like_html(body: str, content_type: str) -> bool:
    ct = (content_type or "").split(";")[0].strip().lower()
    if "html" in ct:
        return True
    if ct and ct not in ("", "application/octet-stream") and not ct.startswith("text/"):
        return False
    head = (body or "")[:512].lstrip().lower()
    return head.startswith(("<!doctype", "<html"))


def extract_html(
    html: str,
    url: str,
    *,
    output_format: str = "txt",
    favor_recall: bool = True,
    include_tables: bool = True,
) -> str:
    fmt = output_format if output_format in ("txt", "markdown", "xml") else "txt"
    return (
        trafilatura.extract(
            html,
            url=url,
            include_links=False,
            include_tables=include_tables,
            output_format=fmt,
            favor_recall=favor_recall,
            deduplicate=True,
        )
        or ""
    )


async def fetch_local(
    url: str,
    *,
    timeout: float,
    max_bytes: int,
    user_agent: str,
    output_format: str,
    favor_recall: bool,
    include_tables: bool,
) -> tuple[str, str, str]:
    ua = user_agent or _DEFAULT_UA
    async with httpx.AsyncClient(
        follow_redirects=True,
        max_redirects=8,
        timeout=httpx.Timeout(timeout),
        trust_env=False,
    ) as client:
        r = await client.get(
            url,
            headers={
                "User-Agent": ua,
                "Accept": "text/html,application/xhtml+xml,text/plain;q=0.9,*/*;q=0.8",
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            },
        )
        r.raise_for_status()
        final = str(r.url)
        ok, err = _url_allowed(final)
        if not ok:
            raise ValueError(f"redirect blocked: {err}")
        raw = r.content
        if len(raw) > max_bytes:
            raw = raw[:max_bytes]
        body = raw.decode(r.encoding or "utf-8", errors="replace")
        ct = r.headers.get("content-type", "")

    if looks_like_html(body, ct):
        content = await asyncio.to_thread(
            extract_html,
            body,
            final,
            output_format=output_format,
            favor_recall=favor_recall,
            include_tables=include_tables,
        )
        fmt = output_format if output_format in ("txt", "markdown") else "txt"
    else:
        content = body.strip()
        fmt = "text"

    if not content.strip():
        raise ValueError("No readable content extracted")
    return final, content, fmt
