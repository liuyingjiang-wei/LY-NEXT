from ly_next.tools.base import BaseTool, ToolDefinition, ToolResult, tool
from ly_next.tools.builtin import BUILTIN_TOOLS, BUILTIN_TOOLS_BY_NAME, register_builtin_tools
from ly_next.tools.registry import ToolRegistry, get_tool_registry, set_tool_registry

__all__ = [
    "BaseTool",
    "ToolDefinition",
    "ToolResult",
    "tool",
    "ToolRegistry",
    "get_tool_registry",
    "set_tool_registry",
    "BUILTIN_TOOLS",
    "BUILTIN_TOOLS_BY_NAME",
    "register_builtin_tools",
    "register_tools_from_directory",
]


def __getattr__(name: str):
    if name == "register_tools_from_directory":
        from ly_next.tools.loader import register_tools_from_directory

        return register_tools_from_directory
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
