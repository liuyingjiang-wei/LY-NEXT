from __future__ import annotations

from ly_next.agent.tool_filter import (
    filter_tools_for_agent,
    list_tools_payload,
    max_tier_rank,
    tier_rank,
)
from ly_next.tools.registry import ToolRegistry


def test_tier_rank():
    assert tier_rank("safe") == 0
    assert tier_rank("general") == 1
    assert tier_rank("network") == 2
    assert tier_rank("mcp") == 1
    assert tier_rank(None) == 1


def test_max_tier_rank():
    assert max_tier_rank("safe") == 0
    assert max_tier_rank("network") == 2
    assert max_tier_rank("host") == 3
    assert tier_rank("host") == 3


def test_filter_deny_tools(fake_registry):
    picked, names = filter_tools_for_agent(
        fake_registry,
        allow_tools=None,
        deny_tools=["http_fetch"],
        allow_categories=None,
        max_tier="network",
        max_tools=40,
    )
    assert "http_fetch" not in names
    assert "calculator" in names


def test_filter_allow_tools_whitelist(fake_registry):
    picked, names = filter_tools_for_agent(
        fake_registry,
        allow_tools=["calculator", "http_fetch"],
        deny_tools=[],
        allow_categories=None,
        max_tier="safe",
        max_tools=40,
    )
    assert set(names) == {"calculator", "http_fetch"}


def test_filter_max_tier_safe_excludes_network(fake_registry):
    picked, names = filter_tools_for_agent(
        fake_registry,
        allow_tools=None,
        deny_tools=[],
        allow_categories=None,
        max_tier="safe",
        max_tools=40,
    )
    assert names == ["calculator"]


def test_filter_allow_categories(fake_registry):
    picked, names = filter_tools_for_agent(
        fake_registry,
        allow_tools=None,
        deny_tools=[],
        allow_categories=["mcp"],
        max_tier="network",
        max_tools=40,
    )
    assert names == ["mcp_search"]


def test_filter_allow_tools_empty_returns_empty(fake_registry):
    picked, names = filter_tools_for_agent(
        fake_registry,
        allow_tools=[],
        deny_tools=[],
        allow_categories=None,
        max_tier="network",
        max_tools=40,
    )
    assert picked == []
    assert names == []


def test_filter_max_tier_network_excludes_host(fake_registry):
    picked, names = filter_tools_for_agent(
        fake_registry,
        allow_tools=None,
        deny_tools=[],
        allow_categories=None,
        max_tier="network",
        max_tools=40,
    )
    assert "host_read_file" not in names
    assert "calculator" in names


def test_filter_max_tier_host_includes_host(fake_registry):
    picked, names = filter_tools_for_agent(
        fake_registry,
        allow_tools=None,
        deny_tools=[],
        allow_categories=None,
        max_tier="host",
        max_tools=40,
    )
    assert "host_read_file" in names


def test_semantic_select_ranks_by_query(monkeypatch):
    from ly_next.core.config import config as global_config
    from tests.conftest import FakeTool

    monkeypatch.setattr("ly_next.agent.tool_filter.semantic_select_enabled", lambda: True)
    real_get = global_config.get

    def fake_get(key: str, default=None):
        if key == "agent.tool_policy":
            return {"semantic_top_k": 2, "pin_tools": []}
        return real_get(key, default)

    monkeypatch.setattr(global_config, "get", fake_get)
    monkeypatch.setattr(
        "ly_next.agent.tool_router._policy",
        lambda: {
            "semantic_method": "lexical",
            "semantic_min_score": 0.05,
            "semantic_relative_factor": 0.85,
            "semantic_min_pool": 1,
            "semantic_fallback": "pins_only",
            "semantic_top_k": 2,
            "pin_tools": [],
        },
    )
    reg = ToolRegistry()
    reg.register(FakeTool("calculator", "safe"))
    reg.register(FakeTool("web_search", "network"))
    reg._tools["web_search"]._definition.description = "search the live web for news and facts"
    picked, names = filter_tools_for_agent(
        reg,
        allow_tools=None,
        deny_tools=[],
        allow_categories=None,
        max_tier="network",
        max_tools=5,
        router_query="search the web for news",
    )
    assert names == ["web_search"]


def test_list_tools_payload(fake_registry):
    picked, _ = filter_tools_for_agent(
        fake_registry,
        allow_tools=["calculator"],
        deny_tools=[],
        allow_categories=None,
        max_tier="network",
        max_tools=40,
    )
    payload = list_tools_payload(picked)
    assert len(payload) == 1
    assert payload[0]["name"] == "calculator"
    assert "inputSchema" in payload[0]
