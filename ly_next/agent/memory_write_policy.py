from __future__ import annotations

import re
import time
from collections import deque
from pathlib import Path
from threading import Lock

from ly_next.core.config import config

_APPEND_TIMES: deque[float] = deque()
_APPEND_LOCK = Lock()


def _normalize(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip().lower())


def _tail_note_norms(path: Path, max_bytes: int = 12000) -> set[str]:
    if not path.is_file():
        return set()
    try:
        tail = path.read_bytes()[-max_bytes:].decode("utf-8", errors="replace")
    except OSError:
        return set()
    out: set[str] = set()
    for line in tail.splitlines():
        t = line.strip()
        if not t.startswith("- "):
            continue
        if "—" in t:
            body = t.split("—", 1)[-1].strip()
        elif " - " in t[2:]:
            body = t[2:].split(" - ", 1)[-1].strip()
        else:
            body = t[2:].strip()
        if body:
            out.add(_normalize(body))
    return out


def evaluate_memory_append(note: str, memory_path: Path) -> tuple[bool, str]:
    mw = config.get("agent.memory.write", {}) or {}
    if not isinstance(mw, dict):
        mw = {}
    if not bool(mw.get("enabled", True)):
        return (False, "agent.memory.write.enabled is false")

    n = (note or "").strip()
    mn = max(1, int(mw.get("min_note_chars", 2) or 2))
    mx = max(mn, int(mw.get("max_note_chars", 2000) or 2000))
    if len(n) < mn:
        return (False, f"note shorter than min_note_chars ({mn})")
    if len(n) > mx:
        return (False, f"note longer than max_note_chars ({mx})")

    rpm = max(0, int(mw.get("max_appends_per_minute", 24) or 0))
    if rpm > 0:
        now = time.monotonic()
        with _APPEND_LOCK:
            while _APPEND_TIMES and now - _APPEND_TIMES[0] > 60.0:
                _APPEND_TIMES.popleft()
            if len(_APPEND_TIMES) >= rpm:
                return (False, "max_appends_per_minute exceeded (sliding window)")

    if bool(mw.get("dedupe", True)):
        key = _normalize(n)
        if key in _tail_note_norms(memory_path):
            return (False, "duplicate of a recent memory line (dedupe)")

    return (True, "")


def record_append_event() -> None:
    mw = config.get("agent.memory.write", {}) or {}
    if not isinstance(mw, dict):
        mw = {}
    rpm = max(0, int(mw.get("max_appends_per_minute", 24) or 0))
    if rpm <= 0:
        return
    with _APPEND_LOCK:
        _APPEND_TIMES.append(time.monotonic())
