from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from ly_next.core.task_manager import TaskEntry, TaskManager


@pytest.fixture
def manager(monkeypatch):
    mgr = TaskManager()
    monkeypatch.setattr(mgr, "_db_ready", lambda: True)
    return mgr


@pytest.mark.asyncio
async def test_update_falls_back_to_memory_when_db_row_missing(manager, monkeypatch):
    monkeypatch.setattr(
        "ly_next.core.task_manager.db.update_task",
        AsyncMock(return_value=None),
    )
    tid = "mem-task-1"
    manager._mem_tasks[tid] = TaskEntry(
        id=tid,
        name="WebSocket Chat",
        status="pending",
        created_at=datetime.now(),
    )

    ok = await manager.update(tid, status="running")

    assert ok is True
    assert manager._mem_tasks[tid].status == "running"


@pytest.mark.asyncio
async def test_list_tasks_merges_memory_with_db(manager, monkeypatch):
    db_row = MagicMock()
    db_row.id = "db-task-1"
    db_row.name = "DB Task"
    db_row.status = "completed"
    db_row.created_at = datetime(2026, 1, 1, 12, 0, 0)
    db_row.started_at = None
    db_row.ended_at = None
    db_row.progress = 1.0
    db_row.message = ""
    db_row.result = "ok"
    db_row.error = None

    monkeypatch.setattr(
        "ly_next.core.task_manager.db.list_tasks",
        AsyncMock(return_value=[db_row]),
    )

    mem_id = "mem-task-2"
    manager._mem_tasks[mem_id] = TaskEntry(
        id=mem_id,
        name="WebSocket Chat",
        status="running",
        created_at=datetime(2026, 6, 6, 12, 0, 0),
    )

    tasks = await manager.list_tasks()

    ids = {t.id for t in tasks}
    assert "db-task-1" in ids
    assert mem_id in ids


@pytest.mark.asyncio
async def test_stop_falls_back_to_memory(manager, monkeypatch):
    monkeypatch.setattr(
        "ly_next.core.task_manager.db.get_task_row",
        AsyncMock(return_value=None),
    )
    tid = "mem-stop-1"
    manager._mem_tasks[tid] = TaskEntry(
        id=tid,
        name="WebSocket Chat",
        status="running",
        created_at=datetime.now(),
    )

    ok = await manager.stop(tid)

    assert ok is True
    assert manager._mem_tasks[tid].status == "stopped"
