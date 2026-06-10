"""Eager tool dispatch during LLM streaming (Claude Code / Cursor pattern)."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any

from ly_next.agent.deps import AgentDeps
from ly_next.agent.react.tool_exec import execute_native_tool_call
from ly_next.models.stream_assemble import parse_sealed_tool_call


def _normalize_tool_call(tool_call: dict[str, Any]) -> dict[str, Any]:
    if isinstance(tool_call.get("function"), dict):
        return tool_call
    return {
        "id": tool_call.get("id"),
        "type": "function",
        "function": {
            "name": tool_call.get("name"),
            "arguments": tool_call.get("arguments") if tool_call.get("arguments") is not None else "{}",
        },
    }


class StreamingToolExecutor:
    """Start tool execution as soon as each tool_call block seals in the stream."""

    def __init__(
        self,
        deps: AgentDeps,
        *,
        allowed_set: set[str],
        run_tag: str,
        iteration: int,
        id_prefix: str,
    ) -> None:
        self.deps = deps
        self.allowed_set = allowed_set
        self.run_tag = run_tag
        self.iteration = iteration
        self.id_prefix = id_prefix
        self._sealed_indices: set[int] = set()
        self._tasks: dict[str, asyncio.Task[dict[str, Any]]] = {}
        self._order: list[str] = []

    @property
    def has_pending(self) -> bool:
        return bool(self._tasks)

    def note_sealed(self, index: int, tool_call: dict[str, Any]) -> dict[str, Any] | None:
        """Record a sealed tool block; returns tool_start event or None if duplicate."""
        if index in self._sealed_indices:
            return None
        normalized = _normalize_tool_call(tool_call)
        parsed = parse_sealed_tool_call(normalized)
        if parsed is None:
            return None
        self._sealed_indices.add(index)
        name, args, call_id = parsed
        if not str(normalized.get("id") or tool_call.get("id") or "").strip():
            call_id = f"{self.id_prefix}_{self.iteration}_{index}_{name}"
        self._order.append(call_id)
        self._tasks[call_id] = asyncio.create_task(
            execute_native_tool_call(
                self.deps,
                name=name,
                args=args,
                call_id=call_id,
                run_tag=self.run_tag,
                allowed_set=self.allowed_set,
            )
        )
        from ly_next.agent.react.helpers import preview_json

        return {
            "type": "tool_start",
            "tool": name,
            "call_id": call_id,
            "iteration": self.iteration,
            "args_preview": preview_json(args, limit=1200),
            "eager": True,
        }

    def dispatch_from_completion(self, tool_calls: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Dispatch any tool calls not yet started during streaming."""
        events: list[dict[str, Any]] = []
        for idx, tc in enumerate(tool_calls):
            ev = self.note_sealed(idx, tc)
            if ev is not None:
                events.append(ev)
        return events

    async def iter_results(self) -> AsyncIterator[dict[str, Any]]:
        """Yield tool_done events in dispatch order."""
        for call_id in self._order:
            task = self._tasks.get(call_id)
            if task is None:
                continue
            outcome = await task
            yield {
                "type": "tool_done",
                "tool": outcome["name"],
                "call_id": outcome["call_id"],
                "iteration": self.iteration,
                "success": outcome["ok"],
                "result_preview": outcome["preview"],
                "eager": True,
            }
            yield {"type": "_tool_outcome", "outcome": outcome}
