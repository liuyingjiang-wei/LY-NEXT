from __future__ import annotations

from unittest.mock import MagicMock, patch

from ly_next.agent.deps import create_agent_deps


def _policy_mock(policy: dict):
    root = {"agent": {"tool_policy": policy}}
    mock = MagicMock()
    mock.get.side_effect = lambda k, default=None: _get(root, k, default)
    return mock


def _get(d: dict, dotted: str, default):
    cur: object = d
    for part in dotted.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return default
    return cur


def test_allow_categories_empty_list_becomes_none():
    mock = _policy_mock({"allow_categories": [], "deny_tools": [], "max_tier": "network"})
    with patch("ly_next.agent.deps.config", mock):
        deps = create_agent_deps()
    assert deps.tool_allow_categories is None


def test_allow_categories_whitelist():
    mock = _policy_mock(
        {"allow_categories": ["safe", "mcp"], "deny_tools": [], "max_tier": "network"}
    )
    with patch("ly_next.agent.deps.config", mock):
        deps = create_agent_deps()
    assert deps.tool_allow_categories == ["safe", "mcp"]
