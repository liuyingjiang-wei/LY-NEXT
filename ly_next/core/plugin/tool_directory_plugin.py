"""Plugin that loads tools from tools.plugin_dir."""

from __future__ import annotations

from ly_next.core.app_context import AppContext
from ly_next.core.plugin.protocol import LyNextPlugin
from ly_next.tools.loader import register_tools_from_directory
from ly_next.tools.registry import ToolRegistry


class ToolDirectoryPlugin(LyNextPlugin):
    name = "ly-next-tool-directory"
    version = "1.0.0"
    description = "Loads @tool modules from tools.plugin_dir"

    def register_tools(self, registry: ToolRegistry, ctx: AppContext) -> None:
        n = register_tools_from_directory(registry)
        ctx.extras["tool_directory_registered"] = n
