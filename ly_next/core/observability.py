from __future__ import annotations

from typing import Any

from ly_next.core.config import config

_REDACT_TEXT_KEYS = frozenset({"prompt", "content", "messages", "text", "response"})


def _obs_cfg() -> dict[str, Any]:
    raw = config.get("agent.observability", {}) or {}
    return raw if isinstance(raw, dict) else {}


def observability_enabled() -> bool:
    return bool(_obs_cfg().get("enabled", True))


def observability_persist() -> bool:
    if not observability_enabled():
        return False
    return bool(_obs_cfg().get("persist", True))


def max_events_per_run() -> int:
    return max(50, min(int(_obs_cfg().get("max_events_per_run", 500) or 500), 5000))


def clamp_runs_query_limit(limit: int) -> int:
    return max(1, min(int(limit), 200))


def store_prompts() -> bool:
    return bool(_obs_cfg().get("store_prompts", False))


def ws_run_summary_enabled() -> bool:
    return bool(_obs_cfg().get("ws_run_summary", True))


def attach_run_fields(payload: dict[str, Any], snap: dict[str, Any] | None) -> dict[str, Any]:
    if not snap:
        return payload
    out = {**payload}
    if ws_run_summary_enabled():
        out["run_summary"] = snap
    lk = snap.get("loop_kind")
    if lk:
        out["loop_kind"] = lk
    return out


def redact_event_payload(payload: dict[str, Any]) -> dict[str, Any]:
    if store_prompts():
        return dict(payload)
    out: dict[str, Any] = {}
    for key, value in payload.items():
        if key in _REDACT_TEXT_KEYS:
            if isinstance(value, str):
                out[f"{key}_chars"] = len(value)
            elif isinstance(value, list):
                out[f"{key}_count"] = len(value)
            continue
        out[key] = value
    return out
