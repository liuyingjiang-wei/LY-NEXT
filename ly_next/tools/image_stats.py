from __future__ import annotations

import json
from typing import Any

from ly_next.core.cache import cache
from ly_next.core.logger import get_logger

logger = get_logger(__name__)

_STATS_KEY = "ly:image:tool_stats"


async def record_tool_call(tool_name: str, *, success: bool) -> None:
    try:
        raw = await cache.get(_STATS_KEY)
        stats: dict[str, Any] = raw if isinstance(raw, dict) else {}
        row = stats.setdefault(
            tool_name,
            {"calls": 0, "success": 0, "failure": 0},
        )
        row["calls"] = int(row.get("calls", 0)) + 1
        if success:
            row["success"] = int(row.get("success", 0)) + 1
        else:
            row["failure"] = int(row.get("failure", 0)) + 1
        await cache.set(_STATS_KEY, stats, ttl=86400 * 30)
    except Exception as e:
        logger.debug("[image_stats] record failed: %s", e)


async def get_tool_stats() -> dict[str, Any]:
    try:
        raw = await cache.get(_STATS_KEY)
        if isinstance(raw, dict):
            return raw
        if isinstance(raw, str):
            return json.loads(raw)
    except Exception as e:
        logger.debug("[image_stats] get failed: %s", e)
    return {}
