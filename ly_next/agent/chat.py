from collections.abc import AsyncIterator
from typing import Any

from ly_next.agent.deps import AgentDeps, create_agent_deps
from ly_next.agent.turn_engine import (
    collect_turn_text,
    iter_direct_answer,
    normalize_dialog_messages,
)
from ly_next.core.logger import get_logger
from ly_next.core.run_graph import (
    NODE_DIRECT_ANSWER,
    NODE_PREP,
    emit_graph_edge,
    emit_graph_node_enter,
    emit_graph_node_exit,
)
from ly_next.core.run_telemetry import set_run_loop_kind

logger = get_logger(__name__)


class ChatAgent:
    def __init__(self, deps: AgentDeps | None = None, **kwargs):
        if deps is None:
            deps = create_agent_deps(**kwargs)
        self.deps = deps

    async def run(self, messages: list[dict[str, Any]]) -> str:
        if not messages:
            return "No messages provided."

        set_run_loop_kind("chat")
        return await collect_turn_text(self.run_stream(messages))

    async def run_stream(self, messages: list[dict[str, Any]]) -> AsyncIterator[dict[str, Any]]:
        if not messages:
            yield {"type": "error", "content": "No messages provided."}
            return

        set_run_loop_kind("chat")
        emit_graph_node_enter(NODE_PREP, loop_kind="chat")
        emit_graph_node_exit(NODE_PREP, outcome="ready", loop_kind="chat")
        emit_graph_edge(NODE_PREP, NODE_DIRECT_ANSWER, loop_kind="chat")
        emit_graph_node_enter(NODE_DIRECT_ANSWER, loop_kind="chat")
        async for ev in iter_direct_answer(
            self.deps,
            messages,
            status_detail="直接对话",
            phase="answer",
        ):
            yield ev
        emit_graph_node_exit(NODE_DIRECT_ANSWER, outcome="done", loop_kind="chat")

    def _process_messages(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return normalize_dialog_messages(messages)
