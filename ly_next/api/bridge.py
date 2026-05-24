from __future__ import annotations

from datetime import datetime
from typing import Any

from ly_next.api.websocket import get_ws_manager

SUPPORTED_CHANNELS = frozenset(
    {
        "stdin",
        "ComWeChat",
        "OPQBot",
        "OneBot11",
    }
)


def is_supported_channel(channel: str) -> bool:
    return channel in SUPPORTED_CHANNELS


async def emit_channel_event(channel: str, event_type: str, payload: dict[str, Any]) -> int:
    manager = get_ws_manager()
    return await manager.broadcast(
        {
            "type": event_type,
            "channel": channel,
            "timestamp": datetime.now().isoformat(),
            **payload,
        },
        group=channel,
    )
