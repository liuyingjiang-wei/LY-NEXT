from collections.abc import Callable
from typing import Any

from ly_next.core.logger import get_logger
from ly_next.tools.base import BaseTool, ToolResult

logger = get_logger(__name__)


class ToolRegistry:
    def __init__(self):
        self._tools: dict[str, BaseTool] = {}
        self._by_category: dict[str, set[str]] = {}
        self._aliases: dict[str, str] = {}

    def register(
        self,
        tool: BaseTool | Callable,
        name: str | None = None,
        category: str | None = None,
        aliases: list[str] | None = None,
    ) -> None:
        tool_name = name or getattr(tool, "name", None) or tool.__name__

        if not hasattr(tool, "definition") or not hasattr(tool, "execute"):
            raise ValueError(f"{tool_name} is not a valid tool")

        definition = tool.definition
        if category:
            definition.category = category
        tool_name = name or definition.name

        self._tools[tool_name] = tool
        tool.definition.name = tool_name

        cat = tool.definition.category
        if cat not in self._by_category:
            self._by_category[cat] = set()
        self._by_category[cat].add(tool_name)

        if aliases:
            for alias in aliases:
                self._aliases[alias] = tool_name

        logger.debug(f"[registry] Registered tool: {tool_name} (category: {cat})")

    def unregister(self, name: str) -> bool:
        tool_name = self._aliases.pop(name, name)

        if tool_name in self._tools:
            tool = self._tools.pop(tool_name)
            cat = tool.definition.category
            if cat in self._by_category:
                self._by_category[cat].discard(tool_name)
            return True

        return False

    def get(self, name: str) -> BaseTool | None:
        tool_name = self._aliases.get(name, name)
        return self._tools.get(tool_name)

    def has(self, name: str) -> bool:
        return self.get(name) is not None

    def list_tools(self) -> list[BaseTool]:
        return list(self._tools.values())

    def list_tool_names(self) -> list[str]:
        return list(self._tools.keys())

    def get_by_category(self, category: str) -> list[BaseTool]:
        tool_names = self._by_category.get(category, set())
        return [self._tools[name] for name in tool_names if name in self._tools]

    def list_categories(self) -> list[str]:
        return list(self._by_category.keys())

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        tool = self.get(name)
        if not tool:
            return {"success": False, "error": f"Tool not found: {name}"}

        try:
            logger.debug(f"[registry] Calling tool: {name} with args: {arguments}")
            result = await tool.execute(**arguments)

            if isinstance(result, ToolResult):
                return result.to_dict()

            return {"success": True, "result": result}

        except Exception as e:
            logger.error(f"[registry] Tool {name} failed: {e}")
            return {"success": False, "error": str(e)}

    def get_tools_for_llm(self, category: str | None = None) -> list[dict[str, Any]]:
        tools = self._tools.values() if not category else self.get_by_category(category)

        return [
            {
                "name": t.definition.name,
                "description": t.definition.description,
                "inputSchema": t.definition.parameters,
            }
            for t in tools
        ]

    def get_openai_format(self) -> list[dict[str, Any]]:
        return [t.definition.to_openai_format() for t in self._tools.values()]

    def get_langchain_format(self) -> list[dict[str, Any]]:
        return [t.definition.to_langchain_format() for t in self._tools.values()]

    def __len__(self) -> int:
        return len(self._tools)

    def __contains__(self, name: str) -> bool:
        return self.has(name)


_global_registry: ToolRegistry | None = None


def get_tool_registry() -> ToolRegistry:
    global _global_registry
    if _global_registry is None:
        _global_registry = ToolRegistry()
    return _global_registry


def set_tool_registry(registry: ToolRegistry) -> None:
    global _global_registry
    _global_registry = registry
