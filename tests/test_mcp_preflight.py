from __future__ import annotations

from ly_next.mcp.preflight import _needs_node, gather_mcp_runtime_checks


def test_needs_node_detects_cmd_npx():
    assert _needs_node("cmd", ["/c", "npx", "-y", "bing-cn-mcp"])


def test_gather_mcp_runtime_checks_empty_when_disabled(monkeypatch):
    monkeypatch.setattr(
        "ly_next.mcp.preflight._mcp_remote_blocks",
        lambda: [],
    )
    assert gather_mcp_runtime_checks() == []
