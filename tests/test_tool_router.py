from __future__ import annotations

from ly_next.agent.tool_router import (
    _apply_threshold,
    pin_tool_names,
    route_tools_by_query,
    score_tools_lexical,
)
from ly_next.tools.base import ToolDefinition


class _T:
    def __init__(self, name: str, desc: str) -> None:
        self.definition = ToolDefinition(
            name=name,
            description=desc,
            parameters={"type": "object", "properties": {}},
            category="general",
        )


def test_route_tools_prefers_web_search_for_news_query(monkeypatch):
    monkeypatch.setattr(
        "ly_next.agent.tool_router._policy",
        lambda: {
            "semantic_method": "lexical",
            "semantic_min_score": 0.05,
            "semantic_relative_factor": 0.85,
            "semantic_min_pool": 2,
            "semantic_fallback": "pins_only",
            "pin_tools": [],
        },
    )
    tools = [
        _T("calculator", "math expressions"),
        _T("web_search", "search the live web for news and facts"),
        _T("knowledge_search", "local markdown knowledge base"),
    ]
    ordered = route_tools_by_query("latest AI news today", tools, limit=2)
    names = [t.definition.name for t in ordered]
    assert names[0] == "web_search"


def test_low_confidence_falls_back_to_pins_only(monkeypatch):
    monkeypatch.setattr(
        "ly_next.agent.tool_router._policy",
        lambda: {
            "semantic_method": "lexical",
            "semantic_min_score": 0.9,
            "semantic_relative_factor": 0.92,
            "semantic_min_pool": 2,
            "semantic_fallback": "pins_only",
            "pin_tools": ["list_tools", "describe_tool"],
        },
    )
    tools = [
        _T("list_tools", "list visible tools"),
        _T("describe_tool", "describe a tool"),
        _T("calculator", "math expressions"),
    ]
    ordered = route_tools_by_query("你好", tools, limit=5)
    names = [t.definition.name for t in ordered]
    assert names == ["list_tools", "describe_tool"]


def test_hybrid_uses_lexical_only_when_embedding_missing(monkeypatch):
    monkeypatch.setattr(
        "ly_next.agent.tool_router._policy",
        lambda: {
            "semantic_method": "hybrid",
            "semantic_min_score": 0.01,
            "semantic_relative_factor": 0.5,
            "semantic_min_pool": 2,
            "semantic_fallback": "all",
            "pin_tools": [],
        },
    )
    tools = [
        _T("web_search", "search the live web for news and facts"),
        _T("calculator", "math expressions"),
    ]
    ordered = route_tools_by_query("latest AI news today", tools, limit=1, query_vec=None)
    assert ordered[0].definition.name == "web_search"


def test_small_pool_skips_semantic_filter(monkeypatch):
    monkeypatch.setattr(
        "ly_next.agent.tool_router._policy",
        lambda: {
            "semantic_min_pool": 8,
            "semantic_fallback": "pins_only",
        },
    )
    tools = [_T("a", "alpha"), _T("b", "beta")]
    ordered = route_tools_by_query("anything", tools, limit=2)
    assert len(ordered) == 2


def test_apply_threshold_relative_cutoff():
    tools = [_T("a", ""), _T("b", ""), _T("c", "")]
    scored = [(1.0, tools[0]), (0.95, tools[1]), (0.5, tools[2])]
    picked = _apply_threshold(scored, limit=5, min_absolute=0.3, relative_factor=0.92)
    names = [t.definition.name for t in picked]
    assert names == ["a", "b"]


def test_name_match_boost_ranks_exact_tool(monkeypatch):
    monkeypatch.setattr(
        "ly_next.agent.tool_router._policy",
        lambda: {
            "semantic_method": "lexical",
            "semantic_min_score": 0.05,
            "semantic_relative_factor": 0.8,
            "semantic_min_pool": 1,
            "pin_tools": [],
        },
    )
    tools = [
        _T("web_search", "search the live web"),
        _T("grep_code", "search code in files"),
    ]
    scored = score_tools_lexical("use grep_code on src", tools)
    assert scored[0][1].definition.name == "grep_code"


def test_pin_tool_names_default():
    assert "list_tools" in pin_tool_names()
