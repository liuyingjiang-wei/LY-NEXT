from __future__ import annotations

import asyncio
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ly_next.core.config import config, get_data_root
from ly_next.core.logger import get_logger

logger = get_logger(__name__)

LEGACY_MARK_PREFIX = "LY_NEXT_STDIN "


def _journal_cfg() -> dict[str, Any]:
    raw = config.get("agent.stdin_journal", {}) or {}
    return raw if isinstance(raw, dict) else {}


def journal_path() -> Path:
    rel = str(
        _journal_cfg().get("relative_path", "logs/stdin_journal.jsonl")
        or "logs/stdin_journal.jsonl"
    )
    rel = rel.replace("\\", "/").lstrip("/")
    return get_data_root() / rel


def build_record(*, line: str, source: str, replay: bool = False) -> dict[str, Any]:
    return {
        "v": 1,
        "ts": datetime.now(timezone.utc).isoformat(),
        "line": line,
        "source": str(source or "unknown").strip() or "unknown",
        "replay": bool(replay),
    }


def parse_log_line(text: str) -> dict[str, Any] | None:
    if not text or not isinstance(text, str):
        return None
    plain = re.sub(r"\x1b\[[0-9;]*m", "", text)
    idx = plain.find(LEGACY_MARK_PREFIX)
    if idx < 0:
        return None
    tail = plain[idx + len(LEGACY_MARK_PREFIX) :].strip()
    try:
        obj = json.loads(tail)
    except json.JSONDecodeError:
        return None
    return obj if isinstance(obj, dict) else None


def _append_jsonl_sync(path: Path, rec: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(rec, ensure_ascii=False) + "\n"
    with path.open("a", encoding="utf-8") as f:
        f.write(line)


async def publish_stdin_line(line: str, source: str, *, replay: bool = False) -> int:
    from ly_next.api.bridge import emit_channel_event

    rec = build_record(line=line, source=source, replay=replay)
    if bool(_journal_cfg().get("enabled", True)):
        jp = journal_path()
        try:
            await asyncio.to_thread(_append_jsonl_sync, jp, rec)
        except OSError as e:
            logger.warning("[stdin_journal] append failed: %s", e)

    return await emit_channel_event(
        "stdin",
        "stdin_line",
        {"line": line, "source": rec["source"], "replay": replay},
    )


def extract_line_source(rec: dict[str, Any]) -> tuple[str, str] | None:
    line = rec.get("line")
    if not isinstance(line, str):
        return None
    src = rec.get("source")
    if not isinstance(src, str) or not src.strip():
        src = "replay"
    return line, src.strip()
