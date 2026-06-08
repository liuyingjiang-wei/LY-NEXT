"""ReAct agent: native, compat, and legacy LangGraph execution modes."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from ly_next.agent.deps import AgentDeps, create_agent_deps
from ly_next.agent.image_reply import finalize_agent_reply
from ly_next.agent.react.graph import build_react_graph
from ly_next.agent.react.helpers import (
    aborted,
    looks_tool_blind_response,
    react_loop_kind,
    tool_blind_fallback,
)
from ly_next.agent.react.loops import iter_compat_react, iter_native_react
from ly_next.agent.state import create_initial_state
from ly_next.core.checkpointer import compile_graph, graph_astream
from ly_next.core.logger import get_logger
from ly_next.core.run_telemetry import (
    get_run_loop_kind,
    record_stream_event,
    set_run_loop_kind,
)
from ly_next.messaging.models import mixed_message_to_dict

logger = get_logger(__name__)


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
            if isinstance(ev, dict) and ev.get("type") == "final":
                text = str(ev.get("content") or "")
                _, mixed, _ = await finalize_agent_reply(self.deps, text)
                ev = {
                    **ev,
                    "mixed_message": mixed_message_to_dict(mixed),
                    "image_urls": mixed.image_urls(),
                }
            yield ev

    async def _iter_react_inner(
        self, messages: list[dict[str, Any]], kind: str
    ) -> AsyncIterator[dict[str, Any]]:
        if kind == "compat":
            async for ev in iter_compat_react(messages, self.deps):
                yield ev
            return

        if kind == "native":
            saw_tool = False
            final_text = ""
            pending_final: dict[str, Any] | None = None
            try:
                async for ev in iter_native_react(messages, self.deps):
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
                    if saw_tool or et in ("chunk", "status"):
                        yield ev
                    else:
                        yield ev
                if not saw_tool and looks_tool_blind_response(final_text):
                    fb = tool_blind_fallback(self.deps)
                    logger.warning("[agent] native tool-blind; fallback=%s", fb)
                    if fb == "compat":
                        set_run_loop_kind("compat")
                        async for ev in iter_compat_react(messages, self.deps):
                            yield ev
                        return
                    set_run_loop_kind("legacy")
                    async for ev in self._iter_legacy_graph(messages):
                        yield ev
                    return
                if pending_final is not None:
                    yield pending_final
                return
            except Exception as e:
                logger.warning("[agent] native ReAct failed, legacy graph: %s", e)
                kind = "legacy"
                set_run_loop_kind(kind)

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
