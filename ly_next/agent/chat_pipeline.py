from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

from ly_next.agent.deps import AgentDeps, create_agent_deps
from ly_next.agent.factory import AgentFactory
from ly_next.agent.image_reply import begin_agent_run
from ly_next.agent.model_router import ModelRoutingResult, resolve_model_routing, routing_payload
from ly_next.agent.prompt_augment import augment_messages_async
from ly_next.agent.vision_precaption import apply_vision_precaption_if_needed
from ly_next.core.config import config
from ly_next.core.thread_persistence import persist_chat_turn, prepare_messages_for_agent
from ly_next.tools import get_tool_registry


def _pipeline_cfg(key: str, default: Any) -> Any:
    return config.get(f"agent.chat_pipeline.{key}", default)


@dataclass
class ChatTurnRequest:
    client_messages: list[dict[str, Any]]
    thread_id: str | None = None
    mode: str = "react"
    temperature: float = 0.7
    max_tokens: int = 2048
    provider: str | None = None
    model: str | None = None
    router_hint: str | None = None
    use_model_router: bool | None = None
    skip_vision_precaption: bool = False
    skip_augment: bool | None = None
    skip_rag: bool = False
    skip_context: bool = False
    skip_memory: bool = False
    persist_user_async: bool | None = None
    parallel_prep: bool | None = None
    tool_call_mode: str | None = None
    turn_meta_extra: dict[str, Any] = field(default_factory=dict)
    history_limit: int | None = None


@dataclass
class PreparedChatTurn:
    thread_id: str | None
    messages: list[dict[str, Any]]
    user_to_persist: list[dict[str, Any]]
    routed: ModelRoutingResult
    turn_meta: dict[str, Any]
    router_payload: dict[str, Any]
    _user_persist_task: asyncio.Task[None] | None = None


async def await_user_persist(prepared: PreparedChatTurn) -> None:
    task = prepared._user_persist_task
    if task is not None:
        await asyncio.gather(task, return_exceptions=True)


async def prepare_chat_turn(req: ChatTurnRequest) -> PreparedChatTurn:
    thread_id, messages, user_to_persist = await prepare_messages_for_agent(
        req.thread_id,
        list(req.client_messages),
        history_limit=req.history_limit,
    )

    parallel = (
        req.parallel_prep
        if req.parallel_prep is not None
        else bool(_pipeline_cfg("parallel_prep", True))
    )

    if parallel:
        messages, routed = await asyncio.gather(
            apply_vision_precaption_if_needed(
                messages,
                skip_precaption=req.skip_vision_precaption,
            ),
            resolve_model_routing(
                messages,
                request_provider=req.provider,
                request_model=req.model,
                router_hint=req.router_hint,
                enabled_override=req.use_model_router,
            ),
        )
    else:
        messages = await apply_vision_precaption_if_needed(
            messages,
            skip_precaption=req.skip_vision_precaption,
        )
        routed = await resolve_model_routing(
            messages,
            request_provider=req.provider,
            request_model=req.model,
            router_hint=req.router_hint,
            enabled_override=req.use_model_router,
        )

    turn_meta = {"mode": req.mode, **(req.turn_meta_extra or {})}
    persist_async = (
        req.persist_user_async
        if req.persist_user_async is not None
        else bool(_pipeline_cfg("persist_user_async", True))
    )

    user_persist_task: asyncio.Task[None] | None = None
    if user_to_persist and thread_id:
        if persist_async:
            user_persist_task = asyncio.create_task(
                persist_chat_turn(thread_id, user_to_persist, None, metadata=turn_meta)
            )
        else:
            await persist_chat_turn(thread_id, user_to_persist, None, metadata=turn_meta)

    skip_augment = req.skip_augment is True
    if not skip_augment:
        messages = await augment_messages_async(
            messages,
            skip_rag=req.skip_rag,
            skip_context=req.skip_context,
            skip_memory=req.skip_memory,
        )

    return PreparedChatTurn(
        thread_id=thread_id,
        messages=messages,
        user_to_persist=user_to_persist,
        routed=routed,
        turn_meta=turn_meta,
        router_payload=routing_payload(routed),
        _user_persist_task=user_persist_task,
    )


def build_agent_deps(
    prepared: PreparedChatTurn,
    *,
    temperature: float | None = None,
    max_tokens: int | None = None,
    tool_call_mode: str | None = None,
    stop_event: Any = None,
    begin_run: bool = True,
) -> AgentDeps:
    deps = create_agent_deps(
        provider=prepared.routed.provider,
        model=prepared.routed.model,
        stop_event=stop_event,
    )
    if temperature is not None:
        deps.temperature = temperature
    if max_tokens is not None:
        deps.max_tokens = max_tokens
    deps.tool_registry = get_tool_registry()
    deps.thread_id = prepared.thread_id
    if tool_call_mode is not None:
        deps.tool_call_mode = str(tool_call_mode).strip().lower() or deps.tool_call_mode
    if begin_run:
        begin_agent_run(deps)
    return deps


async def run_agent_on_prepared(
    prepared: PreparedChatTurn,
    deps: AgentDeps,
    *,
    mode: str,
) -> str:
    agent = AgentFactory.create_agent(mode=mode, deps=deps)
    return await agent.run(prepared.messages) or ""


async def run_agent_stream_on_prepared(
    prepared: PreparedChatTurn,
    deps: AgentDeps,
    *,
    mode: str,
):
    agent = AgentFactory.create_agent(mode=mode, deps=deps)
    async for event in agent.run_stream(prepared.messages):
        yield event
