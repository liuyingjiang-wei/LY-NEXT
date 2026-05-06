from __future__ import annotations

from pathlib import Path

from ly_next.core.config import config, get_project_root
from ly_next.core.logger import get_logger

logger = get_logger(__name__)

_CACHE = {"path": "", "mtime": 0.0, "text": ""}


def _memory_path() -> Path:
    raw = str(config.get("agent.memory.path", "MEMORY.md") or "MEMORY.md").strip()
    p = Path(raw)
    if not p.is_absolute():
        p = get_project_root() / p
    return p


def get_startup_memory_block() -> str:
    if not bool(config.get("agent.memory.enabled", True)):
        return ""
    p = _memory_path()
    if not p.is_file():
        return ""
    try:
        st = p.stat()
    except Exception:
        return ""
    key = str(p.resolve())
    if _CACHE["path"] == key and float(_CACHE["mtime"]) == float(st.st_mtime):
        return str(_CACHE["text"])
    try:
        text = p.read_text(encoding="utf-8", errors="replace").strip()
    except Exception as e:
        logger.warning("[agent.memory] failed to read %s: %s", p, e)
        return ""
    if not text:
        return ""
    block = (
        "【启动记忆（长期规则）】\n"
        "以下内容来自系统启动时加载的长期记忆，需优先遵守；若与用户当前请求冲突，以用户当前请求为准。\n\n"
        + text
    )
    _CACHE["path"] = key
    _CACHE["mtime"] = float(st.st_mtime)
    _CACHE["text"] = block
    return block
