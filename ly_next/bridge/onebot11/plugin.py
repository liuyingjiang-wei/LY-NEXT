"""OneBot v11 bridge registered via the plugin system."""

from __future__ import annotations

from typing import Any

from ly_next.bridge.onebot11.config import get_onebot11_settings
from ly_next.bridge.onebot11.router import attach_onebot_routes
from ly_next.core.config import config


class OneBotBridge:
    name = "onebot11"

    @property
    def enabled(self) -> bool:
        return bool(config.get("bridge.onebot11.enabled", False))

    def attach_routes(self, router: Any, app: Any) -> list[str]:
        if not self.enabled:
            return []
        _ = app
        settings = get_onebot11_settings()
        if not settings.enabled:
            return []
        return attach_onebot_routes(router)
