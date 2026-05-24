from __future__ import annotations

from contextvars import ContextVar, Token
from dataclasses import dataclass, field
from typing import Any

from ly_next.core import run_memory
from ly_next.core.observability import max_events_per_run, redact_event_payload

_STREAM_KIND = {
    "status": "status",
    "tool_start": "tool_start",
    "tool_done": "tool_end",
    "final": "final",
    "node": "node",
    "error": "error",
}

LLM_ERROR_MAX_LEN = 500


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
    mode: str = "react"
    loop_kind: str | None = None
    router: dict[str, Any] = field(default_factory=dict)
    llm_calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    tools: list[dict[str, Any]] = field(default_factory=list)
    events: list[dict[str, Any]] = field(default_factory=list)
    _event_seq: int = 0

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
        out: dict[str, Any] = {
            "task_id": self.task_id,
            "run_id": self.task_id,
            "llm_calls": self.llm_calls,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "tools": list(self.tools),
        }
        if self.loop_kind:
            out["loop_kind"] = self.loop_kind
        if self.mode:
            out["mode"] = self.mode
        return out


_current: ContextVar[RunTelemetry | None] = ContextVar("ly_next_run_telemetry", default=None)


def _active_run() -> RunTelemetry | None:
    return _current.get()


def snapshot_usage_for_api(snap: dict[str, Any] | None) -> dict[str, Any]:
    s = snap or {}
    return {
        "prompt_tokens": usage_counter_value(s.get("prompt_tokens")),
        "completion_tokens": usage_counter_value(s.get("completion_tokens")),
        "total_tokens": usage_counter_value(s.get("total_tokens")),
        "llm_calls": usage_counter_value(s.get("llm_calls")),
    }


def persisted_usage_from_snapshot(snap: dict[str, Any] | None) -> dict[str, Any]:
    tools = (snap or {}).get("tools")
    return {
        **snapshot_usage_for_api(snap),
        "tools": list(tools) if isinstance(tools, list) else [],
    }


def begin_run(
    task_id: str,
    *,
    mode: str = "react",
    router: dict[str, Any] | None = None,
) -> Token:
    return _current.set(RunTelemetry(task_id=task_id, mode=mode, router=dict(router or {})))


def end_run(token: Token | None) -> None:
    if token is not None:
        _current.reset(token)


def set_run_loop_kind(loop_kind: str) -> None:
    run = _active_run()
    if run is None:
        return
    lk = run_memory.normalize_field(loop_kind)
    if lk is None:
        return
    run.loop_kind = lk
    run_memory.patch_loop_kind(run.task_id, lk)


def emit_run_event(kind: str, payload: dict[str, Any] | None = None) -> None:
    run = _active_run()
    if run is None or len(run.events) >= max_events_per_run():
        return
    run._event_seq += 1
    event = {
        "seq": run._event_seq,
        "kind": kind[:64],
        "payload": redact_event_payload(payload or {}),
    }
    run.events.append(event)
    if run.task_id in run_memory.runs:
        mem_list = run_memory.events.setdefault(run.task_id, [])
        if len(mem_list) < max_events_per_run():
            mem_list.append(dict(event))


def record_stream_event(ev: dict[str, Any]) -> None:
    if not isinstance(ev, dict):
        return
    etype = str(ev.get("type") or "event")
    if etype == "chunk":
        return
    emit_run_event(
        _STREAM_KIND.get(etype, etype),
        {k: v for k, v in ev.items() if k != "type"},
    )


def get_run_events() -> list[dict[str, Any]]:
    run = _active_run()
    return list(run.events) if run else []


def get_public_snapshot() -> dict[str, Any] | None:
    run = _active_run()
    return run.to_public_dict() if run else None


def get_run_loop_kind() -> str | None:
    run = _active_run()
    return run.loop_kind if run else None


def _emit_llm_end(
    *,
    model: str | None,
    success: bool,
    usage: dict[str, Any] | None = None,
    error: str | None = None,
) -> None:
    payload: dict[str, Any] = {"model": model, "success": success}
    if usage is not None:
        payload["usage"] = usage
    if error:
        payload["error"] = error[:LLM_ERROR_MAX_LEN]
    emit_run_event("llm_end", payload)


def record_llm_call_start(
    *,
    model: str | None = None,
    messages_count: int | None = None,
    provider: str | None = None,
) -> None:
    payload: dict[str, Any] = {}
    if model:
        payload["model"] = model
    if provider:
        payload["provider"] = provider
    if messages_count is not None:
        payload["messages_count"] = messages_count
    emit_run_event("llm_start", payload)


def record_llm_call_failed(*, model: str | None = None, error: str) -> None:
    run = _active_run()
    if run is None:
        return
    run.llm_calls += 1
    _emit_llm_end(model=model, success=False, error=error or "")


def record_llm_usage_from_chat_response(data: dict[str, Any]) -> None:
    run = _active_run()
    if run is None:
        return
    usage = data.get("usage") if isinstance(data, dict) else None
    usage_dict = usage if isinstance(usage, dict) else {}
    run.record_chat_completion_usage(usage_dict or None)
    _emit_llm_end(
        model=data.get("model") if isinstance(data, dict) else None,
        success=True,
        usage=usage_dict,
    )


def record_tool_timing(name: str, elapsed_ms: float, success: bool) -> None:
    run = _active_run()
    if run is None:
        return
    run.record_tool(name, elapsed_ms, success)
