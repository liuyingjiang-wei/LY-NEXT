from __future__ import annotations

from typing import Any

from ly_next.core.config import config
from ly_next.core.logger import get_logger
from ly_next.rag.retrieval_fusion import bm25_rank, tokenize
from ly_next.rag.similarity import cosine_similarity

logger = get_logger(__name__)


def _policy() -> dict[str, Any]:
    raw = config.get("agent.tool_policy", {}) or {}
    return raw if isinstance(raw, dict) else {}


def semantic_select_enabled() -> bool:
    return bool(_policy().get("semantic_select", False))


def pin_tool_names() -> list[str]:
    raw = _policy().get("pin_tools")
    if not isinstance(raw, list) or not raw:
        return ["list_tools", "describe_tool"]
    names = [str(x).strip() for x in raw if str(x).strip()]
    return names or ["list_tools", "describe_tool"]


def tool_document(tool: Any) -> str:
    name = tool.definition.name
    desc = (tool.definition.description or "").strip()
    return f"{name}\n{desc}" if desc else name


def _router_limits(policy: dict[str, Any]) -> dict[str, Any]:
    return {
        "min_absolute": float(policy.get("semantic_min_score", 0.32) or 0.32),
        "relative_factor": float(policy.get("semantic_relative_factor", 0.92) or 0.92),
        "min_pool": int(policy.get("semantic_min_pool", 8) or 8),
        "fallback": str(policy.get("semantic_fallback") or "pins_only").strip().lower(),
    }


def _name_match_boost(query: str, tool_name: str) -> float:
    q = (query or "").lower()
    name = tool_name.lower()
    if name in q:
        return 0.45
    spaced = name.replace("_", " ")
    if spaced in q:
        return 0.4
    q_tokens = set(tokenize(q))
    name_tokens = set(tokenize(spaced))
    if name_tokens and name_tokens <= q_tokens:
        return 0.35
    return 0.0


def score_tools_lexical(query: str, tools: list[Any]) -> list[tuple[float, Any]]:
    q = (query or "").strip()
    if not q or not tools:
        return []

    corpus = [tool_document(t) for t in tools]
    ranked = bm25_rank(q, corpus)
    if not ranked:
        return []

    max_raw = max((s for s, _ in ranked), default=0.0)
    if max_raw <= 0:
        return [(0.0, tools[i]) for i in range(len(tools))]

    by_idx: dict[int, float] = {}
    used: set[int] = set()
    for raw_score, text in ranked:
        idx = next((i for i, doc in enumerate(corpus) if i not in used and doc == text), -1)
        if idx < 0:
            continue
        used.add(idx)
        norm = raw_score / max_raw
        boost = _name_match_boost(q, tools[idx].definition.name)
        by_idx[idx] = min(1.0, norm + boost)

    ordered = sorted(by_idx.items(), key=lambda x: x[1], reverse=True)
    return [(score, tools[idx]) for idx, score in ordered]


def score_tools_embedding(
    tools: list[Any],
    *,
    query_vec: list[float],
    tool_vectors: dict[str, list[float]],
) -> list[tuple[float, Any]]:
    scored: list[tuple[float, Any]] = []
    for tool in tools:
        vec = tool_vectors.get(tool.definition.name)
        if not vec:
            continue
        scored.append((cosine_similarity(query_vec, vec), tool))
    scored.sort(key=lambda x: x[0], reverse=True)
    return scored


def _apply_threshold(
    scored: list[tuple[float, Any]],
    *,
    limit: int,
    min_absolute: float,
    relative_factor: float,
) -> list[Any]:
    if not scored:
        return []
    top = scored[0][0]
    if top < min_absolute:
        return []
    cutoff = top * relative_factor
    picked: list[Any] = []
    seen: set[str] = set()
    for score, tool in scored:
        if score < cutoff:
            break
        name = tool.definition.name
        if name in seen:
            continue
        seen.add(name)
        picked.append(tool)
        if len(picked) >= limit:
            break
    return picked


def _merge_pins(ordered: list[Any], tools: list[Any], *, limit: int) -> list[Any]:
    by_name = {t.definition.name: t for t in tools}
    seen = {t.definition.name for t in ordered}
    out = list(ordered)
    for name in pin_tool_names():
        tool = by_name.get(name)
        if tool and name not in seen:
            out.insert(0, tool)
            seen.add(name)
    return out[:limit]


def _pins_only(tools: list[Any], *, limit: int) -> list[Any]:
    by_name = {t.definition.name: t for t in tools}
    out: list[Any] = []
    seen: set[str] = set()
    for name in pin_tool_names():
        tool = by_name.get(name)
        if tool and name not in seen:
            out.append(tool)
            seen.add(name)
    return out[: max(1, limit)]


def route_tools_by_query(
    query: str,
    tools: list[Any],
    *,
    limit: int,
    query_vec: list[float] | None = None,
    tool_vectors: dict[str, list[float]] | None = None,
    method: str | None = None,
) -> list[Any]:
    q = (query or "").strip()
    if not q or not tools:
        return tools[:limit]

    policy = _policy()
    limits = _router_limits(policy)
    if len(tools) <= limits["min_pool"]:
        return tools[:limit]

    use_method = (method or str(policy.get("semantic_method") or "embedding")).strip().lower()
    if use_method not in ("embedding", "lexical", "hybrid"):
        use_method = "embedding"

    scored: list[tuple[float, Any]] = []
    if use_method in ("embedding", "hybrid") and query_vec and tool_vectors:
        scored = score_tools_embedding(tools, query_vec=query_vec, tool_vectors=tool_vectors)
    if use_method == "lexical" or (use_method == "hybrid" and not scored):
        scored = score_tools_lexical(q, tools)

    selected = _apply_threshold(
        scored,
        limit=limit,
        min_absolute=limits["min_absolute"],
        relative_factor=limits["relative_factor"],
    )

    if not selected:
        if limits["fallback"] == "pins_only":
            logger.debug(
                "[tool_router] no confident match (top=%.3f); exposing pin tools only",
                scored[0][0] if scored else 0.0,
            )
            return _pins_only(tools, limit=limit)
        return tools[:limit]

    merged = _merge_pins(selected, tools, limit=limit)
    logger.debug(
        "[tool_router] selected %s tools (method=%s top=%.3f cutoff=%.3f): %s",
        len(merged),
        use_method,
        scored[0][0] if scored else 0.0,
        (scored[0][0] * limits["relative_factor"]) if scored else 0.0,
        [t.definition.name for t in merged],
    )
    return merged
