from __future__ import annotations

import ly_next.api.ws_api as ws_api
from ly_next.core.run_telemetry import (
    begin_run,
    end_run,
    get_public_snapshot,
    record_llm_usage_from_chat_response,
    record_tool_timing,
)


def test_telemetry_accumulates_usage_and_tools():
    tok = begin_run("tid-1")
    try:
        record_llm_usage_from_chat_response(
            {"usage": {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30}}
        )
        record_llm_usage_from_chat_response({})
        record_tool_timing("calculator", 12.5, True)
        snap = get_public_snapshot()
        assert snap is not None
        assert snap["task_id"] == "tid-1"
        assert snap["llm_calls"] == 2
        assert snap["prompt_tokens"] == 10
        assert snap["completion_tokens"] == 20
        assert snap["total_tokens"] == 30
        assert len(snap["tools"]) == 1
        assert snap["tools"][0]["tool"] == "calculator"
    finally:
        end_run(tok)

    assert get_public_snapshot() is None


def test_ws_run_summary_respects_flag(monkeypatch):
    monkeypatch.setattr(ws_api, "ws_run_summary_enabled", lambda: False)
    tok = begin_run("tid-2")
    try:
        record_llm_usage_from_chat_response({"usage": {"total_tokens": 1}})
        assert ws_api._ws_run_summary_fields() == {}
    finally:
        end_run(tok)

    monkeypatch.setattr(ws_api, "ws_run_summary_enabled", lambda: True)
    tok = begin_run("tid-3")
    try:
        record_llm_usage_from_chat_response({"usage": {"total_tokens": 2}})
        d = ws_api._ws_run_summary_fields()
        assert d.get("run_summary", {}).get("total_tokens") == 2
    finally:
        end_run(tok)


def test_usage_counter_accepts_integral_float():
    from ly_next.core.run_telemetry import usage_counter_value

    assert usage_counter_value(3.0) == 3
    assert usage_counter_value(-1) == 0
    assert usage_counter_value(True) == 0
    assert usage_counter_value("x") == 0


def test_telemetry_coerces_float_usage_tokens():
    tok = begin_run("tid-f")
    try:
        record_llm_usage_from_chat_response(
            {"usage": {"prompt_tokens": 5.0, "completion_tokens": 1.5, "total_tokens": 7}}
        )
        snap = get_public_snapshot()
        assert snap["prompt_tokens"] == 5
        assert snap["completion_tokens"] == 0
        assert snap["total_tokens"] == 7
    finally:
        end_run(tok)
