from __future__ import annotations

import json
import re
from typing import Any

from ly_next.core.config import config, get_data_root, get_project_root
from ly_next.core.logger import get_logger

logger = get_logger(__name__)


def _tool_spill_cfg() -> dict[str, Any]:
    raw = config.get("agent.tool_spill", {}) or {}
    return raw if isinstance(raw, dict) else {}


def coerce_tool_payload_text(result: Any) -> str:
    if isinstance(result, str):
        return result
    if isinstance(result, dict):
        inner = result.get("result")
        if isinstance(inner, dict):
            text = inner.get("text")
            if isinstance(text, str) and text.strip():
                return text
        if isinstance(inner, str) and inner.strip():
            return inner
    try:
        return json.dumps(result, ensure_ascii=False)
    except TypeError:
        return str(result)


def _is_effectively_empty_text(text: str) -> bool:
    if not text or not str(text).strip():
        return True
    t = str(text).strip()
    return t in ("{}", "[]", "null", '""', "''")


def _sanitize_id_fragment(s: str) -> str:
    out = re.sub(r"[^\w\-.]+", "_", (s or "").strip())[:96]
    return out or "tool"


def _preview_parts(text: str, head: int, tail: int) -> str:
    if len(text) <= head + tail + 80:
        return text
    mid = "\n\n… [middle omitted] …\n\n"
    return text[:head] + mid + text[-tail:]


def format_tool_result_for_llm(
    tool_name: str,
    tool_call_id: str,
    result: Any,
    *,
    run_tag: str,
) -> str:
    cfg = _tool_spill_cfg()
    if not bool(cfg.get("enabled", True)):
        return coerce_tool_payload_text(result)

    raw = coerce_tool_payload_text(result)
    if _is_effectively_empty_text(raw):
        return f"({tool_name} completed with no output)"

    max_inline = max(2000, min(int(cfg.get("max_inline_chars", 32000) or 32000), 500_000))
    head = max(400, min(int(cfg.get("preview_head_chars", 2000) or 2000), 50_000))
    tail = max(0, min(int(cfg.get("preview_tail_chars", 500) or 500), 20_000))

    if len(raw) <= max_inline:
        return raw

    rel = str(cfg.get("relative_dir", "tool_results") or "tool_results").strip().strip("/\\")
    base = get_data_root() / rel / _sanitize_id_fragment(run_tag)
    try:
        base.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        logger.warning("[tool_spill] mkdir failed %s: %s", base, e)
        return raw[: max_inline - 80] + "\n\n[truncated: spill write failed]"

    fn = f"{_sanitize_id_fragment(tool_call_id)}.txt"
    path = base / fn
    try:
        path.write_text(raw, encoding="utf-8")
    except OSError as e:
        logger.warning("[tool_spill] write failed %s: %s", path, e)
        return raw[: max_inline - 80] + "\n\n[truncated: spill write failed]"

    try:
        rel_msg = path.relative_to(get_project_root())
    except ValueError:
        rel_msg = path

    preview = _preview_parts(raw, head, tail)
    return (
        f"Tool output exceeded inline limit ({len(raw)} chars); full text on disk.\n\n"
        f"path: {rel_msg}\n\n"
        f"Preview:\n{preview}"
    )
