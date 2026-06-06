from __future__ import annotations

import json
import re
from typing import Any

from ly_next.messaging.models import MessagePart, MixedMessage

_IMAGE_TAG_RE = re.compile(
    r"\[image:((?:https?://|data:image/|base64://)[^\]\s]+)\]",
    re.IGNORECASE,
)
_IMAGE_TOOLS = frozenset({"generate_image", "search_images"})


def _urls_from_tool_payload(payload: Any) -> list[str]:
    if payload is None:
        return []
    data = payload
    if isinstance(payload, str):
        try:
            data = json.loads(payload)
        except json.JSONDecodeError:
            return []
    if not isinstance(data, dict):
        return []

    if data.get("success") is False:
        return []

    inner: Any = data.get("result")
    if inner is None and "status" in data or inner is None:
        inner = data
    if isinstance(inner, str):
        try:
            inner = json.loads(inner)
        except json.JSONDecodeError:
            return []
    if not isinstance(inner, dict):
        return []

    status = str(inner.get("status") or "").lower()
    if status and status not in ("ok", "success"):
        return []

    urls: list[str] = []
    one = inner.get("image_url")
    if isinstance(one, str) and one.strip():
        urls.append(one.strip())
    many = inner.get("image_urls")
    if isinstance(many, list):
        for u in many:
            if isinstance(u, str) and u.strip():
                urls.append(u.strip())
    return urls


def extract_image_urls_from_tool_results(
    tool_results: list[dict[str, Any]] | None,
) -> list[str]:
    urls: list[str] = []
    seen: set[str] = set()
    for row in tool_results or []:
        name = str(row.get("tool") or "")
        if name and name not in _IMAGE_TOOLS:
            continue
        for u in _urls_from_tool_payload(row.get("result")):
            if u not in seen:
                seen.add(u)
                urls.append(u)
    return urls


def parse_image_tags(text: str) -> tuple[list[MessagePart], list[str]]:
    """Split text by [image:URL] markers into ordered parts."""
    if not text:
        return [], []

    parts: list[MessagePart] = []
    urls: list[str] = []
    last = 0
    for m in _IMAGE_TAG_RE.finditer(text):
        before = text[last : m.start()]
        if before:
            parts.append(MessagePart(type="text", content=before))
        url = m.group(1).strip()
        parts.append(MessagePart(type="image", content=url))
        urls.append(url)
        last = m.end()
    tail = text[last:]
    if tail:
        parts.append(MessagePart(type="text", content=tail))
    return parts, urls


def build_mixed_message(
    text: str,
    tool_results: list[dict[str, Any]] | None = None,
) -> MixedMessage:
    """Merge [image:URL] tags in text with URLs from recent image tool results."""
    tagged_parts, tagged_urls = parse_image_tags(text or "")
    tool_urls = extract_image_urls_from_tool_results(tool_results)

    if tagged_parts:
        seen = set(tagged_urls)
        parts = list(tagged_parts)
        for u in tool_urls:
            if u in seen:
                continue
            seen.add(u)
            parts.append(MessagePart(type="image", content=u))
        return MixedMessage(parts=_collapse_adjacent_text(parts))

    if tool_urls:
        parts: list[MessagePart] = []
        body = (text or "").strip()
        if body:
            parts.append(MessagePart(type="text", content=body))
        for u in tool_urls:
            parts.append(MessagePart(type="image", content=u))
        return MixedMessage(parts=parts)

    body = text or ""
    if body.strip():
        return MixedMessage(parts=[MessagePart(type="text", content=body)])
    return MixedMessage(parts=[])


def parse_mixed_message(
    text: str, tool_results: list[dict[str, Any]] | None = None
) -> MixedMessage:
    return build_mixed_message(text, tool_results)


def _collapse_adjacent_text(parts: list[MessagePart]) -> list[MessagePart]:
    if not parts:
        return parts
    out: list[MessagePart] = []
    for p in parts:
        if p.type == "text" and out and out[-1].type == "text":
            out[-1] = MessagePart(type="text", content=out[-1].content + p.content)
        else:
            out.append(p)
    return out
