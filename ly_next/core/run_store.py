from __future__ import annotations

import contextlib
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import delete, desc, select

from ly_next.core import run_memory
from ly_next.core.database import AgentRun, AgentRunEvent, db
from ly_next.core.logger import get_logger
from ly_next.core.observability import (
    clamp_runs_query_limit,
    max_events_per_run,
    observability_enabled,
    observability_persist,
)
from ly_next.core.run_telemetry import persisted_usage_from_snapshot

logger = get_logger(__name__)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _parse_run_uuid(run_id: str) -> UUID | None:
    try:
        return UUID(run_id)
    except ValueError:
        return None


def _persist_ready(run_id: str) -> UUID | None:
    if not observability_persist() or db._engine is None:
        return None
    return _parse_run_uuid(run_id)


def _parse_started_at(raw: Any) -> datetime | None:
    if not isinstance(raw, str) or not raw:
        return None
    with contextlib.suppress(ValueError):
        return datetime.fromisoformat(raw)
    return None


def _public_run(row: AgentRun | dict[str, Any]) -> dict[str, Any]:
    if isinstance(row, AgentRun):
        return {
            "run_id": str(row.id),
            "task_id": row.task_id,
            "thread_id": row.thread_id,
            "mode": row.mode,
            "loop_kind": row.loop_kind,
            "status": row.status,
            "router": dict(row.router_ or {}),
            "usage": dict(row.usage_ or {}),
            "error": row.error,
            "started_at": row.started_at.isoformat() if row.started_at else None,
            "ended_at": row.ended_at.isoformat() if row.ended_at else None,
        }
    run_id = str(row.get("id") or row.get("task_id") or "")
    return {
        "run_id": run_id,
        "task_id": str(row.get("task_id") or row.get("id") or ""),
        "thread_id": row.get("thread_id"),
        "mode": row.get("mode"),
        "loop_kind": row.get("loop_kind"),
        "status": row.get("status"),
        "router": dict(row.get("router") or {}),
        "usage": dict(row.get("usage") or {}),
        "error": row.get("error"),
        "started_at": row.get("started_at"),
        "ended_at": row.get("ended_at"),
    }


def _merge_run_lists(
    db_rows: list[dict[str, Any]], mem_rows: list[dict[str, Any]], limit: int
) -> list[dict[str, Any]]:
    by_id = {str(r.get("run_id") or ""): r for r in db_rows if r.get("run_id")}
    for row in mem_rows:
        rid = str(row.get("run_id") or "")
        if rid:
            by_id[rid] = row
    merged = sorted(by_id.values(), key=lambda r: r.get("started_at") or "", reverse=True)
    return merged[:limit]


def _event_dict(ev: AgentRunEvent) -> dict[str, Any]:
    return {
        "seq": ev.seq,
        "kind": ev.kind,
        "payload": dict(ev.payload_ or {}),
        "created_at": ev.created_at.isoformat() if ev.created_at else None,
    }


def _status_value(status: str) -> str:
    return (status or "error")[: run_memory.FIELD_MAX_LEN]


def _agent_run_from_memory(
    run_uuid: UUID, run_id: str, mem: dict[str, Any], status: str
) -> AgentRun:
    row = AgentRun(
        id=run_uuid,
        task_id=run_id,
        thread_id=mem.get("thread_id"),
        mode=mem.get("mode", "react"),
        status=_status_value(status),
        router_=dict(mem.get("router") or {}),
    )
    started = _parse_started_at(mem.get("started_at"))
    if started is not None:
        row.started_at = started
    return row


class RunStore:
    async def start_run(
        self,
        run_id: str,
        *,
        mode: str = "react",
        thread_id: str | None = None,
        router: dict[str, Any] | None = None,
    ) -> None:
        if not observability_enabled():
            return
        normalized_mode = run_memory.normalize_field(mode or "react") or "react"
        run_memory.runs[run_id] = {
            "id": run_id,
            "task_id": run_id,
            "thread_id": thread_id,
            "mode": normalized_mode,
            "loop_kind": None,
            "status": "running",
            "router": router or {},
            "usage": {},
            "error": None,
            "started_at": _utcnow().isoformat(),
            "ended_at": None,
        }
        run_memory.evict_oldest()

        run_uuid = _persist_ready(run_id)
        if run_uuid is None:
            return
        try:
            async with db.session() as session:
                session.add(
                    AgentRun(
                        id=run_uuid,
                        task_id=run_id,
                        thread_id=thread_id,
                        mode=normalized_mode,
                        status="running",
                        router_=router or {},
                        usage_={},
                    )
                )
        except Exception as exc:
            logger.warning("[run_store] start_run DB failed: %s", exc)

    async def finish_run(
        self,
        run_id: str,
        *,
        status: str,
        snapshot: dict[str, Any] | None,
        loop_kind: str | None,
        events: list[dict[str, Any]],
        error: str | None = None,
    ) -> None:
        if not observability_enabled():
            return
        ended = _utcnow()
        usage = persisted_usage_from_snapshot(snapshot)
        mem = run_memory.runs.setdefault(run_id, {"id": run_id, "task_id": run_id})
        mem.update(
            {
                "status": _status_value(status),
                "loop_kind": run_memory.normalize_field(loop_kind or ""),
                "usage": usage,
                "error": error,
                "ended_at": ended.isoformat(),
            }
        )
        capped = events[: max_events_per_run()]
        run_memory.events[run_id] = list(capped)
        run_memory.evict_oldest()

        run_uuid = _persist_ready(run_id)
        if run_uuid is None:
            return
        try:
            async with db.session() as session:
                result = await session.execute(select(AgentRun).where(AgentRun.id == run_uuid))
                run_row = result.scalar_one_or_none()
                if run_row is None:
                    run_row = _agent_run_from_memory(run_uuid, run_id, mem, status)
                    session.add(run_row)
                run_row.status = _status_value(status)
                run_row.loop_kind = run_memory.normalize_field(loop_kind or "")
                run_row.usage_ = usage
                run_row.error = error
                run_row.ended_at = ended
                await session.execute(delete(AgentRunEvent).where(AgentRunEvent.run_id == run_uuid))
                session.add_all(
                    AgentRunEvent(
                        run_id=run_uuid,
                        seq=int(ev.get("seq", 0)),
                        kind=str(ev.get("kind", "event"))[:64],
                        payload_=dict(ev.get("payload") or {}),
                    )
                    for ev in capped
                )
        except Exception as exc:
            logger.warning("[run_store] finish_run DB failed: %s", exc)

    async def get_run(self, run_id: str) -> dict[str, Any] | None:
        mem = run_memory.runs.get(run_id)
        if mem is not None:
            return _public_run(mem)
        run_uuid = _parse_run_uuid(run_id)
        if run_uuid is None or db._engine is None:
            return None
        try:
            async with db.session() as session:
                result = await session.execute(select(AgentRun).where(AgentRun.id == run_uuid))
                row = result.scalar_one_or_none()
                return _public_run(row) if row else None
        except Exception as exc:
            logger.warning("[run_store] get_run DB failed: %s", exc)
            return None

    async def list_runs(
        self, *, status: str | None = None, limit: int = 50
    ) -> list[dict[str, Any]]:
        limit = clamp_runs_query_limit(limit)
        db_rows: list[dict[str, Any]] = []
        if db._engine is not None:
            try:
                async with db.session() as session:
                    query = select(AgentRun).order_by(desc(AgentRun.started_at)).limit(limit)
                    if status:
                        query = query.where(AgentRun.status == status)
                    result = await session.execute(query)
                    db_rows = [_public_run(row) for row in result.scalars().all()]
            except Exception as exc:
                logger.warning("[run_store] list_runs DB failed: %s", exc)

        mem_items = run_memory.runs.values()
        if status:
            mem_items = [row for row in mem_items if row.get("status") == status]
        mem_rows = [_public_run(row) for row in mem_items]
        if not db_rows and not mem_rows:
            return []
        return _merge_run_lists(db_rows, mem_rows, limit)

    async def get_events(self, run_id: str) -> list[dict[str, Any]]:
        if run_id in run_memory.events:
            return list(run_memory.events[run_id])
        run_uuid = _parse_run_uuid(run_id)
        if run_uuid is None or db._engine is None:
            return []
        try:
            async with db.session() as session:
                result = await session.execute(
                    select(AgentRunEvent)
                    .where(AgentRunEvent.run_id == run_uuid)
                    .order_by(AgentRunEvent.seq)
                )
                return [_event_dict(ev) for ev in result.scalars().all()]
        except Exception as exc:
            logger.warning("[run_store] get_events DB failed: %s", exc)
            return []


_run_store: RunStore | None = None


def get_run_store() -> RunStore:
    global _run_store
    if _run_store is None:
        _run_store = RunStore()
    return _run_store


def patch_memory_run_loop_kind(run_id: str, loop_kind: str) -> None:
    run_memory.patch_loop_kind(run_id, loop_kind)


def clear_memory_runs_for_tests() -> None:
    run_memory.clear_for_tests()


_MAX_MEM_RUNS = run_memory.MAX_MEM_RUNS
_MEM_RUNS = run_memory.runs
_MEM_EVENTS = run_memory.events
