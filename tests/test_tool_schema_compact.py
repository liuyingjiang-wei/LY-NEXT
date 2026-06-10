from __future__ import annotations

from ly_next.agent.tool_filter import compact_openai_tool, compact_openai_tools


def test_compact_openai_tool_strips_property_descriptions():
    raw = {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "Search the live web.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The search query to run.",
                        "examples": ["weather today"],
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max results.",
                    },
                },
                "required": ["query"],
            },
        },
    }
    out = compact_openai_tool(raw)
    fn = out["function"]
    props = fn["parameters"]["properties"]
    assert "description" not in props["query"]
    assert "examples" not in props["query"]
    assert props["query"]["type"] == "string"
    assert fn["parameters"]["required"] == ["query"]
    assert "(args: query, limit)" in fn["description"]


def test_compact_openai_tool_truncates_long_description(monkeypatch):
    monkeypatch.setattr(
        "ly_next.agent.tool_filter._tool_schema_cfg",
        lambda key, default=None: 24 if key == "max_description_chars" else default,
    )
    raw = {
        "type": "function",
        "function": {
            "name": "calc",
            "description": "A" * 80,
            "parameters": {"type": "object", "properties": {"x": {"type": "number"}}},
        },
    }
    out = compact_openai_tool(raw)
    assert len(out["function"]["description"]) <= 24
    assert out["function"]["description"].endswith("…")


def test_compact_openai_tools_preserves_order():
    tools = [
        {
            "type": "function",
            "function": {
                "name": "a",
                "description": "first",
                "parameters": {"type": "object", "properties": {}},
            },
        },
        {
            "type": "function",
            "function": {
                "name": "b",
                "description": "second",
                "parameters": {"type": "object", "properties": {}},
            },
        },
    ]
    out = compact_openai_tools(tools)
    assert [t["function"]["name"] for t in out] == ["a", "b"]
