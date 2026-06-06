"""Shared plugin metadata constants."""

from __future__ import annotations

BUILTIN_PLUGIN_NAMES: frozenset[str] = frozenset(
    {
        "ly-next-builtin",
        "ly-next-tool-directory",
        "ly-next-directory-api",
        "ly-next-bridges",
    }
)


def is_builtin_plugin_name(name: str) -> bool:
    return str(name or "").strip() in BUILTIN_PLUGIN_NAMES
