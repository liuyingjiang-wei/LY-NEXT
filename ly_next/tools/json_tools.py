from __future__ import annotations

import json
import re
from typing import Any

from ly_next.tools.base import ToolResult, tool

_SEGMENT_RE = re.compile(r"[^.\[\]]+|\[\d+\]")


def _parse_segments(path: str) -> list[str | int]:
    raw = (path or "").strip()
    if not raw:
        return []
    return [int(seg[1:-1]) if seg.startswith("[") else seg for seg in _SEGMENT_RE.findall(raw)]


def _resolve_path(obj: Any, path: str) -> Any:
    cur = obj
    for seg in _parse_segments(path):
        if isinstance(seg, int):
            if not isinstance(cur, list) or seg < 0 or seg >= len(cur):
                raise KeyError(str(seg))
            cur = cur[seg]
            continue
        if isinstance(cur, dict) and seg in cur:
            cur = cur[seg]
            continue
        raise KeyError(str(seg))
    return cur


@tool(
    name="json_query",
    description=(
        "Extract a value from JSON using a dot/bracket path (e.g. items[0].name). "
        "Use on tool outputs or API responses instead of loading full blobs into context."
    ),
    category="safe",
    parameters={
        "type": "object",
        "properties": {
            "data": {"type": "string", "description": "JSON string"},
            "path": {
                "type": "string",
                "description": "Path such as field.sub[0].id",
            },
        },
        "required": ["data", "path"],
    },
)
async def json_query(data: str, path: str) -> ToolResult:
    try:
        parsed = json.loads(data or "")
    except json.JSONDecodeError as exc:
        return ToolResult(success=False, error=f"invalid JSON: {exc}")

    p = (path or "").strip()
    if not p:
        return ToolResult(success=False, error="path is required")

    try:
        value = _resolve_path(parsed, p)
    except (KeyError, IndexError, TypeError) as exc:
        return ToolResult(success=False, error=f"path not found: {exc}")

    return ToolResult(success=True, result={"path": p, "value": value})
