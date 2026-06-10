"""Structured security audit log (tool calls, auth events)."""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ly_next.core.auth_context import get_principal
from ly_next.core.config import config, get_data_root
from ly_next.core.logger import get_logger

logger = get_logger(__name__)
_lock = threading.Lock()


def _audit_cfg() -> dict[str, Any]:
    sec = config.get("security") or {}
    block = sec.get("audit") if isinstance(sec, dict) else {}
    return block if isinstance(block, dict) else {}


def audit_enabled() -> bool:
    return bool(_audit_cfg().get("enabled", True))


def _audit_path() -> Path:
    rel = str(_audit_cfg().get("file") or "logs/security_audit.log").strip()
    path = Path(rel)
    if path.is_absolute():
        return path
    return get_data_root() / rel


def _summarize_args(arguments: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in (arguments or {}).items():
        ks = str(key)
        lower = ks.lower()
        if any(s in lower for s in ("password", "secret", "token", "api_key", "apikey")):
            out[ks] = "[redacted]"
            continue
        text = str(value)
        if len(text) > 240:
            out[ks] = text[:240] + "…"
        else:
            out[ks] = value
    return out


def write_audit_event(event: str, **fields: Any) -> None:
    if not audit_enabled():
        return
    principal = get_principal()
    payload: dict[str, Any] = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "event": event,
    }
    if principal:
        payload["subject"] = principal.subject
        payload["role"] = principal.role
        payload["auth_method"] = principal.auth_method
    payload.update(fields)
    line = json.dumps(payload, ensure_ascii=False, default=str)
    path = _audit_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with _lock, path.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except Exception as e:
        logger.warning("audit log write failed: %s", e)


def audit_tool_call(name: str, arguments: dict[str, Any], result: dict[str, Any]) -> None:
    if not _audit_cfg().get("log_tool_calls", True):
        return
    deps = None
    channel = None
    thread_id = None
    try:
        from ly_next.agent.tool_context import get_tool_run_deps

        deps = get_tool_run_deps()
        if deps is not None:
            channel = getattr(deps, "channel", None)
            thread_id = getattr(deps, "thread_id", None)
    except Exception:
        pass
    extra: dict[str, Any] = {}
    if result.get("policy_blocked"):
        extra["policy_blocked"] = True
        try:
            from ly_next.agent.content_trust import untrusted_reasons

            reasons = untrusted_reasons()
            if reasons:
                extra["untrusted_reasons"] = list(reasons)
        except Exception:
            pass
    write_audit_event(
        "tool_call",
        tool=name,
        args=_summarize_args(arguments),
        success=bool(result.get("success")),
        error=(str(result.get("error"))[:500] if result.get("error") else None),
        channel=channel,
        thread_id=thread_id,
        **extra,
    )


def audit_auth_event(event: str, **fields: Any) -> None:
    if not _audit_cfg().get("log_auth_events", True):
        return
    write_audit_event(event, **fields)
