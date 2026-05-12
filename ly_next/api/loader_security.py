from __future__ import annotations

import hashlib
from pathlib import Path

from ly_next.core.config import config
from ly_next.core.logger import get_logger

logger = get_logger(__name__)


def security_profile() -> str:
    raw = str(config.get("api.security_profile", "development") or "development").strip().lower()
    if raw in ("development", "production", "verified"):
        return raw
    logger.warning("[APILoader] unknown api.security_profile=%r; using development", raw)
    return "development"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def trusted_hashes_map() -> dict[str, str]:
    raw = config.get("api.trusted_module_hashes") or {}
    if not isinstance(raw, dict):
        return {}
    out: dict[str, str] = {}
    for k, v in raw.items():
        if isinstance(k, str) and isinstance(v, str) and k.strip() and v.strip():
            out[k.strip().replace("\\", "/")] = v.strip().lower()
    return out
