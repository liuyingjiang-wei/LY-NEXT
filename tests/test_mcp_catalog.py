from ly_next.mcp.catalog import (
    build_mcp_catalog_payload,
    entries_to_blocks,
    get_loaded_mcp_slugs,
    normalize_remote_entries,
    parse_mcp_enabled_slugs,
    set_loaded_mcp_slugs,
    slugs_from_body,
)
from ly_next.mcp.server_filter import filter_tools_by_mcp_slugs, mcp_tool_matches_slug
from ly_next.tools.base import BaseTool, ToolDefinition, ToolResult


class _StubTool(BaseTool):
    def __init__(self, name: str, category: str = "mcp"):
        self._definition = ToolDefinition(
            name=name,
            description="",
            parameters={"type": "object"},
            category=category,
        )

    @property
    def definition(self) -> ToolDefinition:
        return self._definition

    async def execute(self, **kwargs) -> ToolResult:
        return ToolResult(success=True, result=kwargs)


def test_normalize_remote_entries_from_legacy_blocks():
    remote = {
        "enabled": True,
        "mcpServers": [
            {"config": {"mcpServers": {"weather": {"command": "uvx", "args": ["pkg"]}}}},
        ],
    }
    entries = normalize_remote_entries(remote)
    assert len(entries) == 1
    assert entries[0]["label"] == "weather"
    assert slugs_from_body(entries[0]["body"]) == ["weather"]


def test_entries_to_blocks():
    entries = [{"id": "e1", "label": "W", "body": {"mcpServers": {"a": {"url": "http://x"}}}}]
    blocks = entries_to_blocks(entries)
    assert len(blocks) == 1
    assert "mcpServers" in blocks[0]


def test_parse_mcp_enabled_slugs():
    assert parse_mcp_enabled_slugs(None) is None
    assert parse_mcp_enabled_slugs([]) == frozenset()
    assert parse_mcp_enabled_slugs(["Weather-Server"]) == frozenset({"weather-server"})


def test_set_loaded_mcp_slugs_and_catalog_shape():
    set_loaded_mcp_slugs(["bing-win"])
    payload = build_mcp_catalog_payload()
    assert "servers" in payload
    assert "remote_enabled" in payload
    assert "bing-win" in get_loaded_mcp_slugs()


def test_mcp_tool_matches_slug_with_prefix():
    assert mcp_tool_matches_slug("weather__get", "weather", use_prefix=True)
    assert not mcp_tool_matches_slug("other__get", "weather", use_prefix=True)


def test_filter_tools_by_mcp_slugs():
    tools = [
        _StubTool("web_search", "network"),
        _StubTool("weather__get", "mcp"),
        _StubTool("bing__search", "mcp"),
    ]
    all_tools = filter_tools_by_mcp_slugs(tools, None)
    assert len(all_tools) == 3
    only_weather = filter_tools_by_mcp_slugs(tools, frozenset({"weather"}))
    names = [t.definition.name for t in only_weather]
    assert names == ["web_search", "weather__get"]
    none_mcp = filter_tools_by_mcp_slugs(tools, frozenset())
    assert [t.definition.name for t in none_mcp] == ["web_search"]
