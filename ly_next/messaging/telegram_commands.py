from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class TelegramCommandEvent:
    client: Any
    token: str
    chat_id: int
    user_id: int
    text: str
    update: dict[str, Any]


TelegramCommandHandler = Callable[[TelegramCommandEvent], Awaitable[bool]]

_handlers: list[tuple[int, TelegramCommandHandler]] = []


def register_telegram_command_handler(
    handler: TelegramCommandHandler,
    *,
    priority: int = 100,
) -> None:
    _handlers.append((priority, handler))
    _handlers.sort(key=lambda item: item[0])


async def dispatch_telegram_commands(event: TelegramCommandEvent) -> bool:
    for _, handler in _handlers:
        try:
            if await handler(event):
                return True
        except Exception:
            from ly_next.core.logger import get_logger

            get_logger(__name__).exception(
                "[telegram_commands] handler %s failed", getattr(handler, "__name__", handler)
            )
    return False
