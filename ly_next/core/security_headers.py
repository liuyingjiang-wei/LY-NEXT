"""Standard HTTP security response headers."""

from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from ly_next.core.http_security import (
    default_content_security_policy,
    headers_config,
    request_is_https,
)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        response = await call_next(request)
        cfg = headers_config()
        if not cfg.get("enabled", True):
            return response

        if cfg.get("content_type_options", True):
            response.headers.setdefault("X-Content-Type-Options", "nosniff")

        frame = str(cfg.get("frame_options") or "DENY").strip()
        if frame:
            response.headers.setdefault("X-Frame-Options", frame)

        referrer = str(cfg.get("referrer_policy") or "strict-origin-when-cross-origin").strip()
        if referrer:
            response.headers.setdefault("Referrer-Policy", referrer)

        response.headers.setdefault("X-XSS-Protection", "0")

        csp = str(cfg.get("content_security_policy") or "").strip()
        if csp == "default":
            csp = default_content_security_policy()
        if csp:
            response.headers.setdefault("Content-Security-Policy", csp)

        if cfg.get("hsts", True) and request_is_https(request):
            max_age = int(cfg.get("hsts_max_age") or 31_536_000)
            parts = [f"max-age={max_age}"]
            if cfg.get("hsts_include_subdomains", False):
                parts.append("includeSubDomains")
            response.headers.setdefault("Strict-Transport-Security", "; ".join(parts))

        return response
