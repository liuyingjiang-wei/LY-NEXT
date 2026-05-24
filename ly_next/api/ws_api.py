import asyncio
import contextlib
from contextvars import Token
from typing import Any

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState

from ly_next.agent.deps import create_agent_deps
from ly_next.agent.factory import AgentFactory
from ly_next.agent.model_router import resolve_model_routing, routing_payload
from ly_next.agent.prompt_augment import augment_messages_async
from ly_next.agent.vision_precaption import apply_vision_precaption_if_needed
from ly_next.api.bridge import (
    SUPPORTED_CHANNELS,
    emit_channel_event,
    is_supported_channel,
)
from ly_next.api.websocket import get_task_broadcaster, get_ws_manager
from ly_next.core.auth_http import extract_api_key_from_websocket
from ly_next.core.config import config
from ly_next.core.logger import get_logger
from ly_next.core.observability import attach_run_fields, ws_run_summary_enabled
from ly_next.core.run_lifecycle import finish_observed_run, start_observed_run
from ly_next.core.stdin_journal import normalize_stdin_line, publish_stdin_line
from ly_next.core.task_manager import get_task_manager
from ly_next.core.thread_persistence import persist_chat_turn, prepare_messages_for_agent
from ly_next.tools import get_tool_registry

router = APIRouter(tags=["websocket"])
public_router = APIRouter(tags=["websocket"])

ws_manager = get_ws_manager()
logger = get_logger(__name__)

_STREAM_CANCEL_POLL_SEC = 0.15


class _ChatUserCancelError(Exception):
    """Raised when the client requests stop or disconnects during chat."""


async def _ws_auth_ok(websocket: WebSocket) -> bool:
    if not config.get("auth.enabled", True):
        return True
    key = config.get("auth.api_key", "")
    if not key:
        return True
    header_name = config.get("auth.header_name", "X-API-Key")
    cookie_name = config.get("auth.cookie_name", "ly_api_key")
    allow_query = bool(config.get("auth.allow_api_key_in_query", False))
    provided = extract_api_key_from_websocket(
        websocket,
        header_name=header_name,
        cookie_name=cookie_name,
        allow_query=allow_query,
    )
    if provided == key:
        return True
    if websocket.client_state != WebSocketState.CONNECTED:
        await websocket.accept()
    await websocket.send_json({"type": "error", "message": "Unauthorized"})
    await websocket.close(code=1008)
    return False


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket, group: str | None = Query(None)):
    if not await _ws_auth_ok(websocket):
        return
    await ws_manager.connect(websocket, group=group)

    try:
        while True:
            data = await websocket.receive_json()
            await handle_ws_message(websocket, data)
    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.debug("[ws] /ws loop ended: %s", e, exc_info=True)
    finally:
        await ws_manager.disconnect(websocket)


@router.websocket("/ws/{channel}")
@public_router.websocket("/ws/{channel}")
async def websocket_channel_bridge(websocket: WebSocket, channel: str):
    if not is_supported_channel(channel):
        await websocket.accept()
        await websocket.send_json({"type": "error", "message": f"Unsupported channel: {channel}"})
        await websocket.close(code=1003)
        return
    if not await _ws_auth_ok(websocket):
        return
    await ws_manager.connect(websocket, group=channel)
    await websocket.send_json(
        {
            "type": "channel_connected",
            "channel": channel,
            "supported_channels": sorted(SUPPORTED_CHANNELS),
        }
    )

    try:
        while True:
            data = await websocket.receive_json()
            msg_type = data.get("type", "")

            if msg_type == "ping":
                await websocket.send_json({"type": "pong", "channel": channel})
                continue

            if channel == "stdin" and msg_type == "stdin_line":
                raw = data.get("line")
                if raw is None:
                    raw = data.get("text", "")
                norm = normalize_stdin_line(str(raw))
                if norm is None:
                    await websocket.send_json(
                        {
                            "type": "error",
                            "channel": channel,
                            "message": "stdin_line: empty line",
                        }
                    )
                    continue
                src = str(data.get("source") or "ws").strip() or "ws"
                await publish_stdin_line(norm, src, replay=False)
                await websocket.send_json({"type": "stdin_ack", "channel": channel, "ok": True})
                continue

            if msg_type == "publish":
                await emit_channel_event(
                    channel,
                    data.get("event", f"{channel}_event"),
                    {
                        "source": data.get("source", "ws"),
                        "payload": data.get("payload") or {},
                    },
                )
                await websocket.send_json({"type": "published", "channel": channel})
                continue

            await websocket.send_json({"type": "error", "message": f"Unknown: {msg_type}"})
    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.debug("[ws] channel=%s loop ended: %s", channel, e, exc_info=True)
    finally:
        await ws_manager.disconnect(websocket)


async def _pump_chat_stream(
    agent: Any, messages: list[dict[str, Any]], queue: asyncio.Queue
) -> None:
    how = "finished"
    try:
        async for event in agent.run_stream(messages):
            await queue.put(("ev", event))
    except asyncio.CancelledError:
        how = "cancelled"
        raise
    finally:
        with contextlib.suppress(Exception):
            await queue.put(("done", how))


async def _listen_cancel_ws(
    websocket: WebSocket,
    task_id: str,
    manager: Any,
    pump_holder: dict[str, asyncio.Task | None],
) -> None:
    async def _stop_and_cancel_pump() -> None:
        await manager.stop(task_id)
        pump_task = pump_holder.get("task")
        if pump_task is not None and not pump_task.done():
            pump_task.cancel()

    try:
        while True:
            try:
                data = await websocket.receive_json()
            except WebSocketDisconnect:
                raise
            except Exception as e:
                logger.debug("[ws.chat] cancel listener skip bad frame task=%s: %s", task_id, e)
                continue
            if data.get("type") == "ping":
                await websocket.send_json({"type": "pong"})
                continue
            if data.get("type") in ("chat_cancel", "cancel"):
                tid = str(data.get("task_id") or "")
                if tid and tid != str(task_id):
                    continue
                await _stop_and_cancel_pump()
                return
    except asyncio.CancelledError:
        return
    except WebSocketDisconnect:
        await _stop_and_cancel_pump()
    except Exception as e:
        logger.warning("[ws.chat] cancel listener ended task=%s: %s", task_id, e)
        await _stop_and_cancel_pump()


async def handle_ws_message(websocket: WebSocket, data: dict[str, Any]):
    msg_type = data.get("type", "")

    if msg_type == "ping":
        await websocket.send_json({"type": "pong"})
    elif msg_type == "chat":
        await handle_chat(websocket, data)
    elif msg_type == "join_group":
        group = data.get("group")
        if group:
            await ws_manager.join_group(websocket, group)
    elif msg_type == "leave_group":
        group = data.get("group")
        if group:
            await ws_manager.leave_group(websocket, group)
    else:
        await websocket.send_json({"type": "error", "message": f"Unknown: {msg_type}"})


async def handle_chat(websocket: WebSocket, data: dict[str, Any]):
    client_messages = data.get("messages", [])
    if not client_messages:
        await websocket.send_json({"type": "error", "message": "No messages"})
        return

    manager = get_task_manager()
    task_id = await manager.create_task(name="WebSocket Chat")
    await manager.update(task_id, status="running")

    broadcaster = get_task_broadcaster()
    await broadcaster.task_started(task_id, "WebSocket Chat")

    run_status = "ok"
    run_error: str | None = None
    run_snap: dict[str, Any] | None = None
    pending_complete = False
    pending_stopped: str | None = None
    telemetry_token: Token | None = None
    cancel_task: asyncio.Task | None = None
    pump_holder: dict[str, asyncio.Task | None] = {"task": None}
    thread_id: str | None = data.get("thread_id")

    def _abort_if_stopped() -> None:
        if manager.is_stopped(task_id):
            raise _ChatUserCancelError()

    try:
        try:
            thread_id, messages, user_to_persist = await prepare_messages_for_agent(
                thread_id, list(client_messages)
            )
        except ValueError as e:
            await manager.fail(task_id, str(e))
            await websocket.send_json({"type": "error", "message": str(e)})
            return

        logger.debug(
            "[ws.chat] task=%s mode=%s stream=%s provider=%s model=%s thread=%s",
            task_id,
            data.get("mode", "react"),
            data.get("stream"),
            data.get("provider"),
            data.get("model"),
            thread_id,
        )
        messages = await apply_vision_precaption_if_needed(
            messages,
            skip_precaption=data.get("vision_precaption") is False,
        )
        routed = await resolve_model_routing(
            messages,
            request_provider=data.get("provider"),
            request_model=data.get("model"),
            router_hint=data.get("router_hint"),
            enabled_override=data.get("use_model_router"),
        )
        router_payload = routing_payload(routed)
        telemetry_token = await start_observed_run(
            task_id,
            mode=str(data.get("mode", "react")),
            thread_id=thread_id,
            router=router_payload,
        )
        logger.info(
            "[ws.chat] task=%s routed provider=%s model=%s task_kind=%s via=%s",
            task_id,
            routed.provider,
            routed.model,
            routed.task_kind.value,
            routed.via,
        )
        await websocket.send_json(
            {
                "type": "chat_started",
                "task_id": task_id,
                "run_id": task_id,
                "thread_id": thread_id,
                "router": router_payload,
                "observability": {"ws_run_summary": ws_run_summary_enabled()},
            }
        )
        logger.debug("[ws.chat] task=%s sent chat_started", task_id)
        cancel_task = asyncio.create_task(
            _listen_cancel_ws(websocket, task_id, manager, pump_holder)
        )
        turn_meta = {"task_id": task_id, "mode": str(data.get("mode", "react"))}
        await persist_chat_turn(thread_id, user_to_persist, None, metadata=turn_meta)
        messages = await augment_messages_async(messages)
        _abort_if_stopped()
        logger.debug(
            "[ws.chat] task=%s augment_messages done (messages=%s)", task_id, len(messages)
        )
        deps = create_agent_deps(
            provider=routed.provider,
            model=routed.model,
            stop_event=manager.get_stop_event(task_id),
        )
        deps.temperature = data.get("temperature", 0.7)
        deps.max_tokens = data.get("max_tokens", 2048)
        deps.tool_registry = get_tool_registry()
        deps.thread_id = thread_id
        if data.get("tool_call_mode") is not None:
            deps.tool_call_mode = (
                str(data.get("tool_call_mode") or "").strip().lower() or deps.tool_call_mode
            )
        logger.debug(
            "[ws.chat] task=%s registry_tools=%s tool_call_mode=%s",
            task_id,
            len(deps.tool_registry),
            deps.tool_call_mode,
        )

        agent = AgentFactory.create_agent(mode=data.get("mode", "react"), deps=deps)
        _abort_if_stopped()
        logger.debug("[ws.chat] task=%s agent created mode=%s", task_id, data.get("mode", "react"))

        full_response = ""
        use_stream = data.get("stream")
        if use_stream is None:
            use_stream = bool(config.get("agent.stream_output", True))
        if use_stream:
            logger.debug("[ws.chat] task=%s run_stream begin", task_id)
            q: asyncio.Queue = asyncio.Queue()
            pump_task = asyncio.create_task(_pump_chat_stream(agent, messages, q))
            pump_holder["task"] = pump_task
            end_reason = "finished"
            try:
                while True:
                    if manager.is_stopped(task_id):
                        end_reason = "cancelled"
                        if not pump_task.done():
                            pump_task.cancel()
                        break
                    try:
                        kind, payload = await asyncio.wait_for(
                            q.get(), timeout=_STREAM_CANCEL_POLL_SEC
                        )
                    except asyncio.TimeoutError:
                        continue
                    if kind != "ev":
                        end_reason = str(payload or "finished")
                        break
                    event = payload
                    et = event.get("type")
                    if et == "chunk":
                        content = event.get("content", "")
                        if content:
                            full_response += content
                            await websocket.send_json({"type": "chat_chunk", "content": content})
                    elif et == "status":
                        await websocket.send_json(
                            {
                                "type": "chat_status",
                                "phase": event.get("phase"),
                                "detail": event.get("detail"),
                                "iteration": event.get("iteration"),
                                "tool_names": event.get("tool_names"),
                            }
                        )
                    elif et == "tool_start":
                        await websocket.send_json(
                            {
                                "type": "chat_tool_start",
                                "tool": event.get("tool"),
                                "call_id": event.get("call_id"),
                                "args_preview": event.get("args_preview"),
                                "iteration": event.get("iteration"),
                            }
                        )
                    elif et == "tool_done":
                        await websocket.send_json(
                            {
                                "type": "chat_tool_done",
                                "tool": event.get("tool"),
                                "call_id": event.get("call_id"),
                                "success": event.get("success"),
                                "result_preview": event.get("result_preview"),
                                "iteration": event.get("iteration"),
                            }
                        )
                    elif et == "node":
                        await websocket.send_json(
                            {
                                "type": "chat_node",
                                "node": event.get("node"),
                                "data": event.get("data"),
                            }
                        )
                    elif et == "final":
                        c = event.get("content") or ""
                        if c:
                            full_response = c
                            await websocket.send_json({"type": "chat_chunk", "content": c})
            finally:
                if not pump_task.done():
                    pump_task.cancel()
                await asyncio.gather(pump_task, return_exceptions=True)

            if pump_task.done() and not pump_task.cancelled():
                pump_exc = pump_task.exception()
                if pump_exc is not None:
                    raise pump_exc

            if end_reason == "cancelled" or manager.is_stopped(task_id):
                run_status = "cancelled"
                await manager.update(task_id, status="stopped", result=full_response)
                await broadcaster.task_stopped(task_id, full_response)
                pending_stopped = full_response
        else:
            run_task = asyncio.create_task(agent.run(messages))
            pump_holder["task"] = run_task
            done, pending = await asyncio.wait(
                {run_task, cancel_task}, return_when=asyncio.FIRST_COMPLETED
            )
            for t in pending:
                t.cancel()
            await asyncio.gather(run_task, cancel_task, return_exceptions=True)
            if manager.is_stopped(task_id):
                run_status = "cancelled"
                fr = ""
                if run_task.done() and not run_task.cancelled():
                    try:
                        fr = run_task.result() or ""
                    except Exception:
                        fr = ""
                await manager.update(task_id, status="stopped", result=fr)
                await broadcaster.task_stopped(task_id, fr)
                pending_stopped = fr
                full_response = fr
            elif run_task.cancelled():
                run_status = "cancelled"
                await manager.update(task_id, status="stopped", result="")
                await broadcaster.task_stopped(task_id, "")
                pending_stopped = ""
                full_response = ""
            else:
                try:
                    full_response = run_task.result() or ""
                except Exception as run_err:
                    raise run_err

        if pending_stopped is None:
            if run_status == "ok":
                await persist_chat_turn(
                    thread_id,
                    [],
                    full_response,
                    metadata={**turn_meta, "run_id": task_id},
                )
            await manager.complete(task_id, result=full_response)
            await broadcaster.task_completed(task_id, full_response)
            pending_complete = True
    except _ChatUserCancelError:
        run_status = "cancelled"
        await manager.update(task_id, status="stopped", result=full_response)
        await broadcaster.task_stopped(task_id, full_response)
        pending_stopped = full_response
    except Exception as e:
        run_status = "error"
        run_error = str(e)
        logger.exception("[ws.chat] task=%s failed: %s", task_id, e)
        await manager.fail(task_id, str(e))
        await broadcaster.task_failed(task_id, str(e))
    finally:
        if cancel_task is not None:
            if not cancel_task.done():
                cancel_task.cancel()
            await asyncio.gather(cancel_task, return_exceptions=True)

    if pending_stopped is not None:
        await websocket.send_json(
            attach_run_fields(
                {
                    "type": "chat_stopped",
                    "task_id": task_id,
                    "partial": pending_stopped,
                },
                None,
            )
        )

    if telemetry_token is not None:
        run_snap = await finish_observed_run(
            telemetry_token, task_id, status=run_status, error=run_error
        )

    if pending_complete:
        if run_snap:
            logger.info("[ws.chat] task=%s run_summary=%s", task_id, run_snap)
        await websocket.send_json(
            attach_run_fields(
                {
                    "type": "chat_complete",
                    "task_id": task_id,
                    "run_id": task_id,
                    "thread_id": thread_id,
                    "response": full_response,
                },
                run_snap,
            )
        )
    elif run_error is not None:
        try:
            await websocket.send_json(
                attach_run_fields(
                    {"type": "chat_error", "task_id": task_id, "error": run_error},
                    run_snap,
                )
            )
        except Exception as send_err:
            logger.warning(
                "[ws.chat] task=%s could not send chat_error to client: %s", task_id, send_err
            )
