"""Agent HTTP fetch (httpx) with basic SSRF guards."""

from __future__ import annotations

import ipaddress
from typing import Any
from urllib.parse import urlparse

import httpx

from ly_next.tools.base import ToolResult, tool

_BLOCKED_HOSTNAMES = frozenset(
    {
        "localhost",
        "metadata",
        "metadata.google.internal",
        "kubernetes.default",
        "kubernetes.default.svc",
    }
)


def _host_blocked_reason(hostname: str) -> str | None:
    h = (hostname or "").strip().lower()
    if not h:
        return "missing host"
    if h in _BLOCKED_HOSTNAMES or h.endswith(".local"):
        return f"hostname not allowed: {h}"
    if h == "169.254.169.254" or h.startswith("169.254."):
        return "link-local / metadata-style host not allowed"
    try:
        ip = ipaddress.ip_address(h)
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            return f"IP range not allowed: {ip}"
    except ValueError:
        pass
    return None


def _url_allowed(url: str) -> tuple[bool, str]:
    try:
        p = urlparse(url)
    except Exception as e:
        return False, str(e)
    if p.scheme not in ("http", "https"):
        return False, "only http and https are allowed"
    if not p.hostname:
        return False, "invalid URL (no host)"
    reason = _host_blocked_reason(p.hostname)
    if reason:
        return False, reason
    if p.username is not None and p.username != "":
        return False, "userinfo in URL is not allowed"
    return True, ""


_FORBIDDEN_REQUEST_HEADER_NAMES = frozenset(
    {
        "host",
        "content-length",
        "transfer-encoding",
        "connection",
        "expect",
        "upgrade",
        "te",
        "proxy-authorization",
        "proxy-connection",
    }
)


def _normalize_headers(raw: Any) -> dict[str, str]:
    if not raw or not isinstance(raw, dict):
        return {}
    out: dict[str, str] = {}
    for k, v in raw.items():
        if not isinstance(k, str) or not isinstance(v, str):
            continue
        ks = k.strip()
        if not ks:
            continue
        lower = ks.lower()
        if lower in _FORBIDDEN_REQUEST_HEADER_NAMES or lower.startswith(
            ("x-forwarded-", "x-real-ip", "forwarded")
        ):
            continue
        out[ks] = v
    return out


@tool(
    name="http_fetch",
    description=(
        "Perform an HTTP/HTTPS request and return status, final URL, response headers, and body text. "
        "Use for REST APIs, JSON endpoints, or fetching plain text/HTML. "
        "Private IPs, loopback, and cloud metadata hosts are blocked."
    ),
    category="network",
    parameters={
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "Absolute http(s) URL"},
            "method": {
                "type": "string",
                "description": "HTTP method",
                "enum": ["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
                "default": "GET",
            },
            "headers": {
                "type": "object",
                "description": "Optional string headers (e.g. Content-Type, Authorization)",
                "additionalProperties": {"type": "string"},
            },
            "body": {
                "type": "string",
                "description": "Raw request body (for POST/PUT/PATCH); ignored for GET/HEAD",
            },
            "timeout_seconds": {
                "type": "number",
                "description": "Request timeout in seconds",
                "default": 30,
            },
            "max_response_chars": {
                "type": "integer",
                "description": "Truncate response text after this many characters (max 500000)",
                "default": 120000,
            },
        },
        "required": ["url"],
    },
)
async def http_fetch(
    url: str,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    body: str | None = None,
    timeout_seconds: float = 30.0,
    max_response_chars: int = 120_000,
) -> ToolResult:
    ok, err = _url_allowed(url)
    if not ok:
        return ToolResult(success=False, error=err)

    m = (method or "GET").upper().strip()
    if m not in ("GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"):
        return ToolResult(success=False, error=f"unsupported method: {m}")

    cap = max(1024, min(int(max_response_chars), 500_000))
    to = max(1.0, min(float(timeout_seconds), 120.0))

    hdrs = _normalize_headers(headers)
    payload: str | None = None
    if m not in ("GET", "HEAD") and body is not None and body != "":
        payload = body

    try:
        async with httpx.AsyncClient(
            follow_redirects=True,
            max_redirects=8,
            timeout=httpx.Timeout(to),
            trust_env=False,
        ) as client:
            r = await client.request(m, url, headers=hdrs or None, content=payload)

        final = str(r.url)
        ok2, err2 = _url_allowed(final)
        if not ok2:
            return ToolResult(success=False, error=f"redirect blocked: {err2}")

        out_headers: dict[str, str] = {}
        for i, (hk, hv) in enumerate(r.headers.multi_items()):
            if i >= 48:
                break
            vs = str(hv)
            if len(vs) > 4000:
                vs = vs[:4000] + "…"
            out_headers[str(hk)] = vs

        text = ""
        if m != "HEAD":
            text = r.text
            if len(text) > cap:
                text = text[:cap] + f"\n… truncated ({len(r.text)} chars total)"

        return ToolResult(
            success=True,
            result={
                "status_code": r.status_code,
                "final_url": final,
                "headers": out_headers,
                "text": text,
                "text_length": len(r.text) if m != "HEAD" else 0,
            },
        )
    except httpx.HTTPError as e:
        return ToolResult(success=False, error=f"HTTP error: {e}")
    except Exception as e:
        return ToolResult(success=False, error=str(e))
