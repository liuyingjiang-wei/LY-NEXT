from __future__ import annotations

from ly_next.core.config_merge import merge_config_dicts


def test_merge_nested_dicts():
    default = {
        "tools": {"built_in": ["a", "b"], "mcp": {"enabled": True}},
        "server": {"port": 8000},
    }
    user = {"tools": {"built_in": ["a"]}}
    out = merge_config_dicts(default, user)
    assert out["tools"]["built_in"] == ["a"]
    assert out["tools"]["mcp"]["enabled"] is True
    assert out["server"]["port"] == 8000


def test_merge_list_replaces():
    default = {"x": [1, 2, 3]}
    user = {"x": [9]}
    assert merge_config_dicts(default, user)["x"] == [9]


def test_merge_shallow_keys():
    assert merge_config_dicts({"a": 1}, {"b": 2}) == {"a": 1, "b": 2}
