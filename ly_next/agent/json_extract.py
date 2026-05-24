from __future__ import annotations

import json
import re
from typing import Any

_PREVIEW_LEN = 320


def _preview(text: str, limit: int = _PREVIEW_LEN) -> str:
    s = (text or "").replace("\r\n", "\n").strip()
    if len(s) <= limit:
        return s
    return s[: limit - 1] + "…"


def _extract_json_body(text: str) -> str:
    body = text.strip()
    fenced = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", body, flags=re.IGNORECASE)
    if fenced:
        body = fenced.group(1).strip()
    if not body.startswith("{"):
        brace = re.search(r"(\{[\s\S]*\})", body)
        if brace:
            body = brace.group(1)
    return body


def _escape_control_chars_in_json_strings(raw: str) -> str:
    out: list[str] = []
    in_string = False
    escape = False
    for ch in raw:
        if escape:
            out.append(ch)
            escape = False
            continue
        if ch == "\\" and in_string:
            escape = True
            out.append(ch)
            continue
        if ch == '"':
            in_string = not in_string
            out.append(ch)
            continue
        if in_string:
            if ch == "\n":
                out.append("\\n")
                continue
            if ch == "\r":
                out.append("\\r")
                continue
            if ch == "\t":
                out.append("\\t")
                continue
            if ord(ch) < 32:
                out.append(f"\\u{ord(ch):04x}")
                continue
        out.append(ch)
    return "".join(out)


def _loads_object(body: str) -> dict[str, Any]:
    parsed = json.loads(body)
    if not isinstance(parsed, dict):
        raise ValueError("expected JSON object")
    return parsed


def parse_json_object(text: str) -> dict[str, Any]:
    if not (text or "").strip():
        raise ValueError("empty model output")
    body = _extract_json_body(text)
    if not body:
        raise ValueError("empty model output")
    try:
        return _loads_object(body)
    except json.JSONDecodeError as first:
        fixed = _escape_control_chars_in_json_strings(body)
        if fixed != body:
            try:
                return _loads_object(fixed)
            except json.JSONDecodeError:
                pass
        raise ValueError(
            f"invalid JSON ({first.msg}) at position {first.pos}; snippet: {_preview(body)!r}"
        ) from first
