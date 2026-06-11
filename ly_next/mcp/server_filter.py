"""Filter MCP registry tools by per-chat enabled server slugs."""

from __future__ import annotations

from typing import Any

from ly_next.core.config import config


def mcp_tool_matches_slug(tool_name: str, slug: str, *, use_prefix: bool) -> bool:
    name = str(tool_name or "").strip()
    s = str(slug or "").strip()
    if not name or not s:
        return False
    if use_prefix:
        return name == s or name.startswith(f"{s}__")
    return name == s


def filter_tools_by_mcp_slugs(
    tools: list[Any],
    enabled_slugs: frozenset[str] | None,
    *,
    use_prefix: bool | None = None,
) -> list[Any]:
    if enabled_slugs is None:
        return tools
    prefix = use_prefix
    if prefix is None:
        prefix = bool(config.get("tools.mcp.langgraph_tool_name_prefix", True))

    out: list[Any] = []
    for t in tools or []:
        cat = getattr(getattr(t, "definition", None), "category", None)
        if cat != "mcp":
            out.append(t)
            continue
        name = getattr(getattr(t, "definition", None), "name", "") or ""
        if enabled_slugs and any(mcp_tool_matches_slug(name, slug, use_prefix=prefix) for slug in enabled_slugs):
            out.append(t)
    return out
