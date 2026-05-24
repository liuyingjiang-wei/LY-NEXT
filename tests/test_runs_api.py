from __future__ import annotations

import uuid
from contextlib import asynccontextmanager

import pytest
from fastapi import HTTPException

from ly_next.api import runs_api
from ly_next.core.run_lifecycle import finish_observed_run, start_observed_run
from ly_next.core.run_store import clear_memory_runs_for_tests, get_run_store
from ly_next.core.run_telemetry import (
    emit_run_event,
    record_llm_call_start,
    record_llm_usage_from_chat_response,
    set_run_loop_kind,
)


@pytest.fixture(autouse=True)
def _clear_runs():
    clear_memory_runs_for_tests()
    yield
    clear_memory_runs_for_tests()


@pytest.mark.asyncio
async def test_list_runs_returns_memory_rows():
    run_id = str(uuid.uuid4())
    store = get_run_store()
    await store.start_run(run_id, mode="react")
    await store.finish_run(
        run_id,
        status="ok",
        snapshot={"llm_calls": 1, "total_tokens": 10, "tools": []},
        loop_kind="native",
        events=[{"seq": 1, "kind": "llm_end", "payload": {}}],
    )

    result = await runs_api.list_runs(limit=10)
    assert result["count"] >= 1
    assert any(r["run_id"] == run_id for r in result["runs"])


@pytest.mark.asyncio
async def test_get_run_and_events():
    run_id = str(uuid.uuid4())
    store = get_run_store()
    await store.start_run(run_id, mode="plan", router={"provider": "openai"})
    await store.finish_run(
        run_id,
        status="error",
        snapshot={},
        loop_kind="plan",
        events=[
            {"seq": 1, "kind": "llm_start", "payload": {"model": "gpt-4o-mini"}},
            {"seq": 2, "kind": "tool_end", "payload": {"tool": "calculator"}},
        ],
        error="boom",
    )

    row = await runs_api.get_run_detail(run_id)
    assert row["status"] == "error"
    assert row["loop_kind"] == "plan"
    assert row["error"] == "boom"

    ev = await runs_api.list_run_events(run_id)
    assert ev["count"] == 2
    kinds = {e["kind"] for e in ev["events"]}
    assert "llm_start" in kinds
    assert "tool_end" in kinds


@pytest.mark.asyncio
async def test_runs_api_404_when_disabled(monkeypatch):
    monkeypatch.setattr(runs_api, "observability_enabled", lambda: False)
    with pytest.raises(HTTPException) as exc:
        await runs_api.list_runs()
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_get_run_not_found():
    with pytest.raises(HTTPException) as exc:
        await runs_api.get_run_detail(str(uuid.uuid4()))
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_chat_lifecycle_produces_llm_events():
    run_id = str(uuid.uuid4())
    token = await start_observed_run(run_id, mode="react", thread_id="thread-1")
    set_run_loop_kind("compat")
    record_llm_call_start(model="gpt-4o-mini", messages_count=3)
    record_llm_usage_from_chat_response(
        {
            "model": "gpt-4o-mini",
            "usage": {"prompt_tokens": 5, "completion_tokens": 2, "total_tokens": 7},
        }
    )
    emit_run_event("tool_end", {"tool": "calculator", "success": True, "elapsed_ms": 12})

    await finish_observed_run(token, run_id, status="ok")

    events = await get_run_store().get_events(run_id)
    kinds = [e["kind"] for e in events]
    assert "llm_start" in kinds
    assert "llm_end" in kinds
    assert "tool_end" in kinds

    row = await get_run_store().get_run(run_id)
    assert row is not None
    assert row["loop_kind"] == "compat"
    assert row["thread_id"] == "thread-1"


@pytest.mark.asyncio
async def test_finish_run_db_failure_does_not_raise(monkeypatch):
    run_id = str(uuid.uuid4())
    store = get_run_store()
    await store.start_run(run_id, mode="react")

    @asynccontextmanager
    async def _fail_session():
        raise RuntimeError("db down")
        yield  # pragma: no cover

    monkeypatch.setattr("ly_next.core.run_store.db._engine", object())
    monkeypatch.setattr("ly_next.core.run_store.db.session", _fail_session)

    await store.finish_run(
        run_id,
        status="ok",
        snapshot={"llm_calls": 0, "tools": []},
        loop_kind="native",
        events=[{"seq": 1, "kind": "status", "payload": {}}],
    )
    row = await store.get_run(run_id)
    assert row is not None
    assert row["status"] == "ok"
