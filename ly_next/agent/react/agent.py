"""ReAct agent: native, compat, and legacy LangGraph execution modes."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from ly_next.agent.deps import AgentDeps, create_agent_deps
from ly_next.agent.react.graph import build_react_graph
from ly_next.agent.react.helpers import (
    aborted,
    format_agent_error,
    looks_tool_blind_response,
    native_react_failure_message,
    react_loop_kind,
    should_skip_native_legacy_fallback,
    tool_blind_fallback,
)
from ly_next.agent.react.loops import iter_compat_react, iter_native_react
from ly_next.agent.react.native_graph import iter_langgraph_native_react
from ly_next.agent.state import create_initial_state
from ly_next.core.checkpointer import compile_graph, graph_astream
from ly_next.core.logger import get_logger
from ly_next.core.run_graph import (
    NODE_COMPAT_STEP,
    NODE_PREP,
    NODE_REACT_STEP,
    emit_graph_edge,
    emit_graph_node_enter,
    emit_graph_node_exit,
)
from ly_next.core.run_telemetry import (
    get_run_loop_kind,
    record_stream_event,
    set_run_loop_kind,
)

logger = get_logger(__name__)

_STREAM_TYPES = frozenset({"chunk", "status", "think_chunk"})


async def _iter_native_variant_stream(
    agent: ReactAgent,
    messages: list[dict[str, Any]],
    *,
    kind: str,
    stream: AsyncIterator[dict[str, Any]],
) -> AsyncIterator[dict[str, Any]]:
    """Stream native/langgraph_native events with tool-blind fallback."""
    saw_tool = False
    final_text = ""
    pending_final: dict[str, Any] | None = None
    try:
        async for ev in stream:
            if not isinstance(ev, dict):
                yield ev
                continue
            et = ev.get("type")
            if et == "tool_start":
                saw_tool = True
                if pending_final is not None:
                    yield pending_final
                    pending_final = None
                yield ev
                continue
            if et == "final":
                final_text = str(ev.get("content") or "")
                if saw_tool:
                    yield ev
                else:
                    pending_final = ev
                continue
            if saw_tool or et in _STREAM_TYPES:
                yield ev
            else:
                yield ev
        if not saw_tool and looks_tool_blind_response(final_text):
            fb = tool_blind_fallback(agent.deps)
            logger.warning("[agent] %s tool-blind; fallback=%s", kind, fb)
            if fb == "compat":
                set_run_loop_kind("compat")
                async for ev in iter_compat_react(messages, agent.deps):
                    yield ev
                return
            set_run_loop_kind("legacy")
            async for ev in agent._iter_legacy_graph(messages):
                yield ev
            return
        if pending_final is not None:
            yield pending_final
    except Exception as e:
        summary = format_agent_error(e)
        if should_skip_native_legacy_fallback(e):
            logger.warning(
                "[agent] %s ReAct failed (%s); skip legacy fallback",
                kind,
                summary,
            )
            yield {"type": "final", "content": native_react_failure_message(e)}
            return
        logger.warning("[agent] %s failed, legacy graph: %s", kind, summary)
        set_run_loop_kind("legacy")
        async for ev in agent._iter_legacy_graph(messages):
            yield ev


class ReactAgent:
    def __init__(self, deps: AgentDeps | None = None, **kwargs):
        if deps is None:
            deps = create_agent_deps(**kwargs)
        self.deps = deps
        self.graph = build_react_graph(deps)
        self.app = compile_graph(self.graph)

    async def _iter_legacy_graph(
        self, messages: list[dict[str, Any]]
    ) -> AsyncIterator[dict[str, Any]]:
        init = create_initial_state(messages)
        async for chunk in graph_astream(self.app, init, self.deps.thread_id):
            if aborted(self.deps):
                yield {"type": "final", "content": "（对话已由用户中断）"}
                return
            for node_name, node_output in chunk.items():
                if isinstance(node_output, dict) and "decision" in node_output:
                    logger.debug("[agent] %s: %s", node_name, node_output["decision"])
                yield {"type": "node", "node": node_name, "data": node_output}
                if isinstance(node_output, dict) and "decision" in node_output:
                    decision = node_output["decision"]
                    if decision.get("kind") == "final":
                        yield {"type": "final", "content": decision.get("final", "")}
                        return

    async def _iter_react(self, messages: list[dict[str, Any]]) -> AsyncIterator[dict[str, Any]]:
        kind = react_loop_kind(self.deps)
        set_run_loop_kind(kind)
        async for ev in self._iter_react_inner(messages, kind):
            record_stream_event(ev)
            yield ev

    async def _iter_react_inner(
        self, messages: list[dict[str, Any]], kind: str
    ) -> AsyncIterator[dict[str, Any]]:
        # langgraph_native prep/graph events are owned by native_graph.py nodes.
        if kind != "langgraph_native":
            emit_graph_node_enter(NODE_PREP, loop_kind=kind)
            emit_graph_node_exit(NODE_PREP, outcome="ready", loop_kind=kind)
        if kind == "compat":
            emit_graph_edge(NODE_PREP, NODE_COMPAT_STEP, loop_kind=kind)
            async for ev in iter_compat_react(messages, self.deps):
                yield ev
            return

        if kind == "langgraph_native":
            async for ev in _iter_native_variant_stream(
                self,
                messages,
                kind=kind,
                stream=iter_langgraph_native_react(messages, self.deps),
            ):
                yield ev
            return

        if kind == "native":
            emit_graph_edge(NODE_PREP, NODE_REACT_STEP, loop_kind=kind)
            async for ev in _iter_native_variant_stream(
                self,
                messages,
                kind=kind,
                stream=iter_native_react(messages, self.deps),
            ):
                yield ev
            return

        if kind == "legacy":
            async for ev in self._iter_legacy_graph(messages):
                yield ev

    async def run(self, messages: list[dict[str, Any]]) -> str:
        final = ""
        async for ev in self._iter_react(messages):
            if isinstance(ev, dict) and ev.get("type") == "final":
                final = str(ev.get("content") or "")
        if final:
            return final
        if get_run_loop_kind() == "legacy":
            return "Agent produced no valid decision."
        return ""

    async def run_stream(self, messages: list[dict[str, Any]]) -> AsyncIterator[dict[str, Any]]:
        async for ev in self._iter_react(messages):
            yield ev
