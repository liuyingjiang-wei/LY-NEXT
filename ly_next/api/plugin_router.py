from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import FastAPI

from ly_next.api.base import BaseAPI
from ly_next.core.logger import get_logger

logger = get_logger(__name__)


class PluginRouterAPI(BaseAPI):
    def __init__(
        self,
        *,
        name: str,
        description: str,
        router: Any,
        enabled: Callable[[], bool],
        priority: int = 100,
    ) -> None:
        super().__init__(name=name, description=description, priority=priority, enabled=True)
        self._router = router
        self._enabled_check = enabled

    async def startup(self, app: FastAPI) -> None:
        if not self._enabled_check():
            logger.info("[PluginRouterAPI] %s skipped (disabled in config)", self.name)
            return
        await super().startup(app)

    def register_routes(self, app: FastAPI) -> None:
        app.include_router(self._router, prefix="/api")
