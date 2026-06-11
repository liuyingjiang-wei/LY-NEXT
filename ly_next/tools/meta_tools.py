from __future__ import annotations

from typing import Any

from ly_next.agent.tool_context import get_tool_run_deps
from ly_next.agent.tool_filter import filter_tools_for_agent, list_tools_payload, tier_rank
from ly_next.core.config import config
from ly_next.tools.base import ToolResult, tool


def _policy() -> dict[str, Any]:
    raw = config.get("agent.tool_policy", {}) or {}
    return raw if isinstance(raw, dict) else {}


def _visible_tools(*, category: str | None = None, max_tier: str | None = None) -> list[Any]:
    deps = get_tool_run_deps()
    if deps is not None and getattr(deps, "tool_registry", None):
        from ly_next.agent.tool_filter import get_filtered_tools_for_deps

        objs, _ = get_filtered_tools_for_deps(deps)
    else:
        from ly_next.tools import get_tool_registry

        policy = _policy()
        deny = policy.get("deny_tools") or []
        allow = policy.get("allow_tools")
        allow_cat = policy.get("allow_categories")
        max_tools = int(config.get("agent.max_tools", 40) or 40)
        tier = str(max_tier or policy.get("max_tier") or "network").strip().lower()
        objs, _ = filter_tools_for_agent(
            get_tool_registry(),
            allow_tools=allow if isinstance(allow, list) else None,
            deny_tools=deny if isinstance(deny, list) else [],
            allow_categories=allow_cat if isinstance(allow_cat, list) else None,
            max_tier=tier,
            max_tools=max_tools,
        )

    if category:
        cat = category.strip().lower()
        objs = [t for t in objs if (t.definition.category or "general").strip().lower() == cat]
    if max_tier:
        cap = tier_rank(max_tier.strip().lower())
        objs = [t for t in objs if tier_rank(t.definition.category) <= cap]
    return objs


@tool(
    name="list_tools",
    description=(
        "Call only when unsure which tool fits the task. "
        "Lists name, category, short description for tools visible this run. "
        "Not for executing work — pick a domain tool after listing."
    ),
    category="safe",
    parameters={
        "type": "object",
        "properties": {
            "category": {
                "type": "string",
                "description": "Filter: safe, general, network, host, mcp",
            },
            "max_tier": {
                "type": "string",
                "description": "Filter by max tier: safe, general, network, host",
            },
        },
        "required": [],
    },
)
async def list_tools(category: str | None = None, max_tier: str | None = None) -> ToolResult:
    objs = _visible_tools(category=category, max_tier=max_tier)
    rows = [
        {
            "name": t.definition.name,
            "category": t.definition.category or "general",
            "description": (t.definition.description or "")[:280],
        }
        for t in objs
    ]
    return ToolResult(success=True, result={"count": len(rows), "tools": rows})


@tool(
    name="describe_tool",
    description=(
        "Call after list_tools to get full JSON schema for one visible tool. "
        "Not for running the tool — use the target tool directly once args are clear."
    ),
    category="safe",
    parameters={
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Tool name"},
        },
        "required": ["name"],
    },
)
async def describe_tool(name: str) -> ToolResult:
    key = (name or "").strip()
    if not key:
        return ToolResult(success=False, error="name is required")

    objs = _visible_tools()
    match = next((t for t in objs if t.definition.name == key), None)
    if match is None:
        return ToolResult(
            success=False,
            error=f"tool not found or not visible in this run: {key}",
        )

    payload = list_tools_payload([match])[0]
    return ToolResult(
        success=True,
        result={
            "name": payload["name"],
            "category": match.definition.category or "general",
            "description": payload["description"],
            "parameters": payload["inputSchema"],
        },
    )
