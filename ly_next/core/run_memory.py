from __future__ import annotations

from typing import Any

MAX_MEM_RUNS = 200
FIELD_MAX_LEN = 32

runs: dict[str, dict[str, Any]] = {}
events: dict[str, list[dict[str, Any]]] = {}


def normalize_field(value: str | None, *, max_len: int = FIELD_MAX_LEN) -> str | None:
    if not value:
        return None
    trimmed = value[:max_len]
    return trimmed or None


def evict_oldest() -> None:
    overflow = len(runs) - MAX_MEM_RUNS
    if overflow <= 0:
        return
    finished = sorted(
        ((rid, row) for rid, row in runs.items() if row.get("ended_at")),
        key=lambda item: item[1].get("started_at") or "",
    )
    running = sorted(
        ((rid, row) for rid, row in runs.items() if not row.get("ended_at")),
        key=lambda item: item[1].get("started_at") or "",
    )
    for run_id, _ in (finished + running)[:overflow]:
        runs.pop(run_id, None)
        events.pop(run_id, None)


def patch_loop_kind(run_id: str, loop_kind: str) -> None:
    row = runs.get(run_id)
    if row is not None:
        row["loop_kind"] = normalize_field(loop_kind)


def clear_for_tests() -> None:
    runs.clear()
    events.clear()
