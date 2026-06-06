"""Per-request context for tools (thread / user quota keys)."""

from __future__ import annotations

from contextvars import ContextVar

current_thread_id: ContextVar[str | None] = ContextVar("ly_thread_id", default=None)


def set_current_thread_id(thread_id: str | None) -> None:
    current_thread_id.set(thread_id)


def get_current_thread_id() -> str | None:
    return current_thread_id.get()
