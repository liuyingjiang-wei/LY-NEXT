from fastapi import APIRouter, HTTPException

from ly_next.core.observability import clamp_runs_query_limit, observability_enabled
from ly_next.core.run_store import get_run_store

router = APIRouter(tags=["runs"])


def _require_observability() -> None:
    if not observability_enabled():
        raise HTTPException(status_code=404, detail="Observability disabled")


@router.get("/runs")
async def list_runs(status: str | None = None, limit: int = 50):
    _require_observability()
    runs = await get_run_store().list_runs(status=status, limit=clamp_runs_query_limit(limit))
    return {"runs": runs, "count": len(runs)}


@router.get("/runs/{run_id}")
async def get_run_detail(run_id: str):
    _require_observability()
    row = await get_run_store().get_run(run_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return row


@router.get("/runs/{run_id}/events")
async def list_run_events(run_id: str):
    _require_observability()
    store = get_run_store()
    if await store.get_run(run_id) is None:
        raise HTTPException(status_code=404, detail="Run not found")
    events = await store.get_events(run_id)
    return {"run_id": run_id, "events": events, "count": len(events)}
