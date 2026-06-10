"""Configurable HTTP rate limiting with Redis or in-memory storage."""

from __future__ import annotations

import time
from typing import Any

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from ly_next.core.http_security import (
    client_ip,
    limit_for_bucket,
    path_matches_any,
    rate_limit_bucket,
    rate_limit_config,
)
from ly_next.core.logger import get_logger

logger = get_logger(__name__)


class _MemoryStore:
    def __init__(self) -> None:
        self._hits: dict[str, tuple[int, float]] = {}

    def _prune(self, now: float) -> None:
        if len(self._hits) < 4096:
            return
        expired = [k for k, (_, exp) in self._hits.items() if exp <= now]
        for k in expired:
            self._hits.pop(k, None)

    async def hit(self, key: str, *, window_seconds: int) -> int:
        now = time.monotonic()
        self._prune(now)
        count, expires = self._hits.get(key, (0, now + window_seconds))
        if now >= expires:
            count = 0
            expires = now + window_seconds
        count += 1
        self._hits[key] = (count, expires)
        return count


class RateLimiter:
    def __init__(self) -> None:
        self._memory = _MemoryStore()

    def _storage_mode(self, request: Request) -> str:
        rl = rate_limit_config()
        mode = str(rl.get("storage") or "auto").strip().lower()
        if mode in ("memory", "redis"):
            return mode
        return "redis" if bool(getattr(request.app.state, "redis_available", False)) else "memory"

    async def _redis_hit(self, key: str, *, window_seconds: int) -> int | None:
        from ly_next.core.cache import cache

        client = cache._client
        if client is None:
            return None
        try:
            pipe = client.pipeline()
            pipe.incr(key)
            pipe.expire(key, window_seconds)
            count, _ = await pipe.execute()
            return int(count)
        except Exception as e:
            logger.debug("rate limit redis fallback: %s", e)
            return None

    async def allow(self, request: Request, *, bucket: str, ip: str) -> tuple[bool, int, int]:
        parsed = limit_for_bucket(bucket)
        if parsed is None:
            return True, 0, 0
        limit, window = parsed
        key = f"ly:rl:{bucket}:{ip}"
        if self._storage_mode(request) == "redis":
            count = await self._redis_hit(key, window_seconds=window)
            if count is None:
                count = await self._memory.hit(key, window_seconds=window)
        else:
            count = await self._memory.hit(key, window_seconds=window)
        return count <= limit, limit, window


_rate_limiter = RateLimiter()


def get_rate_limiter() -> RateLimiter:
    return _rate_limiter


def reset_rate_limiter() -> None:
    """Clear in-memory counters (tests and hot reload)."""
    _rate_limiter._memory = _MemoryStore()


class RateLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        rl = rate_limit_config()
        if not rl.get("enabled", True):
            return await call_next(request)

        path = request.url.path
        exempt = [str(p) for p in (rl.get("exempt_paths") or [])]
        if path_matches_any(path, exempt):
            return await call_next(request)

        trust_proxy = bool(rl.get("trust_proxy_headers", False))
        ip = client_ip(request, trust_proxy_headers=trust_proxy)
        bucket = rate_limit_bucket(request)
        allowed, limit, window = await get_rate_limiter().allow(request, bucket=bucket, ip=ip)
        if allowed:
            response = await call_next(request)
            if limit > 0:
                response.headers.setdefault("X-RateLimit-Limit", str(limit))
            return response

        retry_after = max(1, window)
        return JSONResponse(
            {"detail": "Too Many Requests"},
            status_code=429,
            headers={"Retry-After": str(retry_after)},
        )
