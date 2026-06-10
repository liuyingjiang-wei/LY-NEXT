"""Tests for react loop routing and turn plan fast paths."""

from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import MagicMock

from ly_next.agent.deps import AgentDeps
from ly_next.agent.react.helpers import auto_use_compat_first_for_mcp, react_loop_kind
from ly_next.agent.turn_plan import build_turn_plan


@dataclass
class _Req:
    mode: str = "react"
    client_messages: list = None
    skip_rag: bool = False
    skip_context: bool = False
    skip_memory: bool = False
    skip_augment: bool | None = None

    def __post_init__(self):
        if self.client_messages is None:
            self.client_messages = [{"role": "user", "content": "搜索今天的新闻"}]


def test_react_loop_kind_prefers_native_over_mcp_compat(monkeypatch):
    monkeypatch.setattr(
        "ly_next.agent.react.helpers.config.get",
        lambda key, default=None: False if key == "agent.prefer_compat_when_mcp_tools" else default,
    )
    monkeypatch.setattr(
        "ly_next.agent.react.helpers.visible_tools_include_mcp",
        lambda _deps: True,
    )
    deps = AgentDeps(
        tool_registry=MagicMock(list_tools=MagicMock(return_value=[object()])),
        native_tool_calls=True,
        tool_call_mode="auto",
    )
    assert auto_use_compat_first_for_mcp(deps) is False
    assert react_loop_kind(deps) == "native"


def test_turn_plan_skips_rag_on_react(monkeypatch):
    monkeypatch.setattr(
        "ly_next.agent.turn_plan.pipeline_cfg",
        lambda key, default=None: (
            True
            if key == "skip_rag_on_react"
            else (False if key == "auto_skip_tool_intents" else default)
        ),
    )
    monkeypatch.setattr("ly_next.agent.turn_plan.is_fast_chat_query", lambda _q: False)
    plan = build_turn_plan(
        _Req(
            mode="react",
            client_messages=[{"role": "user", "content": "帮我写一首关于春天的诗"}],
        )
    )
    assert plan.effective_mode == "react"
    assert plan.skip_rag is True
    assert plan.skip_context is False


def test_turn_plan_skips_augment_on_tool_intent(monkeypatch):
    monkeypatch.setattr(
        "ly_next.agent.turn_plan.pipeline_cfg",
        lambda key, default=None: True,
    )
    plan = build_turn_plan(_Req())
    assert plan.tool_intent is True
    assert plan.skip_augment is True
    assert plan.skip_rag is True
    assert plan.skip_context is True
