"""Unified LLM turn execution: direct streaming + agent event pump."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from ly_next.agent.deps import AgentDeps
from ly_next.core.chat_trace_log import chat_info as chat_trace_info
from ly_next.core.chat_trace_log import chat_warn as chat_trace_warn
from ly_next.core.logger import get_logger

logger = get_logger(__name__)


def _message_has_content(content: Any) -> bool:
    if content is None:
        return False
    if isinstance(content, str):
        return bool(content.strip())
    if isinstance(content, list):
        return len(content) > 0
    return bool(content)


def normalize_dialog_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Strip empty turns; keep roles the LLM API accepts."""
    out: list[dict[str, Any]] = []
    for msg in messages or []:
        role = (msg.get("role") or "user").strip().lower()
        content = msg.get("content", "")
        if not _message_has_content(content):
            continue
        if role in ("system", "user", "assistant"):
            out.append({"role": role, "content": content})
        else:
            out.append({"role": "user", "content": content})
    return out


async def iter_direct_answer(
    deps: AgentDeps,
    messages: list[dict[str, Any]],
    *,
    status_detail: str = "直接对话",
    phase: str = "answer",
) -> AsyncIterator[dict[str, Any]]:
    """Single-pass token streaming (chat mode hot path)."""
    processed = normalize_dialog_messages(messages)
    if not processed:
        chat_trace_warn(
            "empty_dialog",
            thread_id=getattr(deps, "thread_id", None),
            raw_turns=len(messages or []),
        )
        yield {"type": "error", "content": "No messages provided."}
        return

    chat_trace_info(
        "direct_answer",
        thread_id=getattr(deps, "thread_id", None),
        turns=len(processed),
        messages=processed,
    )
    yield {"type": "status", "phase": phase, "detail": status_detail}
    parts: list[str] = []
    think_parts: list[str] = []
    try:
        async for piece in deps.iter_messages_stream(processed):
            if isinstance(piece, dict):
                ptype = piece.get("type")
                text = str(piece.get("content") or "")
                if ptype == "think" and text:
                    think_parts.append(text)
                    yield {"type": "think_chunk", "content": text}
                elif ptype == "chunk" and text:
                    parts.append(text)
                    yield {"type": "chunk", "content": text}
            elif isinstance(piece, str) and piece:
                parts.append(piece)
                yield {"type": "chunk", "content": piece}
    except Exception as e:
        logger.error("[turn_engine] direct stream failed: %s", e)
        chat_trace_warn("direct_stream_failed", thread_id=getattr(deps, "thread_id", None), error=str(e))
        yield {"type": "error", "content": str(e)}
        return

    text = "".join(parts).strip()
    if not text and think_parts:
        text = "".join(think_parts).strip()
    text = text or "No response."
    yield {"type": "final", "content": text, "chunked": bool(parts), "had_thinking": bool(think_parts)}


async def iter_agent_turn(
    messages: list[dict[str, Any]],
    deps: AgentDeps,
    *,
    mode: str,
) -> AsyncIterator[dict[str, Any]]:
    from ly_next.agent.factory import AgentFactory
    from ly_next.agent.content_trust import reset_content_trust, seed_untrusted_from_channel
    from ly_next.agent.tool_context import reset_tool_run_deps, set_tool_run_deps

    token = set_tool_run_deps(deps)
    reset_content_trust()
    seed_untrusted_from_channel(getattr(deps, "channel", None))
    try:
        if deps.tool_registry and getattr(deps, "tool_router_query", None):
            from ly_next.agent.tool_router import semantic_select_enabled
            from ly_next.agent.tool_router_index import prepare_tool_router_context

            if semantic_select_enabled():
                pool = list(deps.tool_registry.list_tools())
                await prepare_tool_router_context(deps, pool)
                deps._filtered_tools_cache = None
                deps._openai_tools_cache = None

        agent = AgentFactory.create_agent(mode=mode, deps=deps)
        async for event in agent.run_stream(messages):
            yield event
    finally:
        reset_content_trust()
        reset_tool_run_deps(token)


async def collect_turn_text(events: AsyncIterator[dict[str, Any]]) -> str:
    final = ""
    async for ev in events:
        if isinstance(ev, dict) and ev.get("type") == "final":
            final = str(ev.get("content") or "")
    return final
