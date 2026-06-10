from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ly_next.core.rate_limit import RateLimiter, RateLimitMiddleware


class _FakeState:
    redis_available = False


@pytest.mark.asyncio
async def test_rate_limiter_blocks_after_limit():
    limiter = RateLimiter()
    request = MagicMock()
    request.app.state = _FakeState()

    cfg = {"default_limit": "3/minute", "storage": "memory"}
    with (
        patch("ly_next.core.http_security.rate_limit_config", return_value=cfg),
        patch("ly_next.core.rate_limit.rate_limit_config", return_value=cfg),
    ):
        for _ in range(3):
            allowed, _, _ = await limiter.allow(request, bucket="default", ip="1.2.3.4")
            assert allowed is True
        allowed, _, _ = await limiter.allow(request, bucket="default", ip="1.2.3.4")
        assert allowed is False


def test_rate_limit_middleware_returns_429():
    app = FastAPI()

    @app.get("/limited")
    async def limited():
        return {"ok": True}

    cfg = {
        "enabled": True,
        "default_limit": "2/minute",
        "storage": "memory",
        "exempt_paths": [],
    }
    with (
        patch("ly_next.core.http_security.rate_limit_config", return_value=cfg),
        patch("ly_next.core.rate_limit.rate_limit_config", return_value=cfg),
    ):
        app.add_middleware(RateLimitMiddleware)
        client = TestClient(app)
        assert client.get("/limited").status_code == 200
        assert client.get("/limited").status_code == 200
        r = client.get("/limited")
        assert r.status_code == 429
        assert r.json()["detail"] == "Too Many Requests"
