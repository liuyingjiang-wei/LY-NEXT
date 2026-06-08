from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Awaitable, Callable


@dataclass(frozen=True)
class OneBotCommandEvent:
    session: Any
    message_type: str
    user_id: int
    group_id: int | None
    text: str
    raw_message: Any


OneBotCommandHandler = Callable[[OneBotCommandEvent], Awaitable[bool]]

_handlers: list[tuple[int, OneBotCommandHandler]] = []


def register_onebot_command_handler(
    handler: OneBotCommandHandler,
    *,
    priority: int = 100,
) -> None:
    _handlers.append((priority, handler))
    _handlers.sort(key=lambda item: item[0])


async def dispatch_onebot_commands(event: OneBotCommandEvent) -> bool:
    for _, handler in _handlers:
        try:
            if await handler(event):
                return True
        except Exception:
            from ly_next.core.logger import get_logger

            get_logger(__name__).exception(
                "[onebot_commands] handler %s failed", getattr(handler, "__name__", handler)
            )
    return False
