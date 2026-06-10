"""Thin LangGraph wrapper for native ReAct (prep → react_step ⇄ execute_tools)."""

from __future__ import annotations

import asyncio
from contextlib import suppress
from collections.abc import AsyncIterator
from typing import Any, Literal

from langgraph.graph import END, StateGraph

from ly_next.agent.deps import AgentDeps
from ly_next.agent.react.native_steps import NativeReactSession
from ly_next.core.checkpointer import compile_graph, graph_astream
from ly_next.core.logger import get_logger
from ly_next.core.run_graph import (
    NODE_DIRECT_ANSWER,
    NODE_EXECUTE_TOOLS,
    NODE_PREP,
    NODE_REACT_STEP,
    emit_graph_edge,
    emit_graph_node_enter,
    emit_graph_node_exit,
)

logger = get_logger(__name__)

SENTINEL = object()


class NativeGraphState(dict):
    """LangGraph state for native ReAct (plain dict for checkpoint serialization)."""

    messages: list[dict[str, Any]]
    dialog: list[dict[str, Any]]
    openai_tools: list[dict[str, Any]]
    allowed_names: list[str]
    last_sig: str
    same_sig_count: int
    fail_streak: int
    run_tag: str
    budget_used: int
    iteration: int
    done: bool
    direct_only: bool
    pending_tool_calls: list[dict[str, Any]]
    phase: str
    route: str


def _route_after_prep(state: dict[str, Any]) -> Literal["direct_answer", "react_step"]:
    if state.get("direct_only"):
        return "direct_answer"
    return "react_step"


def _route_after_llm(state: dict[str, Any]) -> Literal["execute_tools", END]:
    if state.get("done"):
        return END
    if state.get("pending_tool_calls"):
        return "execute_tools"
    return END


def _route_after_tools(state: dict[str, Any]) -> Literal["react_step", END]:
    if state.get("done"):
        return END
    # Let react_step enforce max_steps and emit the final message.
    return "react_step"


def build_native_react_graph(deps: AgentDeps) -> StateGraph:
    emit_queue: asyncio.Queue[Any] = asyncio.Queue()

    async def emit(ev: dict[str, Any]) -> None:
        await emit_queue.put(ev)

    async def prep(state: dict[str, Any]) -> dict[str, Any]:
        messages = list(state.get("messages") or [])
        session = NativeReactSession.from_messages(messages, deps)
        emit_graph_node_enter(NODE_PREP, loop_kind="langgraph_native")
        emit_graph_node_exit(NODE_PREP, outcome="ready", loop_kind="langgraph_native")
        if session.direct_only:
            emit_graph_edge(NODE_PREP, NODE_DIRECT_ANSWER, loop_kind="langgraph_native")
            async for ev in session.iter_direct_answer():
                await emit(ev)
            patch = session.to_state()
            patch["done"] = True
            patch["phase"] = "done"
            return patch

        emit_graph_edge(NODE_PREP, NODE_REACT_STEP, loop_kind="langgraph_native")
        patch = session.to_state()
        patch["max_steps"] = deps.max_steps
        patch["phase"] = "llm"
        return patch

    async def react_step(state: dict[str, Any]) -> dict[str, Any]:
        max_steps = int(state.get("max_steps") or deps.max_steps)
        if int(state.get("iteration") or 0) >= max_steps:
            from ly_next.agent.react.native_steps import graph_finish_final

            graph_finish_final(iteration=max(0, max_steps - 1), outcome="max_steps")
            await emit({"type": "final", "content": "Maximum steps reached."})
            patch = dict(state)
            patch["done"] = True
            patch["phase"] = "done"
            return patch

        session = NativeReactSession.from_state(state, deps)
        async for ev in session.step_llm():
            await emit(ev)
        patch = session.to_state()
        patch["max_steps"] = deps.max_steps
        if session.done:
            patch["phase"] = "done"
        elif session.pending_tool_calls:
            patch["phase"] = "tools"
        else:
            patch["phase"] = "llm"
        return patch

    async def execute_tools(state: dict[str, Any]) -> dict[str, Any]:
        session = NativeReactSession.from_state(state, deps)
        async for ev in session.step_tools():
            await emit(ev)
        patch = session.to_state()
        patch["max_steps"] = deps.max_steps
        if session.done:
            patch["phase"] = "done"
        else:
            patch["phase"] = "llm"
        return patch

    graph = StateGraph(dict)
    graph.add_node("prep", prep)
    graph.add_node("react_step", react_step)
    graph.add_node("execute_tools", execute_tools)
    graph.set_entry_point("prep")
    graph.add_conditional_edges(
        "prep",
        _route_after_prep,
        {"direct_answer": END, "react_step": "react_step"},
    )
    graph.add_conditional_edges(
        "react_step",
        _route_after_llm,
        {"execute_tools": "execute_tools", END: END},
    )
    graph.add_conditional_edges(
        "execute_tools",
        _route_after_tools,
        {"react_step": "react_step", END: END},
    )

    graph._native_emit_queue = emit_queue  # type: ignore[attr-defined]
    return graph


async def iter_langgraph_native_react(
    messages: list[dict[str, Any]],
    deps: AgentDeps,
) -> AsyncIterator[dict[str, Any]]:
    """Run native ReAct through a thin LangGraph with optional checkpointing."""
    if not deps.tool_registry:
        raise RuntimeError("no tool registry")

    graph = build_native_react_graph(deps)
    queue: asyncio.Queue[Any] = graph._native_emit_queue  # type: ignore[attr-defined]
    app = compile_graph(graph)

    init: dict[str, Any] = {"messages": list(messages), "phase": "prep", "done": False}

    async def run_graph() -> None:
        try:
            async for _chunk in graph_astream(app, init, deps.thread_id):
                pass
        finally:
            await queue.put(SENTINEL)

    task = asyncio.create_task(run_graph())
    try:
        while True:
            item = await queue.get()
            if item is SENTINEL:
                break
            if isinstance(item, dict):
                yield item
    finally:
        if not task.done():
            task.cancel()
        with suppress(asyncio.CancelledError):
            await task
        exc = task.exception()
        if exc is not None:
            raise exc
