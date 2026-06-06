"""Security helpers for dynamically loaded plugin modules."""

from __future__ import annotations

from ly_next.api.loader_security import sha256_file, trusted_hashes_map
from ly_next.core.config import config
from ly_next.core.logger import get_logger

logger = get_logger(__name__)

__all__ = ["plugin_security_profile", "sha256_file", "trusted_plugin_hashes_map"]


def plugin_security_profile() -> str:
    raw = config.get("plugins.security_profile")
    if raw is None or str(raw).strip() == "":
        raw = config.get("api.security_profile", "development")
    profile = str(raw or "development").strip().lower()
    if profile in ("development", "production", "verified"):
        return profile
    logger.warning("[PluginLoader] unknown plugins.security_profile=%r; using development", raw)
    return "development"


def trusted_plugin_hashes_map() -> dict[str, str]:
    raw = config.get("plugins.trusted_module_hashes")
    if raw is None:
        return trusted_hashes_map()
    if not isinstance(raw, dict):
        return {}
    out: dict[str, str] = {}
    for k, v in raw.items():
        if isinstance(k, str) and isinstance(v, str) and k.strip() and v.strip():
            out[k.strip().replace("\\", "/")] = v.strip().lower()
    return out
