"""Compress long agent scratchpads to bound context growth."""

from __future__ import annotations

from ly_next.agent.deps import AgentDeps
from ly_next.core.logger import get_logger

logger = get_logger(__name__)


async def compress_scratchpad(
    deps: AgentDeps,
    *,
    scratchpad: str,
    task_hint: str,
    target_chars: int,
    prompt_budget_chars: int = 50000,
) -> str:
    raw = (scratchpad or "").strip()
    if not raw:
        return raw

    snippet = raw[-prompt_budget_chars:]
    hint = (task_hint or "")[:4000]
    prompt = f"""Summarize these agent execution notes for continuing reasoning.
Keep: verified facts, errors, and short key tool outcomes.
Remove: duplication and noise.
Use bullet lines. Stay under ~{max(20, target_chars // 3)} words.

Task (context): {hint}

Notes:
{snippet}
"""
    try:
        text = (
            await deps.call_llm_limited(prompt, max_tokens=deps.scratchpad_compress_max_tokens)
        ).strip()
        if len(text) < 40:
            raise ValueError("compressed text too short")
        out = "[scratchpad compressed]\n" + text
        if len(out) > target_chars * 2:
            out = out[: target_chars * 2]
        return out
    except Exception as e:
        logger.warning("[agent] scratchpad LLM compress failed: %s", e)
        tail = raw[-target_chars:] if len(raw) > target_chars else raw
        return "[scratchpad truncated]\n" + tail
