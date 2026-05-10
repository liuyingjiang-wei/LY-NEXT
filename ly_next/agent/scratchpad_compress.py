from __future__ import annotations

from ly_next.agent.deps import AgentDeps
from ly_next.core.config import config
from ly_next.core.logger import get_logger

logger = get_logger(__name__)


def _dedupe_line_runs(text: str) -> str:
    lines = text.split("\n")
    out: list[str] = []
    prev: str | None = None
    run = 0
    for ln in lines:
        if ln == prev:
            run += 1
            if run <= 2:
                out.append(ln)
            elif run == 3:
                out.append("…")
            continue
        prev = ln
        run = 1
        out.append(ln)
    return "\n".join(out)


def _tail_fit(text: str, target: int) -> str:
    if len(text) <= target:
        return text
    chunk = text[-target:]
    nl = chunk.find("\n")
    if 0 < nl < min(200, len(chunk) // 5):
        chunk = chunk[nl + 1 :]
    return chunk


def _extractive_shrink(raw: str, target_chars: int) -> str:
    d = _dedupe_line_runs(raw)
    if len(d) <= int(target_chars * 1.25):
        return d
    return _tail_fit(d, min(len(d), max(target_chars, int(target_chars * 1.8))))


async def compress_scratchpad(
    deps: AgentDeps,
    *,
    scratchpad: str,
    task_hint: str,
    target_chars: int,
    prompt_budget_chars: int | None = None,
) -> str:
    raw = (scratchpad or "").strip()
    if not raw:
        return raw

    sp = config.get("agent.scratchpad", {}) or {}
    if not isinstance(sp, dict):
        sp = {}
    budget_default = int(sp.get("compress_prompt_chars", 14000) or 14000)
    pb = prompt_budget_chars if prompt_budget_chars is not None else budget_default
    pb = max(4000, min(pb, 100_000))
    use_llm = bool(sp.get("compress_use_llm", True))

    ext = _extractive_shrink(raw, target_chars)
    if len(ext) <= int(target_chars * 1.25):
        return "[scratchpad compressed]\n" + ext

    if not use_llm:
        tail = raw[-target_chars:] if len(raw) > target_chars else raw
        return "[scratchpad truncated]\n" + tail

    snippet = ext[-pb:]
    hint = (task_hint or "")[:1200]
    prompt = (
        f"Summarize notes for continued reasoning. Bullet lines only; "
        f"keep facts/errors/tool outcomes; drop noise. Under ~{max(12, target_chars // 4)} words.\n"
        f"Task: {hint}\n---\n{snippet}"
    )
    try:
        mt = max(96, min(int(deps.scratchpad_compress_max_tokens), 768))
        text = (await deps.call_llm_limited(prompt, max_tokens=mt)).strip()
        if len(text) < 32:
            raise ValueError("compressed text too short")
        out = "[scratchpad compressed]\n" + text
        if len(out) > target_chars * 2:
            out = out[: target_chars * 2]
        return out
    except Exception as e:
        logger.warning("[agent] scratchpad LLM compress failed: %s", e)
        tail = raw[-target_chars:] if len(raw) > target_chars else raw
        return "[scratchpad truncated]\n" + tail
