from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ly_next.core.thread_persistence import (
    create_thread,
    delete_thread,
    get_thread,
    list_thread_messages,
    list_threads,
    patch_thread_metadata,
    persistence_active,
    persistence_enabled,
)

router = APIRouter(prefix="/threads", tags=["threads"])


class ThreadCreateRequest(BaseModel):
    name: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ThreadPatchRequest(BaseModel):
    metadata: dict[str, Any] = Field(default_factory=dict)


def _require_persistence() -> None:
    if not persistence_enabled():
        raise HTTPException(
            status_code=503,
            detail="Thread persistence is disabled (agent.persistence.enabled=false)",
        )
    if not persistence_active():
        raise HTTPException(
            status_code=503,
            detail="Database unavailable — thread persistence requires PostgreSQL",
        )


@router.post("")
async def create_thread_endpoint(body: ThreadCreateRequest):
    _require_persistence()
    return await create_thread(name=body.name, metadata=body.metadata)


@router.get("")
async def list_threads_endpoint(limit: int = 100, status: str | None = "active"):
    if not persistence_enabled():
        return {"threads": [], "count": 0, "persistence": False}
    if not persistence_active():
        return {"threads": [], "count": 0, "persistence": False, "database": False}
    rows = await list_threads(limit=limit, status=status)
    return {"threads": rows, "count": len(rows), "persistence": True}


@router.get("/{thread_id}")
async def get_thread_endpoint(thread_id: str):
    _require_persistence()
    row = await get_thread(thread_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Thread not found")
    return row


@router.patch("/{thread_id}")
async def patch_thread_endpoint(thread_id: str, body: ThreadPatchRequest):
    _require_persistence()
    if not isinstance(body.metadata, dict):
        raise HTTPException(status_code=400, detail="metadata must be an object")
    row = await patch_thread_metadata(thread_id, body.metadata)
    if row is None:
        raise HTTPException(status_code=404, detail="Thread not found")
    return row


@router.get("/{thread_id}/messages")
async def get_thread_messages_endpoint(thread_id: str, limit: int | None = None):
    _require_persistence()
    row = await get_thread(thread_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Thread not found")
    messages = await list_thread_messages(thread_id, limit=limit, include_metadata=True)
    return {"thread_id": row["thread_id"], "messages": messages, "count": len(messages)}


@router.delete("/{thread_id}")
async def delete_thread_endpoint(thread_id: str):
    _require_persistence()
    ok = await delete_thread(thread_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Thread not found")
    return {"success": True, "thread_id": thread_id}
