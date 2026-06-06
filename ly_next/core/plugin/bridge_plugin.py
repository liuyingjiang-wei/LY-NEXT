"""Registers built-in message bridges."""

from __future__ import annotations

from ly_next.bridge.onebot11.plugin import OneBotBridge
from ly_next.core.app_context import AppContext
from ly_next.core.plugin.bridge_registry import BridgeRegistry
from ly_next.core.plugin.protocol import LyNextPlugin


class BridgePlugin(LyNextPlugin):
    name = "ly-next-bridges"
    version = "1.0.0"
    description = "Built-in messaging bridges (OneBot11, etc.)"

    def register_bridges(self, bridge_registry: BridgeRegistry, ctx: AppContext) -> None:
        bridge_registry.register(OneBotBridge())
