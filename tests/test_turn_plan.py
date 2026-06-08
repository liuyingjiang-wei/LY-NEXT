from __future__ import annotations

from ly_next.agent.chat_pipeline import ChatTurnRequest
from ly_next.agent.turn_plan import build_turn_plan


def test_turn_plan_tool_intent_stays_react():
    req = ChatTurnRequest(
        client_messages=[{"role": "user", "content": "搜索今天北京天气"}],
        mode="react",
    )
    plan = build_turn_plan(req)
    assert plan.tool_intent is True
    assert plan.effective_mode == "react"
    assert plan.fast_path is False
