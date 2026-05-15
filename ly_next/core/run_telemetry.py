"""Per-request LLM/tool counters (contextvars)."""

from __future__ import annotations

from contextvars import ContextVar, Token
from dataclasses import dataclass, field
from typing import Any

from ly_next.core.config import config


def usage_counter_value(value: Any) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, int) and value >= 0:
        return value
    if isinstance(value, float) and value >= 0 and value.is_integer():
        return int(value)
    return 0


@dataclass
class RunTelemetry:
    task_id: str
    llm_calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    tools: list[dict[str, Any]] = field(default_factory=list)

    def record_chat_completion_usage(self, usage: dict[str, Any] | None) -> None:
        self.llm_calls += 1
        if not isinstance(usage, dict):
            return
        self.prompt_tokens += usage_counter_value(usage.get("prompt_tokens"))
        self.completion_tokens += usage_counter_value(usage.get("completion_tokens"))
        self.total_tokens += usage_counter_value(usage.get("total_tokens"))

    def record_tool(self, name: str, elapsed_ms: float, success: bool) -> None:
        self.tools.append(
            {
                "tool": name,
                "elapsed_ms": round(elapsed_ms, 2),
                "success": bool(success),
            }
        )

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "llm_calls": self.llm_calls,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "tools": list(self.tools),
        }


_current: ContextVar[RunTelemetry | None] = ContextVar("ly_next_run_telemetry", default=None)


def begin_run(task_id: str) -> Token:
    return _current.set(RunTelemetry(task_id=task_id))


def end_run(token: Token | None) -> None:
    if token is not None:
        _current.reset(token)


def get_public_snapshot() -> dict[str, Any] | None:
    run = _current.get()
    if run is None:
        return None
    return run.to_public_dict()


def record_llm_usage_from_chat_response(data: dict[str, Any]) -> None:
    run = _current.get()
    if run is None:
        return
    run.record_chat_completion_usage(data.get("usage"))


def record_tool_timing(name: str, elapsed_ms: float, success: bool) -> None:
    run = _current.get()
    if run is None:
        return
    run.record_tool(name, elapsed_ms, success)


def ws_run_summary_enabled() -> bool:
    raw = config.get("agent.observability", {}) or {}
    if not isinstance(raw, dict):
        return True
    return bool(raw.get("ws_run_summary", True))
