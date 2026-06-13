"""Persist adapted stdio MCP server configs to skip re-probing across restarts."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from ly_next.core.config import config
from ly_next.core.logger import get_logger

logger = get_logger(__name__)


def _cache_path() -> Path:
    root = config.project_root / "data" / "ly_next" / "cache"
    root.mkdir(parents=True, exist_ok=True)
    return root / "mcp_stdio_adapted.json"


def mcp_config_fingerprint(merged: dict[str, dict[str, Any]]) -> str:
    payload = json.dumps(merged, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def load_adapted_cache(fingerprint: str) -> dict[str, dict[str, Any]] | None:
    path = _cache_path()
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.debug("[mcp] adapt cache read failed: %s", exc)
        return None
    if not isinstance(data, dict):
        return None
    if str(data.get("fingerprint") or "") != fingerprint:
        return None
    servers = data.get("servers")
    if not isinstance(servers, dict):
        return None
    return {str(k): v for k, v in servers.items() if isinstance(v, dict)}


def save_adapted_cache(fingerprint: str, merged: dict[str, dict[str, Any]]) -> None:
    path = _cache_path()
    try:
        path.write_text(
            json.dumps(
                {"fingerprint": fingerprint, "servers": merged},
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
    except OSError as exc:
        logger.debug("[mcp] adapt cache write failed: %s", exc)
