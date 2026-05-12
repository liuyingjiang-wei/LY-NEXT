from __future__ import annotations

import pytest

from ly_next.tools.base import BaseTool, ToolDefinition, ToolResult
from ly_next.tools.registry import ToolRegistry


class FakeTool(BaseTool):
    def __init__(self, name: str, category: str = "general") -> None:
        self._definition = ToolDefinition(
            name=name,
            description="test",
            parameters={"type": "object", "properties": {}},
            category=category,
        )

    @property
    def definition(self) -> ToolDefinition:
        return self._definition

    async def execute(self, **kwargs: object) -> ToolResult:
        return ToolResult(success=True, result=None)


@pytest.fixture
def fake_registry() -> ToolRegistry:
    reg = ToolRegistry()
    reg.register(FakeTool("calculator", "safe"))
    reg.register(FakeTool("http_fetch", "network"))
    reg.register(FakeTool("web_search", "network"))
    reg.register(FakeTool("mcp_search", "mcp"))
    return reg
