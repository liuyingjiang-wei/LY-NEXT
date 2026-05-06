"""Filter registered tools by tier / category / allowlist for agent loops."""

from __future__ import annotations

from typing import Any

from ly_next.core.logger import get_logger

logger = get_logger(__name__)

_TIER_RANK = {"safe": 0, "general": 1, "network": 2}


def tier_rank(category: str | None) -> int:
    return _TIER_RANK.get((category or "general").strip().lower(), 1)


def max_tier_rank(max_tier: str | None) -> int:
    return _TIER_RANK.get((max_tier or "network").strip().lower(), 2)


def list_tools_payload(tools: list[Any]) -> list[dict[str, Any]]:
    return [
        {
            "name": t.definition.name,
            "description": t.definition.description,
            "inputSchema": t.definition.parameters,
        }
        for t in tools
    ]


def filter_tools_for_agent(
    registry: Any,
    *,
    allow_tools: list[str] | None,
    deny_tools: list[str],
    allow_categories: list[str] | None,
    max_tier: str,
    max_tools: int,
) -> tuple[list[Any], list[str]]:
    """Return (tool objects, names) visible to the planner."""
    deny = {x.strip() for x in deny_tools if isinstance(x, str) and x.strip()}
    max_tr = max_tier_rank(max_tier)
    cats = (
        {c.strip().lower() for c in allow_categories if isinstance(c, str) and c.strip()}
        if allow_categories
        else None
    )

    picked: list[Any] = []
    for t in registry.list_tools():
        name = t.definition.name
        if name in deny:
            continue
        cat = (t.definition.category or "general").strip().lower()

        if allow_tools is not None:
            if name not in allow_tools:
                continue
        elif cats:
            if cat not in cats:
                continue
        elif tier_rank(cat) > max_tr:
            continue

        picked.append(t)

    picked = picked[: max(0, int(max_tools))]
    names = [t.definition.name for t in picked]
    logger.debug("[tool_filter] visible tools (%s): %s", len(names), names)
    return picked, names
