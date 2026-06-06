from __future__ import annotations

import hashlib
from datetime import datetime, timezone

from ly_next.core.cache import cache
from ly_next.core.config import config
from ly_next.core.logger import get_logger

logger = get_logger(__name__)


def image_cfg() -> dict:
    raw = config.get("tools.image") or {}
    return raw if isinstance(raw, dict) else {}


def _image_cfg() -> dict:
    return image_cfg()


def daily_limit() -> int:
    return max(0, int(_image_cfg().get("daily_limit", 20) or 20))


def cache_ttl() -> int:
    return max(60, int(_image_cfg().get("cache_ttl", 3600) or 3600))


def _day_key() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d")


def quota_key(user_key: str) -> str:
    return f"ly:image:quota:{user_key}:{_day_key()}"


def cache_key_for_prompt(prompt: str, provider: str) -> str:
    digest = hashlib.sha256(f"{provider}:{prompt.strip()}".encode()).hexdigest()[:32]
    return f"ly:image:cache:{digest}"


async def get_remaining_quota(user_key: str) -> int:
    limit = daily_limit()
    if limit <= 0:
        return 0
    key = quota_key(user_key)
    try:
        used = await cache.get(key)
        if used is None:
            return limit
        return max(0, limit - int(used))
    except Exception as e:
        logger.warning("[image_quota] get failed: %s", e)
        return limit


async def consume_quota(user_key: str) -> tuple[bool, int]:
    """Returns (allowed, remaining_after)."""
    limit = daily_limit()
    if limit <= 0:
        return False, 0
    key = quota_key(user_key)
    try:
        used = await cache.incr(key)
        if used <= 0:
            logger.warning("[image_quota] incr returned %s — treating as unavailable", used)
            return False, 0
        if used == 1:
            # expire at end of UTC day (~24h TTL is fine)
            await cache.set(key, 1, ttl=86400)
        if used > limit:
            await release_quota(user_key)
            return False, 0
        return True, max(0, limit - used)
    except Exception as e:
        logger.warning("[image_quota] consume failed: %s", e)
        return False, 0


async def release_quota(user_key: str) -> None:
    """Refund one daily generation slot after a failed attempt post-consume."""
    limit = daily_limit()
    if limit <= 0:
        return
    key = quota_key(user_key)
    try:
        used = await cache.get(key)
        if used is None:
            return
        n = int(used)
        if n > 0:
            await cache.incr(key, amount=-1)
    except Exception as e:
        logger.warning("[image_quota] release failed: %s", e)


async def get_cached_image_url(prompt: str, provider: str) -> str | None:
    key = cache_key_for_prompt(prompt, provider)
    try:
        val = await cache.get(key)
        if isinstance(val, dict):
            url = val.get("image_url")
            return str(url) if url else None
        if isinstance(val, str) and val.startswith("http"):
            return val
    except Exception as e:
        logger.debug("[image_quota] cache get: %s", e)
    return None


async def set_cached_image_url(prompt: str, provider: str, image_url: str) -> None:
    key = cache_key_for_prompt(prompt, provider)
    try:
        await cache.set(key, {"image_url": image_url}, ttl=cache_ttl())
    except Exception as e:
        logger.debug("[image_quota] cache set: %s", e)
