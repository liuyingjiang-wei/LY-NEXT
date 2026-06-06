from __future__ import annotations

from ly_next.models.stream_assemble import (
    accumulate_tool_call_delta,
    build_chat_completion_from_stream,
)


def test_accumulate_tool_call_delta_merges_chunks():
    acc: dict[int, dict] = {}
    accumulate_tool_call_delta(
        acc,
        {"index": 0, "id": "call_1", "function": {"name": "web", "arguments": ""}},
    )
    accumulate_tool_call_delta(acc, {"index": 0, "function": {"arguments": '{"q":'}})
    accumulate_tool_call_delta(acc, {"index": 0, "function": {"arguments": '"x"}'}})
    assert acc[0]["id"] == "call_1"
    assert acc[0]["function"]["name"] == "web"
    assert acc[0]["function"]["arguments"] == '{"q":"x"}'


def test_build_chat_completion_from_stream_with_tools():
    acc: dict[int, dict] = {}
    accumulate_tool_call_delta(
        acc,
        {"index": 0, "id": "c1", "function": {"name": "calc", "arguments": "{}"}},
    )
    out = build_chat_completion_from_stream(
        content="",
        tool_calls=acc,
        finish_reason="tool_calls",
        usage={"total_tokens": 10},
    )
    msg = out["choices"][0]["message"]
    assert msg["tool_calls"][0]["function"]["name"] == "calc"
    assert out["usage"]["total_tokens"] == 10
