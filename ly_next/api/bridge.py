"""Realtime channel bridge for adapter integrations."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from ly_next.api.websocket import get_ws_manager

SUPPORTED_CHANNELS = {
    "messages",
    "device",
    "stdin",
    "ComWeChat",
    "GSUIDCore",
    "OneBotv11",
    "OPQBot",
}

_device_sessions: dict[str, dict[str, Any]] = {}


def is_supported_channel(channel: str) -> bool:
    return channel in SUPPORTED_CHANNELS


def update_device_session(device_id: str, **fields: Any) -> dict[str, Any]:
    now = datetime.now().isoformat()
    session = _device_sessions.get(device_id, {"device_id": device_id, "created_at": now})
    session.update(fields)
    session["updated_at"] = now
    _device_sessions[device_id] = session
    return session


def get_device_session(device_id: str) -> dict[str, Any] | None:
    return _device_sessions.get(device_id)


def list_device_sessions() -> list[dict[str, Any]]:
    return sorted(_device_sessions.values(), key=lambda x: x.get("updated_at", ""), reverse=True)


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
