from __future__ import annotations

from unittest.mock import MagicMock

from ly_next.agent.deps import AgentDeps
from ly_next.agent.react.helpers import react_loop_kind


def test_react_loop_kind_langgraph_native(monkeypatch):
    def fake_get(key, default=None):
        if key == "agent.react_engine":
            return "langgraph_native"
        if key == "agent.prefer_compat_when_mcp_tools":
            return False
        return default

    monkeypatch.setattr("ly_next.agent.react.helpers.config.get", fake_get)
    deps = AgentDeps(
        tool_registry=MagicMock(list_tools=MagicMock(return_value=[object()])),
        tool_call_mode="native",
        native_tool_calls=True,
    )
    assert react_loop_kind(deps) == "langgraph_native"


def test_checkpoint_write_every(monkeypatch):
    from ly_next.core import checkpointer

    monkeypatch.setattr("ly_next.core.checkpointer.config.get", lambda key, default=None: default)
    assert checkpointer.checkpoint_writes_during_run() is False

    def fake_get(key, default=None):
        if key == "agent.persistence.checkpoint.write_every":
            return "iteration"
        return default

    monkeypatch.setattr("ly_next.core.checkpointer.config.get", fake_get)
    assert checkpointer.checkpoint_writes_during_run() is True
