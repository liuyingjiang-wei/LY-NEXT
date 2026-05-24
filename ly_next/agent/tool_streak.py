from __future__ import annotations

import json
from typing import Any


def tool_call_signature(tool_name: str, args: Any) -> str:
    return json.dumps({"name": tool_name, "args": args}, sort_keys=True, ensure_ascii=False)


def streak_after_tool_call(
    state: dict[str, Any],
    tool_name: str,
    args: Any,
    result: Any,
) -> dict[str, int]:
    sig = tool_call_signature(tool_name, args)
    prev_sig = str(state.get("last_tool_signature") or "")
    repeat = int(state.get("repeat_tool_calls") or 0)
    repeat = repeat + 1 if sig == prev_sig else 1

    fail_streak = int(state.get("tool_fail_streak") or 0)
    if isinstance(result, dict) and result.get("success") is False:
        fail_streak += 1
    else:
        fail_streak = 0

    return {
        "last_tool_signature": sig,
        "repeat_tool_calls": repeat,
        "tool_fail_streak": fail_streak,
    }


def streak_after_tool_error(state: dict[str, Any], tool_name: str, args: Any) -> dict[str, int]:
    sig = tool_call_signature(tool_name, args)
    prev_sig = str(state.get("last_tool_signature") or "")
    repeat = int(state.get("repeat_tool_calls") or 0)
    repeat = repeat + 1 if sig == prev_sig else 1
    return {
        "last_tool_signature": sig,
        "repeat_tool_calls": repeat,
        "tool_fail_streak": int(state.get("tool_fail_streak") or 0) + 1,
    }
