from __future__ import annotations

from typing import Any


def _blocks_from_content(content: Any) -> list[str]:
    if isinstance(content, str):
        return [content] if content.strip() else []
    if not isinstance(content, list):
        return [str(content)] if content is not None else []
    out: list[str] = []
    for block in content:
        if isinstance(block, str) and block.strip():
            out.append(block)
        elif isinstance(block, dict):
            t = block.get("text") or block.get("content")
            if isinstance(t, str) and t.strip():
                out.append(t)
    return out


def text_from_message(message: dict[str, Any] | None) -> str:
    if not message:
        return ""
    main = "\n".join(_blocks_from_content(message.get("content"))).strip()
    if main:
        return main
    for key in ("reasoning_content", "reasoning", "reasoning_text"):
        val = message.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    return ""


def text_from_chat_response(response: dict[str, Any]) -> str:
    choices = response.get("choices")
    if not isinstance(choices, list) or not choices:
        return ""
    first = choices[0]
    if not isinstance(first, dict):
        return ""
    msg = first.get("message")
    return text_from_message(msg if isinstance(msg, dict) else {})


def text_from_stream_delta(delta: dict[str, Any] | None) -> str:
    if not delta:
        return ""
    parts = _blocks_from_content(delta.get("content"))
    if not parts:
        for key in ("reasoning_content", "reasoning"):
            val = delta.get(key)
            if isinstance(val, str) and val:
                parts.append(val)
    return "".join(parts)
