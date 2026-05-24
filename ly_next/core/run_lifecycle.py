from __future__ import annotations

from contextvars import Token
from typing import Any

from ly_next.core.observability import observability_enabled
from ly_next.core.run_store import get_run_store
from ly_next.core.run_telemetry import (
    begin_run,
    end_run,
    get_public_snapshot,
    get_run_events,
    get_run_loop_kind,
)


async def start_observed_run(
    task_id: str,
    *,
    mode: str = "react",
    thread_id: str | None = None,
    router: dict[str, Any] | None = None,
) -> Token:
    token = begin_run(task_id, mode=mode, router=router)
    if observability_enabled():
        await get_run_store().start_run(task_id, mode=mode, thread_id=thread_id, router=router)
    return token


async def finish_observed_run(
    token: Token | None,
    task_id: str,
    *,
    status: str,
    error: str | None = None,
) -> dict[str, Any] | None:
    snap = get_public_snapshot()
    if observability_enabled():
        await get_run_store().finish_run(
            task_id,
            status=status,
            snapshot=snap,
            loop_kind=get_run_loop_kind(),
            events=get_run_events(),
            error=error,
        )
    end_run(token)
    return snap
