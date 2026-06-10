"""Run graph schema and event helpers for native ReAct observability."""

from __future__ import annotations

from typing import Any

from ly_next.core.run_telemetry import emit_run_event

GRAPH_NODE_ENTER = "graph_node_enter"
GRAPH_NODE_EXIT = "graph_node_exit"
GRAPH_EDGE = "graph_edge"

# Native ReAct (default hot path)
NODE_PREP = "prep"
NODE_REACT_STEP = "react_step"
NODE_EXECUTE_TOOLS = "execute_tools"
NODE_FINALIZE = "finalize"
NODE_DIRECT_ANSWER = "direct_answer"

# Compat / legacy aliases
NODE_COMPAT_STEP = "compat_step"
NODE_LEGACY_PLAN = "plan"
NODE_LEGACY_ACT = "act"
NODE_LEGACY_CHECK = "check_steps"

NATIVE_REACT_SCHEMA: dict[str, Any] = {
    "id": "native_react",
    "label": "Native ReAct",
    "nodes": [
        {"id": NODE_PREP, "label": "Prepare context"},
        {"id": NODE_REACT_STEP, "label": "LLM (tool_calls)"},
        {"id": NODE_EXECUTE_TOOLS, "label": "Execute tools"},
        {"id": NODE_FINALIZE, "label": "Final answer"},
        {"id": NODE_DIRECT_ANSWER, "label": "Direct answer"},
    ],
    "edges": [
        {"from": NODE_PREP, "to": NODE_REACT_STEP},
        {"from": NODE_REACT_STEP, "to": NODE_EXECUTE_TOOLS, "condition": "tool_calls"},
        {"from": NODE_REACT_STEP, "to": NODE_FINALIZE, "condition": "final"},
        {"from": NODE_REACT_STEP, "to": NODE_DIRECT_ANSWER, "condition": "no_tools"},
        {"from": NODE_EXECUTE_TOOLS, "to": NODE_REACT_STEP, "condition": "loop"},
    ],
}

LEGACY_REACT_SCHEMA: dict[str, Any] = {
    "id": "legacy_react",
    "label": "Legacy LangGraph ReAct",
    "nodes": [
        {"id": NODE_PREP, "label": "Prepare context"},
        {"id": NODE_LEGACY_PLAN, "label": "Plan (JSON decision)"},
        {"id": NODE_LEGACY_ACT, "label": "Act (tool)"},
        {"id": NODE_LEGACY_CHECK, "label": "Check steps"},
        {"id": NODE_FINALIZE, "label": "Final answer"},
    ],
    "edges": [
        {"from": NODE_PREP, "to": NODE_LEGACY_PLAN},
        {"from": NODE_LEGACY_PLAN, "to": NODE_LEGACY_ACT, "condition": "tool"},
        {"from": NODE_LEGACY_PLAN, "to": NODE_FINALIZE, "condition": "final"},
        {"from": NODE_LEGACY_ACT, "to": NODE_LEGACY_CHECK},
        {"from": NODE_LEGACY_CHECK, "to": NODE_LEGACY_PLAN, "condition": "loop"},
    ],
}

COMPAT_REACT_SCHEMA: dict[str, Any] = {
    "id": "compat_react",
    "label": "Compat JSON ReAct",
    "nodes": [
        {"id": NODE_PREP, "label": "Prepare context"},
        {"id": NODE_COMPAT_STEP, "label": "LLM (JSON decision)"},
        {"id": NODE_EXECUTE_TOOLS, "label": "Execute tool"},
        {"id": NODE_FINALIZE, "label": "Final answer"},
    ],
    "edges": [
        {"from": NODE_PREP, "to": NODE_COMPAT_STEP},
        {"from": NODE_COMPAT_STEP, "to": NODE_EXECUTE_TOOLS, "condition": "tool"},
        {"from": NODE_COMPAT_STEP, "to": NODE_FINALIZE, "condition": "final"},
        {"from": NODE_EXECUTE_TOOLS, "to": NODE_COMPAT_STEP, "condition": "loop"},
    ],
}

CHAT_SCHEMA: dict[str, Any] = {
    "id": "chat",
    "label": "Direct chat",
    "nodes": [
        {"id": NODE_PREP, "label": "Prepare context"},
        {"id": NODE_DIRECT_ANSWER, "label": "Stream answer"},
    ],
    "edges": [{"from": NODE_PREP, "to": NODE_DIRECT_ANSWER}],
}


def schema_for_loop_kind(loop_kind: str | None, mode: str | None = None) -> dict[str, Any]:
    lk = (loop_kind or "").strip().lower()
    md = (mode or "").strip().lower()
    if md == "chat":
        return dict(CHAT_SCHEMA)
    if lk == "legacy":
        return dict(LEGACY_REACT_SCHEMA)
    if lk == "compat":
        return dict(COMPAT_REACT_SCHEMA)
    if lk in ("native", "langgraph_native"):
        return dict(NATIVE_REACT_SCHEMA)
    return dict(NATIVE_REACT_SCHEMA)


def emit_graph_node_enter(node: str, **payload: Any) -> None:
    emit_run_event(GRAPH_NODE_ENTER, {"node": node, **payload})


def emit_graph_node_exit(node: str, **payload: Any) -> None:
    emit_run_event(GRAPH_NODE_EXIT, {"node": node, **payload})


def emit_graph_edge(from_node: str, to_node: str, **payload: Any) -> None:
    emit_run_event(GRAPH_EDGE, {"from": from_node, "to": to_node, **payload})


def _graph_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    graph_kinds = {GRAPH_NODE_ENTER, GRAPH_NODE_EXIT, GRAPH_EDGE, "node"}
    out: list[dict[str, Any]] = []
    for ev in events:
        kind = str(ev.get("kind") or "")
        if kind not in graph_kinds:
            continue
        payload = ev.get("payload") if isinstance(ev.get("payload"), dict) else {}
        row: dict[str, Any] = {
            "seq": ev.get("seq"),
            "kind": kind,
            "created_at": ev.get("created_at"),
        }
        if kind == "node":
            row["node"] = payload.get("node")
            row["data"] = payload.get("data")
        elif kind == GRAPH_EDGE:
            row["from"] = payload.get("from")
            row["to"] = payload.get("to")
            for key in ("iteration", "tools", "reason", "outcome"):
                if key in payload:
                    row[key] = payload[key]
        else:
            row["node"] = payload.get("node")
            for key in ("iteration", "outcome", "detail", "loop_kind", "tools"):
                if key in payload:
                    row[key] = payload[key]
        out.append(row)
    return out


def _executed_path(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    path: list[dict[str, Any]] = []
    for row in _graph_events(events):
        kind = row.get("kind")
        if kind == GRAPH_NODE_ENTER:
            path.append(
                {
                    "seq": row.get("seq"),
                    "node": row.get("node"),
                    "iteration": row.get("iteration"),
                    "action": "enter",
                }
            )
        elif kind == GRAPH_NODE_EXIT:
            path.append(
                {
                    "seq": row.get("seq"),
                    "node": row.get("node"),
                    "iteration": row.get("iteration"),
                    "action": "exit",
                    "outcome": row.get("outcome"),
                }
            )
        elif kind == GRAPH_EDGE:
            path.append(
                {
                    "seq": row.get("seq"),
                    "from": row.get("from"),
                    "to": row.get("to"),
                    "iteration": row.get("iteration"),
                    "action": "edge",
                    "tools": row.get("tools"),
                }
            )
        elif kind == "node":
            path.append(
                {
                    "seq": row.get("seq"),
                    "node": row.get("node"),
                    "action": "legacy_node",
                    "data": row.get("data"),
                }
            )
    return path


def _graph_stats(events: list[dict[str, Any]]) -> dict[str, Any]:
    iterations: set[int] = set()
    for row in _graph_events(events):
        it = row.get("iteration")
        if isinstance(it, int):
            iterations.add(it)
        elif isinstance(it, str) and it.isdigit():
            iterations.add(int(it))
    tool_names: list[str] = []
    for ev in events:
        if str(ev.get("kind") or "") not in ("tool_start", "tool_end"):
            continue
        payload = ev.get("payload") if isinstance(ev.get("payload"), dict) else {}
        name = str(payload.get("tool") or "").strip()
        if name:
            tool_names.append(name)
    return {
        "react_iterations": len(iterations) if iterations else 0,
        "tool_calls": len(tool_names),
        "tools_used": sorted(set(tool_names)),
        "graph_events": len(_graph_events(events)),
    }


def _mermaid_from_schema(schema: dict[str, Any], executed: list[dict[str, Any]]) -> str:
    lines = ["flowchart LR"]
    for edge in schema.get("edges") or []:
        if not isinstance(edge, dict):
            continue
        src = edge.get("from")
        dst = edge.get("to")
        cond = edge.get("condition")
        if not src or not dst:
            continue
        label = f"|{cond}|" if cond else ""
        lines.append(f"  {src}{label} --> {dst}")
    visited = {row.get("node") for row in executed if row.get("node")}
    if visited:
        hot = ",".join(sorted(str(n) for n in visited if n))
        lines.append("  classDef visited fill:#dbeafe,stroke:#2563eb")
        lines.append(f"  class {hot} visited")
    return "\n".join(lines)


def build_run_graph(
    run_id: str,
    events: list[dict[str, Any]],
    *,
    loop_kind: str | None = None,
    mode: str | None = None,
) -> dict[str, Any]:
    """Build graph view from persisted run events."""
    schema = schema_for_loop_kind(loop_kind, mode)
    timeline = _graph_events(events)
    executed = _executed_path(events)
    return {
        "run_id": run_id,
        "loop_kind": loop_kind,
        "mode": mode,
        "graph_schema": schema,
        "executed_path": executed,
        "timeline": timeline,
        "stats": _graph_stats(events),
        "mermaid": _mermaid_from_schema(schema, executed),
    }
