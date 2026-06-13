"""HTTP SSE chat streaming — simpler transport than WebSocket for agent turns."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from starlette.responses import StreamingResponse

from ly_next.agent.chat_pipeline import (
    ChatTurnRequest,
    await_user_persist,
    effective_turn_mode,
    prepare_chat_turn,
)
from ly_next.agent.chat_runtime import bind_agent_deps, iter_turn_stream
from ly_next.agent.image_reply import ensure_mixed_reply
from ly_next.core.chat_trace_log import chat_info as chat_trace_info
from ly_next.core.chat_trace_log import chat_warn as chat_trace_warn
from ly_next.core.config import config
from ly_next.core.observability import attach_run_fields
from ly_next.core.run_lifecycle import finish_observed_run, start_observed_run
from ly_next.core.task_manager import get_task_manager
from ly_next.core.thread_persistence import persist_chat_turn
from ly_next.messaging.models import mixed_message_to_dict

router = APIRouter(tags=["chat-stream"])


class ChatStreamRequest(BaseModel):
    messages: list[dict[str, Any]]
    model: str | None = None
    provider: str | None = None
    mode: str = "react"
    temperature: float = 0.7
    max_tokens: int = 2048
    vision_precaption: bool | None = None
    thread_id: str | None = None
    channel: str | None = "web"
    tool_call_mode: str | None = None
    mcp_enabled_slugs: list[str] | None = None


def _sse(event: str, data: dict[str, Any]) -> str:
    payload = json.dumps(data, ensure_ascii=False, default=str)
    return f"event: {event}\ndata: {payload}\n\n"


def _map_agent_event(ev: dict[str, Any], *, task_id: str) -> tuple[str, dict[str, Any]] | None:
    et = str(ev.get("type") or "")
    base = {"task_id": task_id}
    if et == "status":
        return "status", {**base, **ev}
    if et == "chunk":
        return "token", {**base, "content": ev.get("content") or ""}
    if et == "think_chunk":
        return "think", {**base, "content": ev.get("content") or ""}
    if et == "tool_start":
        return "tool_start", {**base, **ev}
    if et == "tool_done":
        return "tool_done", {**base, **ev}
    if et == "final":
        return "final", {**base, **ev}
    return None


async def _iter_chat_sse(req: ChatStreamRequest) -> AsyncIterator[str]:
    manager = get_task_manager()
    task_id = await manager.create_task(name="Chat SSE")
    await manager.update(task_id, status="running")
    telemetry_token = None
    run_status = "ok"
    run_error: str | None = None
    prepared = None
    full_response = ""

    try:
        chat_req = ChatTurnRequest(
            client_messages=list(req.messages),
            thread_id=req.thread_id,
            mode=req.mode,
            temperature=req.temperature,
            max_tokens=req.max_tokens,
            provider=req.provider,
            model=req.model,
            skip_vision_precaption=req.vision_precaption is False,
            tool_call_mode=req.tool_call_mode,
            channel=req.channel or "web",
            mcp_enabled_slugs=req.mcp_enabled_slugs,
            turn_meta_extra={"task_id": task_id, "requested_mode": req.mode, "channel": "web"},
        )
        prepared = await prepare_chat_turn(chat_req)
        mode = effective_turn_mode(prepared)
        from ly_next.agent.chat_pipeline import ensure_mcp_tools_for_mode

        await ensure_mcp_tools_for_mode(mode)
        chat_trace_info(
            "sse_prepared",
            task_id=task_id,
            effective_mode=mode,
            thread_id=prepared.thread_id,
        )
        yield _sse(
            "started",
            {
                "task_id": task_id,
                "run_id": task_id,
                "thread_id": prepared.thread_id,
                "mode": mode,
                "router": prepared.router_payload,
            },
        )

        telemetry_token = await start_observed_run(
            task_id,
            mode=mode,
            thread_id=prepared.thread_id,
            router=prepared.router_payload,
        )
        deps = bind_agent_deps(
            prepared,
            mode=mode,
            temperature=req.temperature,
            max_tokens=req.max_tokens,
            tool_call_mode=req.tool_call_mode,
            stop_event=manager.get_stop_event(task_id),
            channel=req.channel or "web",
        )

        async for ev in iter_turn_stream(prepared, deps, mode=mode):
            if not isinstance(ev, dict):
                continue
            mapped = _map_agent_event(ev, task_id=task_id)
            if mapped is None:
                continue
            event_name, payload = mapped
            if event_name == "final":
                full_response = str(ev.get("content") or "")
            yield _sse(event_name, payload)

        await await_user_persist(prepared)
        mixed = await ensure_mixed_reply(deps, full_response)
        mixed_payload = mixed_message_to_dict(mixed)
        image_urls = mixed.image_urls()
        if prepared.thread_id:
            await persist_chat_turn(
                prepared.thread_id,
                [],
                full_response,
                metadata={
                    **prepared.turn_meta,
                    "run_id": task_id,
                    "mixed_message": mixed_payload,
                    "image_urls": image_urls,
                },
            )
        await manager.complete(task_id, result=full_response)
    except Exception as exc:
        run_status = "error"
        run_error = str(exc)
        chat_trace_warn("sse_failed", task_id=task_id, error=run_error)
        await manager.fail(task_id, run_error)
        yield _sse("error", {"task_id": task_id, "error": run_error})
    finally:
        snap = None
        if telemetry_token is not None:
            snap = await finish_observed_run(
                telemetry_token, task_id, status=run_status, error=run_error
            )
        complete_body: dict[str, Any] = {"task_id": task_id, "run_id": task_id}
        if prepared is not None:
            complete_body["thread_id"] = prepared.thread_id
        if snap:
            complete_body = attach_run_fields(complete_body, snap)
        yield _sse("complete", complete_body)


@router.post("/chat/stream")
async def chat_stream(request: ChatStreamRequest):
    if not bool(config.get("agent.enabled", True)):
        raise HTTPException(status_code=503, detail="agent disabled")
    return StreamingResponse(
        _iter_chat_sse(request),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
