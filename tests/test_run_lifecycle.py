from __future__ import annotations

import uuid

import pytest

from ly_next.core.run_lifecycle import finish_observed_run, start_observed_run
from ly_next.core.run_store import clear_memory_runs_for_tests, get_run_store
from ly_next.core.run_telemetry import emit_run_event, get_public_snapshot, set_run_loop_kind


@pytest.fixture(autouse=True)
def _clear_runs():
    clear_memory_runs_for_tests()
    yield
    clear_memory_runs_for_tests()


@pytest.mark.asyncio
async def test_observed_run_lifecycle_persists_snapshot():
    run_id = str(uuid.uuid4())
    token = await start_observed_run(
        run_id, mode="react", router={"via": "test", "provider": "openai"}
    )
    set_run_loop_kind("native")
    emit_run_event("status", {"phase": "llm"})
    assert get_public_snapshot() is not None

    snap = await finish_observed_run(token, run_id, status="ok")
    assert snap is not None
    assert snap["loop_kind"] == "native"
    assert get_public_snapshot() is None

    row = await get_run_store().get_run(run_id)
    assert row is not None
    assert row["status"] == "ok"
    assert row["loop_kind"] == "native"
    assert row["router"].get("via") == "test"

    events = await get_run_store().get_events(run_id)
    assert any(e["kind"] == "status" for e in events)


@pytest.mark.asyncio
async def test_finish_observed_run_always_clears_telemetry():
    run_id = str(uuid.uuid4())
    token = await start_observed_run(run_id, mode="chat")
    await finish_observed_run(token, run_id, status="error", error="boom")
    assert get_public_snapshot() is None
