"""Task manager: PostgreSQL persistence when DB is connected, else in-process memory."""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

from ly_next.core.database import Task as TaskRow
from ly_next.core.database import db
from ly_next.core.logger import get_logger

logger = get_logger(__name__)


class TaskEntry(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    id: str
    name: str
    status: str = "pending"
    created_at: datetime
    started_at: datetime | None = None
    ended_at: datetime | None = None
    progress: float = 0.0
    message: str = ""
    result: Any | None = None
    error: str | None = None


def _row_to_entry(row: TaskRow) -> TaskEntry:
    return TaskEntry(
        id=str(row.id),
        name=row.name,
        status=row.status or "pending",
        created_at=row.created_at,
        started_at=row.started_at,
        ended_at=row.ended_at,
        progress=float(row.progress or 0),
        message=row.message or "",
        result=row.result,
        error=row.error,
    )


class TaskManager:
    def __init__(self) -> None:
        self._stop_flags: dict[str, asyncio.Event] = {}
        self._mem_tasks: dict[str, TaskEntry] = {}
        self._mem_flags: dict[str, asyncio.Event] = {}

    def _db_ready(self) -> bool:
        return getattr(db, "_engine", None) is not None

    def _event(self, task_id: str) -> asyncio.Event:
        if self._db_ready():
            if task_id not in self._stop_flags:
                self._stop_flags[task_id] = asyncio.Event()
            return self._stop_flags[task_id]
        if task_id not in self._mem_flags:
            self._mem_flags[task_id] = asyncio.Event()
        return self._mem_flags[task_id]

    def _forget_flag(self, task_id: str) -> None:
        self._stop_flags.pop(task_id, None)
        self._mem_flags.pop(task_id, None)

    async def create_task(self, name: str, metadata: dict | None = None) -> str:
        if self._db_ready():
            try:
                row = await db.create_task(name, metadata or {})
                tid = str(row.id)
                self._event(tid)
                return tid
            except Exception as e:
                logger.warning("Task create DB failed, using memory: %s", e)
        tid = str(uuid.uuid4())
        entry = TaskEntry(id=tid, name=name, created_at=datetime.now())
        if metadata:
            for k, v in metadata.items():
                if hasattr(entry, k):
                    setattr(entry, k, v)
        self._mem_tasks[tid] = entry
        self._event(tid)
        return tid

    async def get_task(self, task_id: str) -> TaskEntry | None:
        if self._db_ready():
            try:
                row = await db.get_task_row(task_id)
                if row:
                    return _row_to_entry(row)
            except Exception as e:
                logger.warning("Task get DB failed: %s", e)
        return self._mem_tasks.get(task_id)

    async def update(
        self,
        task_id: str,
        status: str | None = None,
        progress: float | None = None,
        message: str | None = None,
        result: Any = None,
        error: str | None = None,
    ) -> bool:
        if self._db_ready():
            try:
                row = await db.update_task(
                    task_id,
                    status=status,
                    progress=progress,
                    result=result,
                    error=error,
                    message=message,
                )
                return row is not None
            except Exception as e:
                logger.warning("Task update DB failed: %s", e)
        task = self._mem_tasks.get(task_id)
        if not task:
            return False
        if status:
            task.status = status
            if status == "running" and not task.started_at:
                task.started_at = datetime.now()
            elif status in ("completed", "failed", "stopped"):
                task.ended_at = datetime.now()
        if progress is not None:
            task.progress = max(0.0, min(1.0, progress))
        if message is not None:
            task.message = message
        if result is not None:
            task.result = result
        if error is not None:
            task.error = error
        return True

    async def complete(self, task_id: str, result: Any = None) -> bool:
        return await self.update(task_id, status="completed", result=result, progress=1.0)

    async def fail(self, task_id: str, error: str) -> bool:
        return await self.update(task_id, status="failed", error=error)

    async def stop(self, task_id: str) -> bool:
        if self._db_ready():
            try:
                row = await db.get_task_row(task_id)
                if not row:
                    return False
                await db.update_task(task_id, status="stopped")
                self._event(task_id).set()
                return True
            except Exception as e:
                logger.warning("Task stop DB failed: %s", e)
        task = self._mem_tasks.get(task_id)
        if not task:
            return False
        task.status = "stopped"
        task.ended_at = datetime.now()
        self._event(task_id).set()
        return True

    def get_stop_event(self, task_id: str) -> asyncio.Event:
        return self._event(str(task_id))

    def is_stopped(self, task_id: str) -> bool:
        ev = self._stop_flags.get(task_id) or self._mem_flags.get(task_id)
        return ev.is_set() if ev else False

    async def wait_for_stop(self, task_id: str, timeout: float | None = None) -> bool:
        ev = self._event(task_id)
        try:
            if timeout is not None:
                await asyncio.wait_for(ev.wait(), timeout=timeout)
            else:
                await ev.wait()
            return True
        except asyncio.TimeoutError:
            return False

    async def delete(self, task_id: str) -> bool:
        if self._db_ready():
            try:
                ok = await db.delete_task_row(task_id)
                self._forget_flag(task_id)
                return ok
            except Exception as e:
                logger.warning("Task delete DB failed: %s", e)
        existed = task_id in self._mem_tasks
        self._mem_tasks.pop(task_id, None)
        self._forget_flag(task_id)
        return existed

    async def list_tasks(self, status: str | None = None, limit: int = 100) -> list[TaskEntry]:
        if self._db_ready():
            try:
                rows = await db.list_tasks(status=status, limit=limit)
                return [_row_to_entry(r) for r in rows]
            except Exception as e:
                logger.warning("Task list DB failed, memory only: %s", e)
        tasks = list(self._mem_tasks.values())
        if status:
            tasks = [t for t in tasks if t.status == status]
        tasks.sort(key=lambda t: t.created_at, reverse=True)
        return tasks[:limit]

    async def clear_completed(self) -> int:
        if self._db_ready():
            try:
                return await db.clear_tasks_by_status(("completed", "failed", "stopped"))
            except Exception as e:
                logger.warning("Task clear DB failed: %s", e)
        to_delete = [
            tid
            for tid, t in self._mem_tasks.items()
            if t.status in ("completed", "failed", "stopped")
        ]
        for tid in to_delete:
            self._mem_tasks.pop(tid, None)
            self._forget_flag(tid)
        return len(to_delete)


_task_manager: TaskManager | None = None


def get_task_manager() -> TaskManager:
    global _task_manager
    if _task_manager is None:
        _task_manager = TaskManager()
    return _task_manager
