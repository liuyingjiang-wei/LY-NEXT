"""Application-wide dependency container for LY-NEXT."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from ly_next.core.config import Config
from ly_next.core.config import config as default_config
from ly_next.tools.registry import ToolRegistry, get_tool_registry

if TYPE_CHECKING:
    from ly_next.core.plugin.registry import PluginRegistry


@dataclass
class AppContext:
    """Shared runtime context; prefer injecting this over global singletons."""

    config: Config
    tool_registry: ToolRegistry
    plugin_registry: PluginRegistry | None = None
    extras: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def create(
        cls,
        *,
        config: Config | None = None,
        tool_registry: ToolRegistry | None = None,
    ) -> AppContext:
        cfg = config or default_config
        registry = tool_registry or get_tool_registry()
        return cls(config=cfg, tool_registry=registry)

    def set_plugin_registry(self, plugin_registry: PluginRegistry) -> None:
        self.plugin_registry = plugin_registry


_global_ctx: AppContext | None = None


def get_app_context() -> AppContext:
    global _global_ctx
    if _global_ctx is None:
        _global_ctx = AppContext.create()
    return _global_ctx


def set_app_context(ctx: AppContext) -> None:
    global _global_ctx
    _global_ctx = ctx
