from __future__ import annotations

import uuid

import pytest

from ly_next.core import run_memory
from ly_next.core.run_store import (
    _MAX_MEM_RUNS,
    clear_memory_runs_for_tests,
    get_run_store,
    patch_memory_run_loop_kind,
)
from ly_next.core.run_telemetry import (
    begin_run,
    emit_run_event,
    end_run,
    get_run_events,
    set_run_loop_kind,
)


@pytest.fixture(autouse=True)
def _clear_runs():
    clear_memory_runs_for_tests()
    yield
    clear_memory_runs_for_tests()


@pytest.mark.asyncio
async def test_run_store_memory_roundtrip():
    run_id = str(uuid.uuid4())
    store = get_run_store()
    await store.start_run(run_id, mode="react", router={"provider": "openai"})
    tok = begin_run(run_id, mode="react")
    try:
        set_run_loop_kind("native")
        emit_run_event("status", {"phase": "llm"})
        emit_run_event("tool_end", {"tool": "calculator", "success": True})
        events = get_run_events()
    finally:
        end_run(tok)

    await store.finish_run(
        run_id,
        status="ok",
        snapshot={
            "llm_calls": 1,
            "prompt_tokens": 10,
            "completion_tokens": 5,
            "total_tokens": 15,
            "tools": [],
        },
        loop_kind="native",
        events=events,
    )

    row = await store.get_run(run_id)
    assert row is not None
    assert row["status"] == "ok"
    assert row["loop_kind"] == "native"
    assert row["usage"]["total_tokens"] == 15

    events = await store.get_events(run_id)
    assert len(events) >= 2
    kinds = {e["kind"] for e in events}
    assert "status" in kinds
    assert "tool_end" in kinds


@pytest.mark.asyncio
async def test_list_runs_memory():
    store = get_run_store()
    rid = str(uuid.uuid4())
    await store.start_run(rid, mode="chat")
    await store.finish_run(
        rid,
        status="ok",
        snapshot={},
        loop_kind="chat",
        events=[],
    )
    runs = await store.list_runs(limit=10)
    assert any(r["run_id"] == rid for r in runs)


@pytest.mark.asyncio
async def test_patch_memory_run_loop_kind():
    run_id = str(uuid.uuid4())
    store = get_run_store()
    await store.start_run(run_id, mode="react")
    patch_memory_run_loop_kind(run_id, "compat")
    row = await store.get_run(run_id)
    assert row is not None
    assert row["loop_kind"] == "compat"


@pytest.mark.asyncio
async def test_memory_eviction():
    store = get_run_store()
    for _i in range(_MAX_MEM_RUNS + 5):
        rid = str(uuid.uuid4())
        await store.start_run(rid, mode="react")
        await store.finish_run(
            rid,
            status="ok",
            snapshot={},
            loop_kind="native",
            events=[],
        )
    from ly_next.core.run_store import _MEM_RUNS

    assert len(_MEM_RUNS) <= _MAX_MEM_RUNS


@pytest.mark.asyncio
async def test_eviction_prefers_finished_runs():
    store = get_run_store()
    running_id = str(uuid.uuid4())
    await store.start_run(running_id, mode="react")

    for _ in range(_MAX_MEM_RUNS):
        rid = str(uuid.uuid4())
        await store.start_run(rid, mode="react")
        await store.finish_run(
            rid,
            status="ok",
            snapshot={},
            loop_kind="native",
            events=[],
        )

    overflow_id = str(uuid.uuid4())
    await store.start_run(overflow_id, mode="react")
    await store.finish_run(
        overflow_id,
        status="ok",
        snapshot={},
        loop_kind="native",
        events=[],
    )

    from ly_next.core.run_store import _MEM_RUNS

    assert running_id in _MEM_RUNS
    assert len(_MEM_RUNS) <= _MAX_MEM_RUNS


@pytest.mark.asyncio
async def test_get_events_returns_empty_memory_list_without_db():
    run_id = str(uuid.uuid4())
    store = get_run_store()
    await store.start_run(run_id, mode="react")
    await store.finish_run(
        run_id,
        status="ok",
        snapshot={},
        loop_kind="native",
        events=[],
    )
    events = await store.get_events(run_id)
    assert events == []


@pytest.mark.asyncio
async def test_emit_run_event_syncs_to_memory_during_run():
    run_id = str(uuid.uuid4())
    store = get_run_store()
    await store.start_run(run_id, mode="react")
    tok = begin_run(run_id, mode="react")
    try:
        emit_run_event("status", {"phase": "llm"})
    finally:
        end_run(tok)

    assert run_id in run_memory.events
    mem_events = await store.get_events(run_id)
    assert len(mem_events) == 1
    assert mem_events[0]["kind"] == "status"


@pytest.mark.asyncio
async def test_finish_run_replaces_events_not_appends():
    run_id = str(uuid.uuid4())
    store = get_run_store()
    await store.start_run(run_id, mode="react")
    await store.finish_run(
        run_id,
        status="ok",
        snapshot={},
        loop_kind="native",
        events=[{"seq": 1, "kind": "a", "payload": {}}],
    )
    await store.finish_run(
        run_id,
        status="ok",
        snapshot={},
        loop_kind="native",
        events=[{"seq": 1, "kind": "b", "payload": {}}],
    )
    events = await store.get_events(run_id)
    assert len(events) == 1
    assert events[0]["kind"] == "b"
