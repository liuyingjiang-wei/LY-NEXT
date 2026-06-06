from __future__ import annotations

from typing import Any


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
