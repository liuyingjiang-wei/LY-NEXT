"""Agent interface contract for factory registration and typing."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any, Protocol, runtime_checkable

from ly_next.agent.deps import AgentDeps


@runtime_checkable
class BaseAgent(Protocol):
    deps: AgentDeps

    async def run(self, messages: list[dict[str, Any]]) -> str: ...

    async def run_stream(self, messages: list[dict[str, Any]]) -> AsyncIterator[dict[str, Any]]: ...


def validate_agent_class(agent_class: type) -> None:
    required = ("run", "run_stream")
    missing = [name for name in required if not callable(getattr(agent_class, name, None))]
    if missing:
        raise TypeError(
            f"Agent class {agent_class.__name__} missing required methods: {', '.join(missing)}"
        )
