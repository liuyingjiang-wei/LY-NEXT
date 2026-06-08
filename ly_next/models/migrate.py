"""Migrate legacy per-format LLM config blocks into ``llm.models`` registry."""

from __future__ import annotations

from typing import Any

from ly_next.core.config import config
from ly_next.core.logger import get_logger

logger = get_logger(__name__)

_LEGACY_FORMAT_BLOCKS: tuple[tuple[str, str], ...] = (
    ("openai", "openai_llm"),
    ("anthropic", "anthropic_llm"),
    ("ollama", "ollama_llm"),
    ("openai_compat", "openai_compat_llm"),
)

_EXTRA_FIELDS = (
    "auth_mode",
    "auth_header_name",
    "token_field",
    "model_aliases",
    "headers",
    "path",
)


def _block_to_entry(name: str, fmt: str, block: dict[str, Any]) -> dict[str, Any] | None:
    model_id = str(block.get("model") or "").strip()
    if not model_id:
        return None
    entry: dict[str, Any] = {
        "name": name,
        "format": fmt,
        "model": model_id,
        "api_key": str(block.get("api_key") or ""),
        "base_url": str(block.get("base_url") or ""),
    }
    for key in _EXTRA_FIELDS:
        if key in block and block[key] not in (None, "", {}):
            entry[key] = block[key]
    return entry


def ensure_llm_models_migrated(*, save: bool = True) -> bool:
    """If ``llm.models`` is empty, populate from legacy ``*_llm`` blocks."""
    raw = config.get("llm.models")
    if isinstance(raw, list) and raw:
        return False

    migrated: list[dict[str, Any]] = []
    for name, block_key in _LEGACY_FORMAT_BLOCKS:
        block = config.get(block_key, {}) or {}
        if not isinstance(block, dict):
            continue
        entry = _block_to_entry(name, name, block)
        if entry:
            migrated.append(entry)

    if not migrated:
        return False

    names = {m["name"] for m in migrated}
    default_legacy = str(config.get("llm.default_provider") or "openai").strip().lower()
    default_model = default_legacy if default_legacy in names else migrated[0]["name"]

    llm_block = config.get("llm", {}) or {}
    if not isinstance(llm_block, dict):
        llm_block = {}
    llm_block = dict(llm_block)
    llm_block["models"] = migrated
    llm_block["default_model"] = default_model
    if not llm_block.get("default_provider"):
        llm_block["default_provider"] = default_model

    config.set("llm", llm_block, save=False)
    if save:
        config.save()
    logger.info(
        "Migrated %s legacy LLM block(s) into llm.models (default=%s)",
        len(migrated),
        default_model,
    )
    return True
