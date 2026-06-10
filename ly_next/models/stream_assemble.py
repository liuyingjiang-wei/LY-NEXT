from __future__ import annotations

import json
from typing import Any


def try_parse_tool_arguments(raw: str) -> dict[str, Any] | None:
    """Return parsed args when the streamed JSON object is complete."""
    text = (raw or "").strip()
    if not text:
        return None
    try:
        obj = json.loads(text)
    except json.JSONDecodeError:
        return None
    return obj if isinstance(obj, dict) else {}


def is_tool_call_sealed(tool_call: dict[str, Any]) -> bool:
    """True when name is known and arguments JSON has sealed."""
    fn = tool_call.get("function") if isinstance(tool_call.get("function"), dict) else {}
    name = str(fn.get("name") or "").strip()
    if not name:
        return False
    return try_parse_tool_arguments(str(fn.get("arguments") or "")) is not None


def parse_sealed_tool_call(tool_call: dict[str, Any]) -> tuple[str, dict[str, Any], str] | None:
    """Extract (name, args, call_id) from a sealed tool_call block."""
    if not is_tool_call_sealed(tool_call):
        return None
    fn = tool_call.get("function") if isinstance(tool_call.get("function"), dict) else {}
    name = str(fn.get("name") or "").strip()
    args = try_parse_tool_arguments(str(fn.get("arguments") or "")) or {}
    call_id = str(tool_call.get("id") or "").strip() or f"call_{name}"
    return name, args, call_id


def accumulate_tool_call_delta(acc: dict[int, dict[str, Any]], tc: dict[str, Any]) -> None:
    idx = int(tc.get("index", 0))
    row = acc.setdefault(
        idx,
        {"id": "", "type": "function", "function": {"name": "", "arguments": ""}},
    )
    if tc.get("id"):
        row["id"] = str(tc["id"])
    fn = tc.get("function") if isinstance(tc.get("function"), dict) else {}
    if fn.get("name"):
        row["function"]["name"] = str(row["function"].get("name") or "") + str(fn["name"])
    if fn.get("arguments") is not None:
        row["function"]["arguments"] = str(row["function"].get("arguments") or "") + str(
            fn["arguments"]
        )


def build_chat_completion_from_stream(
    *,
    content: str,
    tool_calls: dict[int, dict[str, Any]],
    finish_reason: str | None,
    usage: dict[str, Any] | None = None,
) -> dict[str, Any]:
    message: dict[str, Any] = {"role": "assistant", "content": content or None}
    if tool_calls:
        ordered = [tool_calls[i] for i in sorted(tool_calls)]
        message["tool_calls"] = ordered
    choice: dict[str, Any] = {"message": message}
    if finish_reason:
        choice["finish_reason"] = finish_reason
    out: dict[str, Any] = {"choices": [choice]}
    if usage:
        out["usage"] = usage
    return out
