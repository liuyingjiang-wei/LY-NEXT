"""Plugin protocol for extending LY-NEXT at runtime."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ly_next.core.plugin.constants import is_builtin_plugin_name

if TYPE_CHECKING:
    from fastapi import FastAPI

    from ly_next.agent.factory import AgentFactory
    from ly_next.api.base import APIRegistry
    from ly_next.core.app_context import AppContext
    from ly_next.core.plugin.bridge_registry import BridgeRegistry
    from ly_next.models.factory import LLMFactory
    from ly_next.tools.registry import ToolRegistry


class LyNextPlugin:
    """Base plugin; override only the hooks you need."""

    name: str = "unnamed-plugin"
    version: str = "0.0.0"
    description: str = ""

    def register_tools(self, registry: ToolRegistry, ctx: AppContext) -> None:
        return None

    def register_agents(self, factory: AgentFactory, ctx: AppContext) -> None:
        return None

    def register_llm_providers(self, factory: LLMFactory, ctx: AppContext) -> None:
        return None

    def register_apis(self, api_registry: APIRegistry, ctx: AppContext) -> None:
        return None

    def register_bridges(self, bridge_registry: BridgeRegistry, ctx: AppContext) -> None:
        return None

    async def on_startup(self, app: FastAPI, ctx: AppContext) -> None:
        return None

    async def on_shutdown(self, app: FastAPI, ctx: AppContext) -> None:
        return None

    def info(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "version": self.version,
            "description": self.description or "",
            "class": f"{type(self).__module__}.{type(self).__qualname__}",
            "builtin": is_builtin_plugin_name(self.name),
        }
