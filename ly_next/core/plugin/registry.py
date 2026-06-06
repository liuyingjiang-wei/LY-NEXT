"""Loaded plugin instances and lifecycle coordination."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ly_next.core.logger import get_logger
from ly_next.core.plugin.bridge_registry import BridgeRegistry

if TYPE_CHECKING:
    from fastapi import FastAPI

    from ly_next.core.app_context import AppContext
    from ly_next.core.plugin.protocol import LyNextPlugin

logger = get_logger(__name__)


class PluginRegistry:
    def __init__(self) -> None:
        self._plugins: list[LyNextPlugin] = []
        self._by_name: dict[str, LyNextPlugin] = {}
        self.bridge_registry = BridgeRegistry()
        self.api_registry: Any | None = None

    def register(self, plugin: LyNextPlugin, *, replace: bool = False) -> None:
        name = plugin.name
        if name in self._by_name and not replace:
            logger.warning("[PluginRegistry] skipping duplicate plugin: %s", name)
            return
        if name in self._by_name:
            old = self._by_name[name]
            self._plugins = [p for p in self._plugins if p is not old]
        self._plugins.append(plugin)
        self._by_name[name] = plugin
        logger.debug("[PluginRegistry] registered plugin: %s", name)

    def get(self, name: str) -> LyNextPlugin | None:
        return self._by_name.get(name)

    def list_plugins(self) -> list[LyNextPlugin]:
        return list(self._plugins)

    def list_info(self) -> list[dict[str, Any]]:
        return [p.info() for p in self._plugins]

    async def startup(self, app: FastAPI, ctx: AppContext) -> None:
        for plugin in self._plugins:
            try:
                await plugin.on_startup(app, ctx)
            except Exception as e:
                logger.error(
                    "[PluginRegistry] on_startup failed for %s: %s",
                    plugin.name,
                    e,
                    exc_info=True,
                )
                raise

    async def shutdown(self, app: FastAPI, ctx: AppContext) -> None:
        for plugin in reversed(self._plugins):
            try:
                await plugin.on_shutdown(app, ctx)
            except Exception as e:
                logger.warning(
                    "[PluginRegistry] on_shutdown failed for %s: %s",
                    plugin.name,
                    e,
                )
