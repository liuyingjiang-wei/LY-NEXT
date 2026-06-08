from __future__ import annotations

import time
from typing import Any, Generic, TypeVar

MAX_SEARCH_COUNT = 10
DEFAULT_SEARCH_COUNT = 5
DEFAULT_CACHE_MAX_ENTRIES = 100

T = TypeVar("T")


class WebCache(Generic[T]):
    def __init__(self, *, max_entries: int = DEFAULT_CACHE_MAX_ENTRIES) -> None:
        self._data: dict[str, tuple[float, T]] = {}
        self._max_entries = max(1, max_entries)

    def get(self, key: str, ttl_seconds: float) -> T | None:
        if ttl_seconds <= 0:
            return None
        entry = self._data.get(key)
        if not entry:
            return None
        ts, value = entry
        if time.monotonic() - ts > ttl_seconds:
            self._data.pop(key, None)
            return None
        return value

    def set(self, key: str, value: T, ttl_seconds: float) -> None:
        if ttl_seconds <= 0:
            return
        if len(self._data) >= self._max_entries:
            oldest = next(iter(self._data), None)
            if oldest is not None:
                self._data.pop(oldest, None)
        self._data[key] = (time.monotonic(), value)


def normalize_cache_key(value: str) -> str:
    return (value or "").strip().lower()


def clamp_count(value: Any, *, default: int, maximum: int = MAX_SEARCH_COUNT) -> int:
    try:
        n = int(value)
    except (TypeError, ValueError):
        n = default
    return max(1, min(n, maximum))


def normalize_search_hit(*, title: str, url: str, snippet: str) -> dict[str, str]:
    return {
        "title": (title or "").strip(),
        "url": (url or "").strip(),
        "snippet": (snippet or "").strip(),
    }


def truncate_text(text: str, max_chars: int) -> tuple[str, bool]:
    if max_chars <= 0 or len(text) <= max_chars:
        return text, False
    return text[:max_chars] + f"\n... [truncated, {len(text)} chars]", True
