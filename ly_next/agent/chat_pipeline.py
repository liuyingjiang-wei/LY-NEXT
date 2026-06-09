from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

from ly_next.agent.chat_middleware import get_chat_middleware_chain
from ly_next.agent.deps import AgentDeps, create_agent_deps
from ly_next.agent.image_reply import begin_agent_run, ensure_mixed_reply
from ly_next.agent.chat_model import ChatModelSelection, resolve_chat_model, selection_payload
from ly_next.agent.prompt_augment import augment_messages_async, last_user_query
from ly_next.agent.turn_engine import iter_agent_turn
from ly_next.agent.turn_plan import (
    TurnPlan,
    build_turn_plan,
    pipeline_cfg,
    resolve_augment_skips,
    resolve_effective_mode,
)
from ly_next.agent.vision_precaption import (
    apply_vision_precaption_if_needed,
    messages_need_vision_precaption,
)
from ly_next.core.config import config
from ly_next.core.thread_persistence import persist_chat_turn, prepare_messages_for_agent
from ly_next.messaging.models import MixedMessage, mixed_message_to_dict
from ly_next.tools import get_tool_registry

__all__ = [
    "ChatTurnRequest",
    "PreparedChatTurn",
    "ChatTurnOutcome",
    "TurnPlan",
    "build_turn_plan",
    "resolve_effective_mode",
    "resolve_augment_skips",
    "prepare_chat_turn",
    "build_agent_deps",
    "run_agent_on_prepared",
    "run_agent_stream_on_prepared",
    "execute_chat_turn",
    "await_user_persist",
]


@dataclass
class ChatTurnRequest:
    client_messages: list[dict[str, Any]]
    thread_id: str | None = None
    mode: str = "react"
    temperature: float = 0.7
    max_tokens: int = 2048
    provider: str | None = None
    model: str | None = None
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
    channel: str | None = None


@dataclass
class PreparedChatTurn:
    thread_id: str | None
    messages: list[dict[str, Any]]
    user_to_persist: list[dict[str, Any]]
    routed: ChatModelSelection
    turn_meta: dict[str, Any]
    router_payload: dict[str, Any]
    plan: TurnPlan | None = None
    _user_persist_task: asyncio.Task[None] | None = None


@dataclass
class ChatTurnOutcome:
    prepared: PreparedChatTurn
    deps: AgentDeps
    mode: str
    text: str
    mixed: MixedMessage


async def await_user_persist(prepared: PreparedChatTurn) -> None:
    task = prepared._user_persist_task
    if task is not None:
        await asyncio.gather(task, return_exceptions=True)


async def prepare_chat_turn(req: ChatTurnRequest) -> PreparedChatTurn:
    middleware = get_chat_middleware_chain()
    mw_ctx: dict[str, Any] = {
        "channel": req.channel,
        "mode": req.mode,
        "thread_id": req.thread_id,
    }
    client_messages = await middleware.before_prepare(list(req.client_messages), mw_ctx)

    thread_id, messages, user_to_persist = await prepare_messages_for_agent(
        req.thread_id,
        client_messages,
        history_limit=req.history_limit,
    )

    plan = build_turn_plan(req, messages)
    effective_mode = plan.effective_mode

    parallel = (
        req.parallel_prep if req.parallel_prep is not None else bool(pipeline_cfg("parallel_prep", True))
    )
    overlap_augment = bool(pipeline_cfg("overlap_augment", True))
    needs_vision = messages_need_vision_precaption(
        messages, skip_precaption=req.skip_vision_precaption
    )

    async def _route(msgs: list[dict[str, Any]]) -> ChatModelSelection:
        return resolve_chat_model(
            request_name=req.provider,
            request_model=req.model,
        )

    skip_rag, skip_context = plan.skip_rag, plan.skip_context
    skip_memory = plan.skip_memory
    skip_skills = plan.skip_skills

    async def _augment(msgs: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if plan.skip_augment or req.skip_augment is True:
            return msgs
        return await augment_messages_async(
            msgs,
            skip_rag=skip_rag,
            skip_context=skip_context,
            skip_memory=skip_memory,
            skip_skills=skip_skills,
        )

    if parallel and overlap_augment and not needs_vision:
        messages, routed = await asyncio.gather(_augment(messages), _route(messages))
    elif parallel:
        messages, routed = await asyncio.gather(
            apply_vision_precaption_if_needed(
                messages,
                skip_precaption=req.skip_vision_precaption,
            ),
            _route(messages),
        )
        messages = await _augment(messages)
    else:
        messages = await apply_vision_precaption_if_needed(
            messages,
            skip_precaption=req.skip_vision_precaption,
        )
        routed = await _route(messages)
        messages = await _augment(messages)

    messages = await middleware.after_prepare(messages, {**mw_ctx, "plan": plan})

    turn_meta = {
        "mode": effective_mode,
        "requested_mode": plan.requested_mode,
        "fast_path": plan.fast_path,
        **(req.turn_meta_extra or {}),
    }
    if req.channel:
        turn_meta["channel"] = str(req.channel).strip()

    persist_async = (
        req.persist_user_async
        if req.persist_user_async is not None
        else bool(pipeline_cfg("persist_user_async", True))
    )

    user_persist_task: asyncio.Task[None] | None = None
    if user_to_persist and thread_id:
        if persist_async:
            user_persist_task = asyncio.create_task(
                persist_chat_turn(thread_id, user_to_persist, None, metadata=turn_meta)
            )
        else:
            await persist_chat_turn(thread_id, user_to_persist, None, metadata=turn_meta)

    return PreparedChatTurn(
        thread_id=thread_id,
        messages=messages,
        user_to_persist=user_to_persist,
        routed=routed,
        turn_meta=turn_meta,
        router_payload=selection_payload(routed),
        plan=plan,
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
    channel: str | None = None,
    agent_mode: str | None = None,
) -> AgentDeps:
    from ly_next.agent.channel_tools import apply_channel_tool_policy
    from ly_next.core.logger import get_logger
    from ly_next.models.factory import LLMFactory
    from ly_next.models.registry import ModelRegistry

    routed = prepared.routed
    deps = create_agent_deps(
        provider=routed.name,
        model=routed.model,
        stop_event=stop_event,
    )
    try:
        from ly_next.models.timeout import llm_timeout_seconds

        kw = ModelRegistry.build_client_kwargs(
            routed.name,
            model_override=routed.model,
            timeout=llm_timeout_seconds(agent=True),
        )
        deps.llm_client = LLMFactory.get_client(**kw)
        deps.provider = routed.name
        deps.model = routed.model
    except Exception as e:
        get_logger(__name__).warning(
            "Failed to bind LLM client for registry model %s: %s", routed.name, e
        )
    if temperature is not None:
        deps.temperature = temperature
    if max_tokens is not None:
        deps.max_tokens = max_tokens
    mode_key = (agent_mode or prepared.turn_meta.get("mode") or "react").strip().lower()
    if mode_key != "chat":
        deps.tool_registry = get_tool_registry()
        ch = channel or prepared.turn_meta.get("channel")
        apply_channel_tool_policy(deps, ch)
    else:
        deps.tool_registry = None
    deps.thread_id = prepared.thread_id
    if tool_call_mode is not None:
        deps.tool_call_mode = str(tool_call_mode).strip().lower() or deps.tool_call_mode
    if begin_run:
        begin_agent_run(deps)
    return deps


def effective_turn_mode(prepared: PreparedChatTurn) -> str:
    return str(prepared.turn_meta.get("mode") or "react").strip().lower()


async def run_agent_on_prepared(
    prepared: PreparedChatTurn,
    deps: AgentDeps,
    *,
    mode: str | None = None,
) -> str:
    mode_key = mode or effective_turn_mode(prepared)
    final = ""
    async for ev in iter_agent_turn(prepared.messages, deps, mode=mode_key):
        if isinstance(ev, dict) and ev.get("type") == "final":
            final = str(ev.get("content") or "")
    return final


async def run_agent_stream_on_prepared(
    prepared: PreparedChatTurn,
    deps: AgentDeps,
    *,
    mode: str | None = None,
):
    mode_key = mode or effective_turn_mode(prepared)
    async for event in iter_agent_turn(prepared.messages, deps, mode=mode_key):
        yield event


async def execute_chat_turn(
    req: ChatTurnRequest,
    *,
    stop_event: Any = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
    tool_call_mode: str | None = None,
    channel: str | None = None,
    persist_assistant: bool = True,
    task_id: str | None = None,
) -> ChatTurnOutcome:
    """Unified blocking turn: prepare → LLM → mixed reply → optional persist."""
    middleware = get_chat_middleware_chain()
    prepared = await prepare_chat_turn(req)
    mode = effective_turn_mode(prepared)
    deps = build_agent_deps(
        prepared,
        temperature=temperature if temperature is not None else req.temperature,
        max_tokens=max_tokens if max_tokens is not None else req.max_tokens,
        tool_call_mode=tool_call_mode or req.tool_call_mode,
        stop_event=stop_event,
        channel=channel or req.channel,
        agent_mode=mode,
    )
    text = await run_agent_on_prepared(prepared, deps, mode=mode)
    text = await middleware.after_agent(text, {"mode": mode, "plan": prepared.plan})
    mixed = await ensure_mixed_reply(deps, text)
    if persist_assistant and prepared.thread_id:
        meta = {
            **prepared.turn_meta,
            "mixed_message": mixed_message_to_dict(mixed),
            "image_urls": mixed.image_urls(),
        }
        if task_id:
            meta["task_id"] = task_id
            meta["run_id"] = task_id
        await persist_chat_turn(prepared.thread_id, [], text, metadata=meta)
    await await_user_persist(prepared)
    return ChatTurnOutcome(prepared=prepared, deps=deps, mode=mode, text=text, mixed=mixed)
