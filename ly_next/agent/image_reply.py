from __future__ import annotations

from typing import Any

from ly_next.agent.deps import AgentDeps
from ly_next.agent.run_context import set_current_thread_id
from ly_next.agent.state import AgentState
from ly_next.messaging.image_handler import build_mixed_message
from ly_next.messaging.models import MixedMessage, mixed_message_to_dict
from ly_next.tools.image_quota import get_remaining_quota
from ly_next.tools.image_tool_helpers import append_image_embed_hint


def record_tool_result(deps: AgentDeps, tool_name: str, result: Any) -> None:
    deps.collected_tool_results.append({"tool": tool_name, "result": result})


def format_image_tool_observation(tool_name: str, formatted: str) -> str:
    return append_image_embed_hint(formatted, tool_name)


async def finalize_agent_reply(
    deps: AgentDeps,
    text: str,
    *,
    state: AgentState | None = None,
) -> tuple[str, MixedMessage, AgentState | None]:
    """Build MixedMessage and optional state updates after agent completes."""
    mixed = build_mixed_message(text, deps.collected_tool_results)
    deps.last_mixed_message = mixed

    uk = deps.thread_id or "anonymous"
    remaining = await get_remaining_quota(uk)

    updates: AgentState | None = None
    if state is not None:
        updates = {
            **state,
            "final_response": text,
            "mixed_message": mixed_message_to_dict(mixed),
            "image_quota_remaining": remaining,
            "tool_results": list(deps.collected_tool_results),
        }

    return text, mixed, updates


def begin_agent_run(deps: AgentDeps) -> None:
    deps.collected_tool_results = []
    deps.last_mixed_message = None
    set_current_thread_id(deps.thread_id)
