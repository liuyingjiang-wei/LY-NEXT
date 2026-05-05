"""LangChain Integration."""

from langchain_core.tools import BaseTool

from ly_next.core.logger import get_logger
from ly_next.tools.base import BaseTool as LyBaseTool
from ly_next.tools.registry import ToolRegistry, get_tool_registry

logger = get_logger(__name__)


def tool_to_langchain(tool: LyBaseTool, registry: ToolRegistry | None = None) -> type[BaseTool]:
    """Convert LY-Next tool to LangChain tool."""
    definition = tool.definition

    class ConvertedTool(BaseTool):
        name: str = definition.name
        description: str = definition.description

        def _run(self, *args, **kwargs) -> str:
            raise NotImplementedError("Use ainvoke instead")

        async def _arun(self, **kwargs) -> str:
            reg = registry or get_tool_registry()
            result = await reg.call_tool(self.name, kwargs)
            if result.get("success"):
                return str(result.get("result", ""))
            else:
                raise Exception(f"Tool execution failed: {result.get('error', 'Unknown error')}")

    return ConvertedTool


class LyToolkit:
    """LangChain toolkit wrapping LY-Next tools."""

    def __init__(self, registry: ToolRegistry | None = None):
        self.registry = registry or get_tool_registry()
        self._tools: list[BaseTool] = []
        self._convert_tools()

    def _convert_tools(self) -> None:
        for ly_tool in self.registry.list_tools():
            try:
                lc_tool = tool_to_langchain(ly_tool, self.registry)
                self._tools.append(lc_tool())
                logger.debug(f"Converted tool to LangChain: {ly_tool.name}")
            except Exception as e:
                logger.warning(f"Failed to convert tool {ly_tool.name}: {e}")

    def get_tools(self) -> list[BaseTool]:
        return self._tools

    def get_tool(self, name: str) -> BaseTool | None:
        for tool in self._tools:
            if tool.name == name:
                return tool
        return None

    def get_by_category(self, category: str) -> list[BaseTool]:
        wei_tools = self.registry.get_by_category(category)
        result = []
        for ly_tool in wei_tools:
            lc_tool = self.get_tool(ly_tool.name)
            if lc_tool:
                result.append(lc_tool)
        return result
