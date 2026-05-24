import pytest

from ly_next.agent.json_extract import parse_json_object
from ly_next.agent.llm_text import text_from_message
from ly_next.agent.tool_streak import streak_after_tool_call, streak_after_tool_error


def test_parse_json_object_fenced() -> None:
    obj = parse_json_object('```json\n{"steps": [{"id": 1}]}\n```')
    assert obj["steps"][0]["id"] == 1


def test_parse_json_object_literal_newline_in_string() -> None:
    raw = '{"type":"final","final":"line one\nline two"}'
    obj = parse_json_object(raw)
    assert obj["type"] == "final"
    assert "line one" in obj["final"]


def test_parse_json_object_empty_raises() -> None:
    with pytest.raises(ValueError, match="empty model output"):
        parse_json_object("   ")


def test_parse_json_object_invalid_snippet() -> None:
    with pytest.raises(ValueError, match="invalid JSON"):
        parse_json_object("{not json}")


def test_text_from_message_reasoning_fallback() -> None:
    assert text_from_message({"content": "", "reasoning_content": '{"type":"final"}'}) == (
        '{"type":"final"}'
    )


def test_text_from_message_prefers_content() -> None:
    msg = {"content": '{"type":"tool"}', "reasoning_content": "thinking"}
    assert text_from_message(msg) == '{"type":"tool"}'


def test_streak_after_failed_tool() -> None:
    state = {"repeat_tool_calls": 0, "tool_fail_streak": 0}
    out = streak_after_tool_call(state, "calc", {"x": 1}, {"success": False, "error": "x"})
    assert out["tool_fail_streak"] == 1
    assert out["repeat_tool_calls"] == 1


def test_streak_after_tool_error() -> None:
    state = {"last_tool_signature": '{"args": {"x": 1}, "name": "calc"}', "repeat_tool_calls": 2}
    out = streak_after_tool_error(state, "calc", {"x": 1})
    assert out["repeat_tool_calls"] == 3
    assert out["tool_fail_streak"] == 1
