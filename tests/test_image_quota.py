import pytest

from ly_next.tools import image_quota


@pytest.mark.asyncio
async def test_release_quota_after_consume(monkeypatch):
    store: dict[str, int] = {}

    async def fake_incr(key: str, amount: int = 1) -> int:
        store[key] = store.get(key, 0) + amount
        return store[key]

    async def fake_get(key: str):
        return store.get(key)

    async def fake_set(key: str, val, ttl: int = 0):
        store[key] = int(val) if isinstance(val, int) else 1

    monkeypatch.setattr(image_quota.cache, "incr", fake_incr)
    monkeypatch.setattr(image_quota.cache, "get", fake_get)
    monkeypatch.setattr(image_quota.cache, "set", fake_set)
    monkeypatch.setattr(image_quota, "daily_limit", lambda: 5)

    allowed, _ = await image_quota.consume_quota("u1")
    assert allowed is True
    await image_quota.release_quota("u1")
    remaining = await image_quota.get_remaining_quota("u1")
    assert remaining == 5


@pytest.mark.asyncio
async def test_consume_fails_when_incr_returns_zero(monkeypatch):
    async def bad_incr(key: str, amount: int = 1) -> int:
        return 0

    monkeypatch.setattr(image_quota.cache, "incr", bad_incr)
    monkeypatch.setattr(image_quota, "daily_limit", lambda: 5)

    allowed, remaining = await image_quota.consume_quota("u2")
    assert allowed is False
    assert remaining == 0
