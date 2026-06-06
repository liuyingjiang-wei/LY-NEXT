from __future__ import annotations

from ly_next.core.run_telemetry import (
    begin_run,
    emit_run_event,
    end_run,
    get_public_snapshot,
    get_run_events,
    persisted_usage_from_snapshot,
    record_llm_call_failed,
    record_llm_call_start,
    record_llm_usage_from_chat_response,
    record_tool_timing,
    set_run_loop_kind,
    snapshot_usage_for_api,
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
    import ly_next.core.observability as obs

    monkeypatch.setattr(obs, "ws_run_summary_enabled", lambda: False)
    assert obs.attach_run_fields({"task_id": "t"}, {"total_tokens": 1}) == {"task_id": "t"}

    monkeypatch.setattr(obs, "ws_run_summary_enabled", lambda: True)
    tok = begin_run("tid-3")
    try:
        record_llm_usage_from_chat_response({"usage": {"total_tokens": 2}})
        snap = get_public_snapshot()
        out = obs.attach_run_fields({"task_id": "t"}, snap)
        assert out.get("run_summary", {}).get("total_tokens") == 2
    finally:
        end_run(tok)


def test_record_stream_event_skips_chunks():
    from ly_next.core.run_telemetry import record_stream_event

    tok = begin_run("tid-chunk")
    try:
        record_stream_event({"type": "chunk", "content": "x" * 1000})
        record_stream_event({"type": "status", "phase": "llm"})
        assert len(get_run_events()) == 1
    finally:
        end_run(tok)


def test_usage_counter_accepts_integral_float():
    from ly_next.core.run_telemetry import usage_counter_value

    assert usage_counter_value(3.0) == 3
    assert usage_counter_value(-1) == 0
    assert usage_counter_value(True) == 0
    assert usage_counter_value("x") == 0


def test_emit_run_event_and_loop_kind():
    tok = begin_run("tid-ev")
    try:
        set_run_loop_kind("compat")
        emit_run_event("status", {"phase": "llm", "content": "secret"})
        events = get_run_events()
        assert len(events) == 1
        assert events[0]["kind"] == "status"
        assert "content" not in events[0]["payload"]
        assert events[0]["payload"].get("content_chars") == len("secret")
        snap = get_public_snapshot()
        assert snap is not None
        assert snap.get("loop_kind") == "compat"
    finally:
        end_run(tok)


def test_snapshot_usage_helpers():
    snap = {
        "prompt_tokens": 5.0,
        "completion_tokens": "bad",
        "total_tokens": 7,
        "llm_calls": 2,
        "tools": [{"tool": "x"}],
    }
    api_usage = snapshot_usage_for_api(snap)
    assert api_usage["prompt_tokens"] == 5
    assert api_usage["completion_tokens"] == 0
    assert api_usage["total_tokens"] == 7
    assert api_usage["llm_calls"] == 2
    assert "tools" not in api_usage

    persisted = persisted_usage_from_snapshot(snap)
    assert persisted["total_tokens"] == 7
    assert len(persisted["tools"]) == 1


def test_llm_start_and_failed_events():
    tok = begin_run("tid-llm")
    try:
        record_llm_call_start(model="gpt-4o", messages_count=4, provider="openai_compat")
        record_llm_call_failed(model="gpt-4o", error="timeout")
        events = get_run_events()
        assert [e["kind"] for e in events] == ["llm_start", "llm_end"]
        assert events[0]["payload"]["model"] == "gpt-4o"
        assert events[1]["payload"]["success"] is False
        snap = get_public_snapshot()
        assert snap["llm_calls"] == 1
    finally:
        end_run(tok)


def test_llm_start_stores_messages_when_store_prompts(monkeypatch):
    import ly_next.core.observability as obs

    monkeypatch.setattr(obs, "store_prompts", lambda: True)
    tok = begin_run("tid-prompt")
    try:
        record_llm_call_start(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": "hello"}],
        )
        events = get_run_events()
        assert events[0]["payload"]["messages"][0]["content"] == "hello"
    finally:
        end_run(tok)


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
