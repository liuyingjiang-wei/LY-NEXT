from __future__ import annotations

import pytest

from ly_next.agent.deps import AgentDeps
from ly_next.agent.tool_context import reset_tool_run_deps, set_tool_run_deps
from ly_next.tools.meta_tools import describe_tool, list_tools
from ly_next.tools.registry import ToolRegistry
from tests.conftest import FakeTool


@pytest.mark.asyncio
async def test_list_tools_uses_run_deps():
    reg = ToolRegistry()
    reg.register(FakeTool("alpha", "safe"))
    reg.register(FakeTool("beta", "network"))
    deps = AgentDeps(tool_registry=reg, tool_max_tier="network", max_tools=40)
    token = set_tool_run_deps(deps)
    try:
        result = await list_tools()
    finally:
        reset_tool_run_deps(token)
    assert result.success is True
    names = {row["name"] for row in result.result["tools"]}
    assert "alpha" in names
    assert "beta" in names


@pytest.mark.asyncio
async def test_describe_tool_returns_schema():
    reg = ToolRegistry()
    tool = FakeTool("alpha", "safe")
    tool._definition.description = "Alpha tool"
    reg.register(tool)
    deps = AgentDeps(tool_registry=reg, max_tools=40)
    token = set_tool_run_deps(deps)
    try:
        result = await describe_tool(name="alpha")
    finally:
        reset_tool_run_deps(token)
    assert result.success is True
    assert result.result["name"] == "alpha"
    assert "parameters" in result.result
