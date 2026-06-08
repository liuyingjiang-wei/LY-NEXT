"""Built-in bridge registration removed; install qq_onebot / telegram_bot under plugins/local/."""

from __future__ import annotations

from ly_next.core.app_context import AppContext
from ly_next.core.plugin.bridge_registry import BridgeRegistry
from ly_next.core.plugin.protocol import LyNextPlugin


class BridgePlugin(LyNextPlugin):
    name = "ly-next-bridges"
    version = "1.0.0"
    description = "Deprecated stub; messaging bridges load from plugins/"

    def register_bridges(self, bridge_registry: BridgeRegistry, ctx: AppContext) -> None:
        return None
