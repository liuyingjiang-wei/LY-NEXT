"""Avoid duplicate web-search tool exposure (builtin web_search vs MCP search tools)."""

from __future__ import annotations

import re
from typing import Any

from ly_next.core.config import config
from ly_next.core.logger import get_logger

logger = get_logger(__name__)

_BUILTIN_SEARCH_TOOLS = frozenset({"web_search"})
_MCP_SEARCH_NAME_RE = re.compile(
    r"(^|__)(bing_)?search|web_?search|crawl_webpage|fetch_webpage|webpage_crawl",
    re.IGNORECASE,
)


def _mcp_search_dedup_cfg() -> dict[str, Any]:
    tools = config.get("tools") or {}
    if not isinstance(tools, dict):
        return {}
    mcp = tools.get("mcp") or {}
    if not isinstance(mcp, dict):
        return {}
    raw = mcp.get("search_dedup") or {}
    return raw if isinstance(raw, dict) else {}


def search_dedup_strategy() -> str:
    strategy = str(_mcp_search_dedup_cfg().get("strategy") or "prefer_builtin").strip().lower()
    if strategy in ("prefer_builtin", "prefer_mcp", "both"):
        return strategy
    return "prefer_builtin"


def is_mcp_search_tool(tool: Any) -> bool:
    cat = (tool.definition.category or "").strip().lower()
    if cat != "mcp":
        return False
    name = (tool.definition.name or "").strip()
    if not name:
        return False
    if _MCP_SEARCH_NAME_RE.search(name):
        return True
    desc = (tool.definition.description or "").lower()
    return "search" in desc and ("bing" in desc or "网页" in desc or "web" in desc)


def list_mcp_search_tool_names(tools: list[Any]) -> list[str]:
    return [t.definition.name for t in tools if is_mcp_search_tool(t)]


def apply_search_tool_dedup(picked: list[Any]) -> list[Any]:
    """Filter visible tools so builtin and MCP search stacks do not compete."""
    strategy = search_dedup_strategy()
    if strategy == "both" or not picked:
        return picked

    mcp_search = [t for t in picked if is_mcp_search_tool(t)]
    builtin_search = [t for t in picked if t.definition.name in _BUILTIN_SEARCH_TOOLS]

    if not mcp_search or not builtin_search:
        return picked

    if strategy == "prefer_builtin":
        drop = {t.definition.name for t in mcp_search}
        kept = [t for t in picked if t.definition.name not in drop]
        logger.info(
            "[mcp/search_dedup] prefer_builtin: hiding MCP search tools %s (use web_search → web_fetch)",
            sorted(drop),
        )
        return kept

    if strategy == "prefer_mcp":
        drop = _BUILTIN_SEARCH_TOOLS
        kept = [t for t in picked if t.definition.name not in drop]
        logger.info(
            "[mcp/search_dedup] prefer_mcp: hiding builtin %s (MCP search tools available: %s)",
            sorted(drop),
            [t.definition.name for t in mcp_search],
        )
        return kept

    return picked
