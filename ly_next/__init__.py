import asyncio
import sys

# 须在任意 asyncio 循环创建前设置；配合 main.run(loop="none") 供 psycopg / LangGraph checkpoint
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

__version__ = "1.0.1"

from ly_next.agent import AgentFactory
from ly_next.core.app_context import AppContext, get_app_context, set_app_context
from ly_next.core.config import Config, config
from ly_next.core.logger import get_logger, setup_logging
from ly_next.core.plugin.protocol import LyNextPlugin
from ly_next.models import LLMFactory
from ly_next.tools import ToolRegistry, get_tool_registry

__all__ = [
    "__version__",
    "Config",
    "config",
    "setup_logging",
    "get_logger",
    "LLMFactory",
    "AgentFactory",
    "ToolRegistry",
    "get_tool_registry",
    "AppContext",
    "get_app_context",
    "set_app_context",
    "LyNextPlugin",
    "PluginLoader",
    "PluginRegistry",
]


def __getattr__(name: str):
    if name == "PluginLoader":
        from ly_next.core.plugin.loader import PluginLoader

        return PluginLoader
    if name == "PluginRegistry":
        from ly_next.core.plugin.registry import PluginRegistry

        return PluginRegistry
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
