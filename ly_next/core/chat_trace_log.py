"""Human-readable INFO logs for web chat turns (aligned with workbench chat payloads)."""

from __future__ import annotations

import logging
from typing import Any

_PLAIN = logging.getLogger("ly_next")

_PREVIEW_LEN = 160
_MAX_MESSAGES = 8


def _clip(text: str, limit: int = _PREVIEW_LEN) -> str:
    s = " ".join(str(text or "").split())
    if len(s) <= limit:
        return s
    return s[: limit - 1] + "…"


def summarize_message_content(content: Any) -> str:
    """One-line preview of a chat message (string or multimodal parts)."""
    if content is None:
        return ""
    if isinstance(content, str):
        return _clip(content)
    if isinstance(content, list):
        parts: list[str] = []
        images = 0
        for block in content:
            if isinstance(block, str) and block.strip():
                parts.append(block.strip())
            elif isinstance(block, dict):
                btype = str(block.get("type") or "").lower()
                if btype in ("text", "input_text"):
                    t = block.get("text") or block.get("content")
                    if isinstance(t, str) and t.strip():
                        parts.append(t.strip())
                elif btype in ("image_url", "image", "input_image"):
                    images += 1
        text = _clip(" ".join(parts)) if parts else ""
        if images:
            suffix = f" [+{images} image{'s' if images > 1 else ''}]"
            return (text + suffix) if text else suffix.strip()
        return text
    return _clip(str(content))


def format_messages_for_log(
    messages: list[dict[str, Any]] | None,
    *,
    limit: int = _MAX_MESSAGES,
) -> list[str]:
    rows: list[str] = []
    for msg in (messages or [])[-limit:]:
        if not isinstance(msg, dict):
            continue
        role = str(msg.get("role") or "?").lower()
        preview = summarize_message_content(msg.get("content"))
        if not preview:
            preview = "(empty)"
        rows.append(f"{role}: {preview}")
    return rows


def _join_lines(lines: list[str]) -> str:
    return " │ ".join(lines) if lines else "—"


def chat_info(event: str, *, task_id: str | None = None, **fields: Any) -> None:
    """Log chat lifecycle at INFO using the standard console/file format (no extra ANSI)."""
    parts: list[str] = [f"[chat] {event}"]
    if task_id:
        parts.append(f"task={task_id}")
    for key, value in fields.items():
        if value is None:
            continue
        if key == "messages" and isinstance(value, list):
            lines = format_messages_for_log(value)
            parts.append(f"messages({len(value)})={_join_lines(lines)}")
        elif key == "client_messages" and isinstance(value, list):
            lines = format_messages_for_log(value)
            parts.append(f"client({len(value)})={_join_lines(lines)}")
        elif key == "plan" and value is not None:
            plan = value
            parts.append(
                "plan="
                + f"mode={getattr(plan, 'effective_mode', '?')}"
                + f" fast={getattr(plan, 'fast_path', '?')}"
                + f" skip_aug={getattr(plan, 'skip_augment', '?')}"
            )
        elif isinstance(value, (list, tuple)):
            parts.append(f"{key}={list(value)!r}")
        else:
            parts.append(f"{key}={value}")
    _PLAIN.info(" │ ".join(parts))


def chat_warn(event: str, *, task_id: str | None = None, **fields: Any) -> None:
    parts: list[str] = [f"[chat] {event}"]
    if task_id:
        parts.append(f"task={task_id}")
    for key, value in fields.items():
        if value is not None:
            parts.append(f"{key}={value}")
    _PLAIN.warning(" │ ".join(parts))


def chat_error(event: str, *, task_id: str | None = None, **fields: Any) -> None:
    parts: list[str] = [f"[chat] {event}"]
    if task_id:
        parts.append(f"task={task_id}")
    for key, value in fields.items():
        if value is not None:
            parts.append(f"{key}={value}")
    _PLAIN.error(" │ ".join(parts))
