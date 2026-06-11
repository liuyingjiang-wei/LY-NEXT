from __future__ import annotations

from typing import Any

from ly_next.agent.deps import AgentDeps
from ly_next.agent.tool_router import route_tools_by_query, semantic_select_enabled
from ly_next.core.config import config
from ly_next.core.logger import get_logger

logger = get_logger(__name__)

_TIER_RANK = {"safe": 0, "general": 1, "image": 1, "network": 2, "host": 3}
_STRIP_SCHEMA_KEYS = frozenset({"description", "examples", "title"})


def _tool_schema_cfg(key: str, default: Any) -> Any:
    return config.get(f"agent.tool_schema.{key}", default)


def _compact_json_schema(schema: Any) -> Any:
    if not isinstance(schema, dict):
        return schema
    out: dict[str, Any] = {}
    for key, value in schema.items():
        if key in _STRIP_SCHEMA_KEYS:
            continue
        if key == "properties" and isinstance(value, dict):
            out[key] = {
                name: _compact_json_schema(prop)
                for name, prop in value.items()
                if isinstance(prop, dict)
            }
            continue
        if key in ("items", "additionalProperties") and isinstance(value, dict):
            out[key] = _compact_json_schema(value)
            continue
        if key in ("anyOf", "oneOf", "allOf") and isinstance(value, list):
            out[key] = [_compact_json_schema(item) for item in value]
            continue
        out[key] = value
    return out


def compact_openai_tool(tool: dict[str, Any]) -> dict[str, Any]:
    """Shrink one OpenAI function tool schema for native tool-calling."""
    if (tool.get("type") or "").strip().lower() != "function":
        return tool
    fn = tool.get("function")
    if not isinstance(fn, dict):
        return tool

    params = fn.get("parameters")
    compact_params = _compact_json_schema(params) if isinstance(params, dict) else params

    desc = str(fn.get("description") or "").strip()
    props = compact_params.get("properties") if isinstance(compact_params, dict) else None
    if isinstance(props, dict) and props:
        keys = ", ".join(list(props.keys())[:30])
        suffix = f" (args: {keys})"
        if suffix not in desc:
            desc = f"{desc}{suffix}".strip()

    max_chars = int(_tool_schema_cfg("max_description_chars", 280) or 280)
    if max_chars > 0 and len(desc) > max_chars:
        desc = desc[: max(1, max_chars - 1)].rstrip() + "…"

    return {
        "type": "function",
        "function": {
            "name": fn.get("name"),
            "description": desc,
            "parameters": compact_params,
        },
    }


def compact_openai_tools(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [compact_openai_tool(t) for t in tools or []]


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


def _pick_tools(
    registry: Any,
    *,
    allow_tools: list[str] | None,
    deny: set[str],
    cats: set[str] | None,
    max_tr: int,
    limit: int,
) -> list[Any]:
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

    return picked[:limit]


def filter_tools_for_agent(
    registry: Any,
    *,
    allow_tools: list[str] | None,
    deny_tools: list[str],
    allow_categories: list[str] | None,
    max_tier: str,
    max_tools: int,
    router_query: str | None = None,
    router_query_vec: list[float] | None = None,
    router_tool_vectors: dict[str, list[float]] | None = None,
    router_method: str | None = None,
) -> tuple[list[Any], list[str]]:
    deny = {x.strip() for x in deny_tools if isinstance(x, str) and x.strip()}
    max_tr = max_tier_rank(max_tier)
    cats = (
        {c.strip().lower() for c in allow_categories if isinstance(c, str) and c.strip()}
        if allow_categories
        else None
    )

    raw_limit = int(max_tools)
    if raw_limit <= 0:
        logger.warning("[tool_filter] max_tools=%s is invalid; using 40", max_tools)
        raw_limit = 40

    use_semantic = bool(semantic_select_enabled() and (router_query or "").strip())
    pool_limit = 9999 if use_semantic else raw_limit

    picked = _pick_tools(
        registry,
        allow_tools=allow_tools,
        deny=deny,
        cats=cats,
        max_tr=max_tr,
        limit=pool_limit,
    )

    registered = registry.list_tools()
    if not picked and registered:
        if allow_tools is not None and len(allow_tools) == 0:
            logger.debug("[tool_filter] allow_tools is empty list — exposing no tools by policy")
            return [], []

        logger.warning(
            "[tool_filter] agent.tool_policy excluded all %s registered tools; "
            "retrying with deny-list + tier only (ignore allow_tools / allow_categories whitelist)",
            len(registered),
        )
        picked = _pick_tools(
            registry,
            allow_tools=None,
            deny=deny,
            cats=None,
            max_tr=max_tr,
            limit=pool_limit,
        )

    if not picked and registered:
        remain = [t for t in registered if t.definition.name not in deny]
        if remain:
            logger.warning(
                "[tool_filter] tier policy still yielded none; exposing %s tools not on deny_tools",
                len(remain),
            )
            picked = remain[:pool_limit]

    if use_semantic and picked:
        policy = config.get("agent.tool_policy", {}) or {}
        if not isinstance(policy, dict):
            policy = {}
        semantic_k = int(policy.get("semantic_top_k", 15) or 15)
        cap = max(1, min(raw_limit, semantic_k))
        picked = route_tools_by_query(
            str(router_query),
            picked,
            limit=cap,
            query_vec=router_query_vec,
            tool_vectors=router_tool_vectors,
            method=router_method,
        )

    from ly_next.mcp.search_dedup import apply_search_tool_dedup

    picked = apply_search_tool_dedup(picked)

    names = [t.definition.name for t in picked]
    logger.debug("[tool_filter] visible tools (%s): %s", len(names), names)
    return picked, names


def get_filtered_tools_for_deps(deps: AgentDeps) -> tuple[list[Any], list[str]]:
    """Return visible tools for this run, cached on deps for the agent loop."""
    cached = getattr(deps, "_filtered_tools_cache", None)
    if cached is not None:
        return cached

    registry = deps.tool_registry
    if not registry:
        empty: tuple[list[Any], list[str]] = ([], [])
        deps._filtered_tools_cache = empty
        return empty

    picked = filter_tools_for_agent(
        registry,
        allow_tools=deps.tool_allow_tools,
        deny_tools=deps.tool_deny_tools,
        allow_categories=deps.tool_allow_categories,
        max_tier=deps.tool_max_tier,
        max_tools=deps.max_tools,
        router_query=getattr(deps, "tool_router_query", None),
        router_query_vec=getattr(deps, "tool_router_query_vec", None),
        router_tool_vectors=getattr(deps, "tool_router_tool_vectors", None),
        router_method=getattr(deps, "tool_router_method", None),
    )
    deps._filtered_tools_cache = picked
    return picked


def get_openai_tools_for_deps(
    deps: AgentDeps,
) -> tuple[list[dict[str, Any]], list[str], list[Any]]:
    """OpenAI tool schemas + allowed names, cached per agent run."""
    cached = getattr(deps, "_openai_tools_cache", None)
    if cached is not None:
        return cached

    objs, names = get_filtered_tools_for_deps(deps)
    openai_tools = [t.definition.to_openai_format() for t in objs]
    if bool(_tool_schema_cfg("compact_native", True)):
        openai_tools = compact_openai_tools(openai_tools)
    result: tuple[list[dict[str, Any]], list[str], list[Any]] = (openai_tools, names, objs)
    deps._openai_tools_cache = result
    return result
