"""Shared chat turn lifecycle for HTTP and WebSocket handlers."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

from ly_next.agent.chat_pipeline import (
    ChatTurnRequest,
    PreparedChatTurn,
    await_user_persist,
    build_agent_deps,
    effective_turn_mode,
    prepare_chat_turn,
    run_agent_on_prepared,
    run_agent_stream_on_prepared,
)
from ly_next.agent.deps import AgentDeps
from ly_next.agent.image_reply import ensure_mixed_reply
from ly_next.core.task_manager import get_task_manager
from ly_next.messaging.models import mixed_message_to_dict


@dataclass
class ChatTaskHandle:
    task_id: str
    name: str


async def begin_chat_task(name: str) -> ChatTaskHandle:
    manager = get_task_manager()
    task_id = await manager.create_task(name=name)
    await manager.update(task_id, status="running")
    return ChatTaskHandle(task_id=task_id, name=name)


async def prepare_turn(req: ChatTurnRequest) -> tuple[PreparedChatTurn, str]:
    prepared = await prepare_chat_turn(req)
    mode = effective_turn_mode(prepared)
    return prepared, mode


def bind_agent_deps(
    prepared: PreparedChatTurn,
    *,
    mode: str,
    temperature: float = 0.7,
    max_tokens: int = 2048,
    tool_call_mode: str | None = None,
    stop_event: Any = None,
    channel: str | None = None,
) -> AgentDeps:
    return build_agent_deps(
        prepared,
        temperature=temperature,
        max_tokens=max_tokens,
        tool_call_mode=tool_call_mode,
        stop_event=stop_event,
        channel=channel,
        agent_mode=mode,
    )


async def run_turn_blocking(
    prepared: PreparedChatTurn,
    deps: AgentDeps,
    *,
    mode: str,
) -> str:
    return await run_agent_on_prepared(prepared, deps, mode=mode)


async def iter_turn_stream(
    prepared: PreparedChatTurn,
    deps: AgentDeps,
    *,
    mode: str,
) -> AsyncIterator[dict[str, Any]]:
    async for event in run_agent_stream_on_prepared(prepared, deps, mode=mode):
        yield event


async def finalize_turn(
    prepared: PreparedChatTurn,
    deps: AgentDeps,
    text: str,
    *,
    task_id: str | None = None,
    persist: bool = True,
) -> dict[str, Any]:
    await await_user_persist(prepared)
    mixed = await ensure_mixed_reply(deps, text)
    mixed_payload = mixed_message_to_dict(mixed)
    image_urls = mixed.image_urls()
    if persist and prepared.thread_id:
        from ly_next.core.thread_persistence import persist_chat_turn

        meta = {
            **prepared.turn_meta,
            "mixed_message": mixed_payload,
            "image_urls": image_urls,
        }
        if task_id:
            meta["task_id"] = task_id
            meta["run_id"] = task_id
        await persist_chat_turn(prepared.thread_id, [], text, metadata=meta)
    return {
        "mixed_payload": mixed_payload,
        "image_urls": image_urls,
    }
