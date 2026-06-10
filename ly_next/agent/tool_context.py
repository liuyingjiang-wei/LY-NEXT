from __future__ import annotations

from contextvars import ContextVar
from typing import Any

_current_deps: ContextVar[Any | None] = ContextVar("ly_tool_run_deps", default=None)


def set_tool_run_deps(deps: Any | None) -> Any:
    return _current_deps.set(deps)


def reset_tool_run_deps(token: Any) -> None:
    _current_deps.reset(token)


def get_tool_run_deps() -> Any | None:
    return _current_deps.get()
