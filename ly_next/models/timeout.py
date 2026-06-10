from __future__ import annotations

from ly_next.core.config import config


def llm_timeout_seconds(*, agent: bool = False) -> int:
    if agent:
        raw = config.get("llm.agent_request_timeout")
        if raw is not None:
            return max(30, int(raw))
    raw = config.get("llm.request_timeout", 120)
    return max(30, int(raw or 120))
