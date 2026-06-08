from __future__ import annotations

from ly_next.agent.chat_pipeline import ChatTurnRequest, resolve_effective_mode
from ly_next.agent.turn_plan import build_turn_plan, resolve_augment_skips


def test_tool_intent_detects_search_and_office():
    from ly_next.agent.prompt_augment import is_tool_intent_query

    assert is_tool_intent_query("帮我搜索一下 OpenAI 最新模型")
    assert is_tool_intent_query("生成一份 Excel 销售表格")
    assert is_tool_intent_query("export this as docx report")
    assert not is_tool_intent_query("解释一下 React useEffect 的用法")


def test_should_skip_retrieval_for_tool_intent():
    from ly_next.agent.prompt_augment import should_skip_retrieval_augment

    assert should_skip_retrieval_augment("联网查今天上海天气") is True


def test_resolve_augment_skips_fast_path():
    skip_rag, skip_ctx = resolve_augment_skips(
        ChatTurnRequest(client_messages=[{"role": "user", "content": "搜索特斯拉股价"}])
    )
    assert skip_rag is True
    assert skip_ctx is True


def test_fast_chat_query_todo_and_greeting():
    from ly_next.agent.prompt_augment import is_fast_chat_query

    assert is_fast_chat_query("帮我整理本周待办")
    assert is_fast_chat_query("你好")
    assert not is_fast_chat_query("帮我搜索一下 OpenAI 最新模型")


def test_resolve_effective_mode_honors_explicit_react():
    req = ChatTurnRequest(
        client_messages=[{"role": "user", "content": "帮我整理本周待办"}],
        mode="react",
    )
    assert resolve_effective_mode(req) == "react"


def test_resolve_effective_mode_keeps_react_for_tool_intent():
    req = ChatTurnRequest(
        client_messages=[{"role": "user", "content": "联网查今天上海天气"}],
        mode="react",
    )
    assert resolve_effective_mode(req) == "react"


def test_turn_plan_fast_path_flags():
    req = ChatTurnRequest(
        client_messages=[{"role": "user", "content": "你好"}],
        mode="react",
    )
    plan = build_turn_plan(req)
    assert plan.fast_path is True
    assert plan.effective_mode == "react"
    assert plan.skip_rag is True
