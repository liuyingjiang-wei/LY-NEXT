from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path

from ly_next.agent.memory_write_policy import evaluate_memory_append, record_append_event
from ly_next.agent.startup_memory import invalidate_startup_memory_cache
from ly_next.core.config import config, get_project_root
from ly_next.core.logger import get_logger
from ly_next.tools.base import ToolResult, tool

logger = get_logger(__name__)

_memory_lock = asyncio.Lock()


def _memory_file_path() -> Path:
    raw = str(config.get("agent.memory.path", "MEMORY.md") or "MEMORY.md").strip()
    p = Path(raw)
    if not p.is_absolute():
        p = get_project_root() / p
    return p.resolve()


def _memory_path_allowed(target: Path) -> bool:
    if not bool(config.get("agent.memory.enabled", True)):
        return False
    root = get_project_root().resolve()
    try:
        target.relative_to(root)
    except ValueError:
        return False
    return True


def _append_note_sync(path: Path, note: str) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    mw = config.get("agent.memory.write", {}) or {}
    mx = 2000
    if isinstance(mw, dict):
        mx = max(32, int(mw.get("max_note_chars", 2000) or 2000))
    snippet = note.strip().replace("\r\n", "\n").replace("\r", "\n")
    if len(snippet) > mx:
        snippet = snippet[:mx] + "…"
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%MZ")
    line = f"- {ts} — {snippet}\n"
    if not path.is_file():
        path.write_text(
            "# 长期记忆\n\n（本文件可由助手通过 `remember_fact` 追加条目；也可手动编辑。）\n\n",
            encoding="utf-8",
        )
    with path.open("a", encoding="utf-8") as f:
        f.write(line)
    return line.strip()


@tool(
    name="remember_fact",
    description=(
        "Append one short bullet to the project's long-term memory file (agent.memory.path, "
        "usually MEMORY.md). Use for stable user preferences or facts they asked to remember. "
        "Do not store secrets, API keys, or one-time codes."
    ),
    category="safe",
    parameters={
        "type": "object",
        "properties": {
            "note": {
                "type": "string",
                "description": "One concise fact to remember (plain text).",
            }
        },
        "required": ["note"],
    },
)
async def remember_fact(note: str) -> ToolResult:
    if not note or not str(note).strip():
        return ToolResult(success=False, error="note is empty")
    target = _memory_file_path()
    if not _memory_path_allowed(target):
        return ToolResult(
            success=False,
            error="memory file path is disabled or outside project root; fix agent.memory.path",
        )
    async with _memory_lock:
        ok, reason = evaluate_memory_append(str(note), target)
        if not ok:
            return ToolResult(success=False, error=reason)
        try:
            written = await asyncio.to_thread(_append_note_sync, target, str(note))
        except OSError as e:
            logger.warning("[remember_fact] write failed: %s", e)
            return ToolResult(success=False, error=str(e))
        record_append_event()
        invalidate_startup_memory_cache()
        return ToolResult(
            success=True,
            result={"path": str(target), "appended": written},
        )
