from __future__ import annotations

from typing import Any

from ly_next.agent.langchain_integration import LyToolkit
from ly_next.mcp.langchain_adapter_bridge import get_cached_langchain_mcp_tools
from ly_next.tools.registry import get_tool_registry


def all_langchain_tools_for_graph(registry: Any | None = None) -> list[Any]:
    reg = registry or get_tool_registry()
    return LyToolkit(reg).get_tools()


def create_react_agent_graph(
    llm: Any, *, registry: Any | None = None, mcp_only: bool = False
) -> Any:
    from langgraph.prebuilt import create_react_agent

    tools = (
        list(get_cached_langchain_mcp_tools())
        if mcp_only
        else all_langchain_tools_for_graph(registry)
    )
    return create_react_agent(llm, tools)
