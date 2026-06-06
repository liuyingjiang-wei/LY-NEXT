from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from ly_next.core.thread_persistence import get_message_by_id, persistence_active
from ly_next.messaging.image_handler import parse_image_tags
from ly_next.tools.image_stats import get_tool_stats

router = APIRouter(tags=["image"])


@router.get("/messages/{message_id}/images")
async def get_message_images(message_id: str) -> dict[str, Any]:
    if not persistence_active():
        raise HTTPException(status_code=503, detail="Database persistence unavailable")
    row = await get_message_by_id(message_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Message not found")

    meta = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
    urls: list[str] = []
    seen: set[str] = set()

    for u in meta.get("image_urls") or []:
        if isinstance(u, str) and u.strip() and u not in seen:
            seen.add(u)
            urls.append(u.strip())

    mixed = meta.get("mixed_message")
    if isinstance(mixed, dict):
        for part in mixed.get("parts") or []:
            if isinstance(part, dict) and part.get("type") == "image":
                u = str(part.get("content") or "").strip()
                if u and u not in seen:
                    seen.add(u)
                    urls.append(u)

    content = row.get("content")
    if isinstance(content, str):
        _, tagged = parse_image_tags(content)
        for u in tagged:
            if u not in seen:
                seen.add(u)
                urls.append(u)

    return {
        "message_id": message_id,
        "image_urls": urls,
        "count": len(urls),
    }


@router.get("/tools/image/stats")
async def get_image_tool_stats() -> dict[str, Any]:
    stats = await get_tool_stats()
    return {"tools": stats}
