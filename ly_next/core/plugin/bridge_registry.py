"""Registry for message bridge plugins (OneBot, web, etc.)."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class MessageBridge(Protocol):
    """Contract for inbound/outbound messaging bridges."""

    name: str

    @property
    def enabled(self) -> bool: ...

    def attach_routes(self, router: Any, app: Any) -> list[str]: ...


class BridgeRegistry:
    def __init__(self) -> None:
        self._bridges: dict[str, MessageBridge] = {}

    def register(self, bridge: MessageBridge) -> None:
        self._bridges[bridge.name] = bridge

    def get(self, name: str) -> MessageBridge | None:
        return self._bridges.get(name)

    def list_bridges(self) -> list[MessageBridge]:
        return list(self._bridges.values())

    def enabled(self) -> list[MessageBridge]:
        return [b for b in self._bridges.values() if b.enabled]

    def list_info(self) -> list[dict[str, str | bool]]:
        return [{"name": b.name, "enabled": bool(b.enabled)} for b in self._bridges.values()]
