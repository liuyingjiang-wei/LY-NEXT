"""Rough context usage vs configured window; prune old tool message bodies."""

from __future__ import annotations

import json
from typing import Any

from ly_next.core.config import config
from ly_next.core.logger import get_logger

logger = get_logger(__name__)

CHARS_PER_TOKEN_EST = 4


def _ctx_cfg() -> dict[str, Any]:
    raw = config.get("agent.context_window", {}) or {}
    return raw if isinstance(raw, dict) else {}


def _message_text_len(m: dict[str, Any]) -> int:
    c = m.get("content")
    if isinstance(c, str):
        return len(c)
    if c is None:
        return 0
    try:
        return len(json.dumps(c, ensure_ascii=False))
    except TypeError:
        return len(str(c))


def estimate_dialog_chars(messages: list[dict[str, Any]]) -> int:
    return sum(_message_text_len(m) for m in messages or [])


def estimate_dialog_tokens(messages: list[dict[str, Any]]) -> int:
    return max(1, estimate_dialog_chars(messages) // CHARS_PER_TOKEN_EST)


def effective_context_window_tokens(model: str | None) -> int:
    cfg = _ctx_cfg()
    default_tok = max(4096, int(cfg.get("default_tokens", 128000) or 128000))
    per = cfg.get("per_model")
    if isinstance(per, dict) and model:
        m = str(model).strip().lower()
        for key, val in per.items():
            if not isinstance(key, str) or not key.strip():
                continue
            if key.strip().lower() in m or m in key.strip().lower():
                try:
                    n = int(val)
                    if n > 0:
                        return min(max(n, 4096), 2_000_000)
                except (TypeError, ValueError):
                    continue
    return min(max(default_tok, 4096), 2_000_000)


def parse_completion_meta(
    resp: dict[str, Any],
) -> tuple[int | None, int | None, str | None]:
    """Best-effort OpenAI-style usage + finish_reason."""
    fr: str | None = None
    choices = resp.get("choices") if isinstance(resp, dict) else None
    if isinstance(choices, list) and choices:
        ch0 = choices[0]
        if isinstance(ch0, dict):
            r = ch0.get("finish_reason")
            fr = str(r).strip().lower() if r is not None else None

    usage = resp.get("usage") if isinstance(resp, dict) else None
    ct: int | None = None
    tt: int | None = None
    if isinstance(usage, dict):
        try:
            c = usage.get("completion_tokens")
            ct = int(c) if c is not None else None
        except (TypeError, ValueError):
            ct = None
        try:
            t = usage.get("total_tokens")
            tt = int(t) if t is not None else None
        except (TypeError, ValueError):
            tt = None
    return ct, tt, fr


def _output_budget_cfg() -> dict[str, Any]:
    raw = config.get("agent.output_token_budget", {}) or {}
    return raw if isinstance(raw, dict) else {}


def cumulative_budget_limit() -> int:
    c = _output_budget_cfg()
    if not bool(c.get("enabled", True)):
        return 0
    try:
        n = int(c.get("max_completion_tokens_per_run", 500000) or 0)
    except (TypeError, ValueError):
        return 0
    if n <= 0:
        return 0
    return n


def length_continuation_max() -> int:
    c = _output_budget_cfg()
    try:
        return max(0, min(int(c.get("length_continuation_max", 2) or 2), 8))
    except (TypeError, ValueError):
        return 2


def prune_old_tool_message_contents(
    messages: list[dict[str, Any]],
    *,
    model: str | None,
    max_output_tokens: int,
) -> list[dict[str, Any]]:
    cfg = _ctx_cfg()
    if not bool(cfg.get("prune_enabled", True)):
        return list(messages)

    window = effective_context_window_tokens(model)
    ratio = float(cfg.get("prune_dialog_fill_ratio", 0.82) or 0.82)
    ratio = max(0.5, min(ratio, 0.95))
    reserved = max(
        1024,
        int(max_output_tokens or 2048) + int(cfg.get("reserve_completion_tokens", 2048) or 2048),
    )
    token_budget = max(4096, int(window * ratio) - reserved)
    char_budget = max(8000, token_budget * CHARS_PER_TOKEN_EST)

    out = [dict(m) for m in (messages or [])]
    placeholder = (
        str(
            cfg.get("tool_placeholder", "[Earlier tool output removed to fit context window.]")
            or ""
        ).strip()
        or "[Earlier tool output removed to fit context window.]"
    )

    def over() -> bool:
        return estimate_dialog_chars(out) > char_budget

    if not over():
        return out

    for i, m in enumerate(out):
        if (m.get("role") or "").strip().lower() != "tool":
            continue
        if not over():
            break
        if _message_text_len(m) < int(cfg.get("prune_min_tool_chars", 400) or 400):
            continue
        out[i] = {**m, "content": placeholder}
        logger.info("[context] pruned tool message index=%s for context budget", i)

    if over():
        logger.warning(
            "[context] dialog still over budget after tool pruning (chars~%s, budget~%s)",
            estimate_dialog_chars(out),
            char_budget,
        )
    return out
