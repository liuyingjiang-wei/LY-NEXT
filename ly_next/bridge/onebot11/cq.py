from __future__ import annotations

import re
from typing import Any

_CQ_AT = re.compile(r"\[CQ:at,qq=(\d+|all)\]", re.IGNORECASE)
_CQ_TEXT = re.compile(r"\[CQ:text,([^\]]+)\]", re.IGNORECASE)
_CQ_PLAIN = re.compile(r"\[CQ:[^\]]+\]", re.IGNORECASE)


def message_to_text(message: Any) -> str:
    if message is None:
        return ""
    if isinstance(message, str):
        return _cq_string_to_text(message)
    if isinstance(message, list):
        parts: list[str] = []
        for seg in message:
            if not isinstance(seg, dict):
                continue
            seg_type = str(seg.get("type") or "")
            data = seg.get("data") or {}
            if not isinstance(data, dict):
                data = {}
            if seg_type == "text":
                parts.append(str(data.get("text") or ""))
            elif seg_type == "at":
                name = data.get("name")
                if name:
                    parts.append(f"@{name}")
        return "".join(parts).strip()
    return str(message).strip()


def _cq_string_to_text(raw: str) -> str:
    text = raw
    for m in _CQ_TEXT.finditer(raw):
        text = text.replace(m.group(0), m.group(1))
    text = _CQ_PLAIN.sub("", text)
    return text.strip()


def is_at_self(message: Any, self_id: int | str) -> bool:
    sid = str(self_id)
    if isinstance(message, str):
        for m in _CQ_AT.finditer(message):
            qq = m.group(1)
            if qq == "all" or qq == sid:
                return True
        return False
    if isinstance(message, list):
        for seg in message:
            if not isinstance(seg, dict) or seg.get("type") != "at":
                continue
            data = seg.get("data") or {}
            qq = str((data or {}).get("qq", ""))
            if qq in ("all", sid):
                return True
    return False


def normalize_user_message_text(message: Any, self_id: int | str) -> str:
    text = message_to_text(message)
    if not text:
        return ""
    sid = str(self_id)
    if isinstance(message, str):
        text = _CQ_AT.sub(
            lambda m: "" if m.group(1) in (sid, "all") else m.group(0),
            text,
        )
    elif isinstance(message, list):
        parts: list[str] = []
        for seg in message:
            if not isinstance(seg, dict):
                continue
            if seg.get("type") == "at":
                data = seg.get("data") or {}
                qq = str((data or {}).get("qq", ""))
                if qq in (sid, "all"):
                    continue
            parts.append(message_to_text([seg]))
        text = "".join(parts)
    return _CQ_PLAIN.sub("", text).strip()


def apply_prefix_trigger(text: str, prefixes: tuple[str, ...]) -> str | None:
    if not prefixes:
        return text.strip() if text.strip() else None
    stripped = text.strip()
    if not stripped:
        return None
    for prefix in prefixes:
        if stripped.startswith(prefix):
            rest = stripped[len(prefix) :].strip()
            return rest if rest else None
    return None
