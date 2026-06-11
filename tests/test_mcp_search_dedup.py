from __future__ import annotations

from ly_next.agent.tool_filter import filter_tools_for_agent
from ly_next.mcp.remote_bridge import merge_mcp_server_blocks
from ly_next.mcp.search_dedup import apply_search_tool_dedup, is_mcp_search_tool
from ly_next.tools.base import ToolDefinition, ToolResult
from ly_next.tools.registry import ToolRegistry


class _FakeTool:
    def __init__(self, name: str, category: str, description: str = ""):
        self._definition = ToolDefinition(
            name=name,
            description=description,
            parameters={"type": "object", "properties": {}},
            category=category,
        )

    @property
    def definition(self):
        return self._definition

    async def execute(self, **kwargs):
        return ToolResult(success=True, result={})


def test_is_mcp_search_tool_detects_prefixed_bing():
    t = _FakeTool("bing-search__bing_search", "mcp", "Search Bing")
    assert is_mcp_search_tool(t)


def test_apply_search_tool_dedup_prefer_builtin(monkeypatch):
    monkeypatch.setattr(
        "ly_next.mcp.search_dedup.search_dedup_strategy",
        lambda: "prefer_builtin",
    )
    tools = [
        _FakeTool("web_search", "network"),
        _FakeTool("bing-search__bing_search", "mcp"),
        _FakeTool("bing-search__crawl_webpage", "mcp"),
        _FakeTool("calculator", "safe"),
    ]
    kept = apply_search_tool_dedup(tools)
    names = [t.definition.name for t in kept]
    assert "web_search" in names
    assert "bing-search__bing_search" not in names
    assert "calculator" in names


def test_apply_search_tool_dedup_prefer_mcp(monkeypatch):
    monkeypatch.setattr(
        "ly_next.mcp.search_dedup.search_dedup_strategy",
        lambda: "prefer_mcp",
    )
    tools = [
        _FakeTool("web_search", "network"),
        _FakeTool("bing-search__bing_search", "mcp"),
    ]
    kept = apply_search_tool_dedup(tools)
    names = [t.definition.name for t in kept]
    assert "web_search" not in names
    assert "bing-search__bing_search" in names


def test_merge_mcp_server_blocks_warns_on_duplicate_keys():
    blocks = [
        {"mcpServers": {"bing-search": {"command": "npx", "args": ["-y", "a"]}}},
        {"mcpServers": {"bing-search": {"command": "npx", "args": ["-y", "b"]}}},
    ]
    merged = merge_mcp_server_blocks(blocks)
    assert merged["bing-search"]["args"] == ["-y", "b"]


def test_filter_tools_applies_search_dedup(monkeypatch):
    monkeypatch.setattr(
        "ly_next.mcp.search_dedup.search_dedup_strategy",
        lambda: "prefer_builtin",
    )
    reg = ToolRegistry()
    reg.register(_FakeTool("web_search", "network", "live web search"), name="web_search")
    reg.register(_FakeTool("bing-search__bing_search", "mcp", "bing search"), name="bing-search__bing_search")
    picked, names = filter_tools_for_agent(
        reg,
        allow_tools=None,
        deny_tools=[],
        allow_categories=None,
        max_tier="network",
        max_tools=40,
    )
    assert "web_search" in names
    assert "bing-search__bing_search" not in names
    assert picked
