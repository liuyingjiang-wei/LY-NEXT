from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class MessagePart:
    type: str  # "text" | "image"
    content: str


@dataclass
class MixedMessage:
    parts: list[MessagePart] = field(default_factory=list)

    @property
    def has_images(self) -> bool:
        return any(p.type == "image" for p in self.parts)

    @property
    def plain_text(self) -> str:
        return "".join(p.content for p in self.parts if p.type == "text").strip()

    def image_urls(self) -> list[str]:
        return [p.content for p in self.parts if p.type == "image" and p.content.strip()]


def mixed_message_to_dict(msg: MixedMessage) -> dict[str, Any]:
    return {
        "parts": [{"type": p.type, "content": p.content} for p in msg.parts],
        "text": msg.plain_text,
        "image_urls": msg.image_urls(),
        "has_images": msg.has_images,
    }
