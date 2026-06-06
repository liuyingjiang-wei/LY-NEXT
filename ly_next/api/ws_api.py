import asyncio
import contextlib
from contextvars import Token
from typing import Any

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState

from ly_next.agent.chat_pipeline import (
    ChatTurnRequest,
    await_user_persist,
    build_agent_deps,
    prepare_chat_turn,
    run_agent_on_prepared,
    run_agent_stream_on_prepared,
)
from ly_next.agent.image_reply import ensure_mixed_reply
from ly_next.api.websocket import get_task_broadcaster, get_ws_manager
from ly_next.core.auth_http import extract_api_key_from_websocket
from ly_next.core.config import config
from ly_next.core.logger import get_logger
from ly_next.core.observability import attach_run_fields, ws_run_summary_enabled
from ly_next.core.run_lifecycle import finish_observed_run, start_observed_run
from ly_next.core.task_manager import get_task_manager
from ly_next.core.thread_persistence import persist_chat_turn
from ly_next.messaging.models import mixed_message_to_dict

router = APIRouter(tags=["websocket"])
public_router = APIRouter(tags=["websocket"])

ws_manager = get_ws_manager()
logger = get_logger(__name__)

_STREAM_CANCEL_POLL_SEC = 0.05


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


async def _pump_chat_stream_prepared(
    prepared: Any,
    deps: Any,
    mode: str,
    queue: asyncio.Queue,
) -> None:
    how = "finished"
    try:
        async for event in run_agent_stream_on_prepared(prepared, deps, mode=mode):
            await queue.put(("ev", event))
    except asyncio.CancelledError:
        how = "cancelled"
        raise
    finally:
        with contextlib.suppress(Exception):
            await queue.put(("done", how))


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
    deps = None
    mixed_payload: dict[str, Any] | None = None
    image_urls: list[str] = []

    def _abort_if_stopped() -> None:
        if manager.is_stopped(task_id):
            raise _ChatUserCancelError()

    prepared = None
    mode = str(data.get("mode", "react"))
    try:
        try:
            prepared = await prepare_chat_turn(
                ChatTurnRequest(
                    client_messages=list(client_messages),
                    thread_id=thread_id,
                    mode=mode,
                    temperature=float(data.get("temperature", 0.7)),
                    max_tokens=int(data.get("max_tokens", 2048)),
                    provider=data.get("provider"),
                    model=data.get("model"),
                    router_hint=data.get("router_hint"),
                    use_model_router=data.get("use_model_router"),
                    skip_vision_precaption=data.get("vision_precaption") is False,
                    tool_call_mode=data.get("tool_call_mode"),
                    turn_meta_extra={"task_id": task_id, "mode": mode},
                )
            )
        except ValueError as e:
            await manager.fail(task_id, str(e))
            await websocket.send_json({"type": "error", "message": str(e)})
            return

        thread_id = prepared.thread_id
        messages = prepared.messages
        routed = prepared.routed
        router_payload = prepared.router_payload
        turn_meta = prepared.turn_meta

        logger.debug(
            "[ws.chat] task=%s mode=%s stream=%s provider=%s model=%s thread=%s",
            task_id,
            mode,
            data.get("stream"),
            data.get("provider"),
            data.get("model"),
            thread_id,
        )
        telemetry_token = await start_observed_run(
            task_id,
            mode=mode,
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
        _abort_if_stopped()
        logger.debug("[ws.chat] task=%s prepare done (messages=%s)", task_id, len(messages))
        deps = build_agent_deps(
            prepared,
            temperature=float(data.get("temperature", 0.7)),
            max_tokens=int(data.get("max_tokens", 2048)),
            tool_call_mode=data.get("tool_call_mode"),
            stop_event=manager.get_stop_event(task_id),
        )
        logger.debug(
            "[ws.chat] task=%s registry_tools=%s tool_call_mode=%s",
            task_id,
            len(deps.tool_registry),
            deps.tool_call_mode,
        )
        _abort_if_stopped()
        logger.debug("[ws.chat] task=%s agent deps ready mode=%s", task_id, mode)

        full_response = ""
        use_stream = data.get("stream")
        if use_stream is None:
            use_stream = bool(config.get("agent.stream_output", True))
        if use_stream:
            logger.debug("[ws.chat] task=%s run_stream begin", task_id)
            q: asyncio.Queue = asyncio.Queue()
            pump_task = asyncio.create_task(_pump_chat_stream_prepared(prepared, deps, mode, q))
            pump_holder["task"] = pump_task
            end_reason = "finished"
            try:
                while True:
                    if manager.is_stopped(task_id):
                        end_reason = "cancelled"
                        if not pump_task.done():
                            pump_task.cancel()
                        break
                    get_task = asyncio.create_task(q.get())
                    try:
                        done, pending = await asyncio.wait(
                            {get_task},
                            timeout=_STREAM_CANCEL_POLL_SEC,
                        )
                        for task in pending:
                            task.cancel()
                        if get_task not in done:
                            continue
                        kind, payload = get_task.result()
                    finally:
                        if not get_task.done():
                            get_task.cancel()
                            with contextlib.suppress(asyncio.CancelledError):
                                await get_task
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
                            if not event.get("chunked"):
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
            run_task = asyncio.create_task(run_agent_on_prepared(prepared, deps, mode=mode))
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
            if run_status == "ok" and deps is not None:
                await await_user_persist(prepared)
                mixed = await ensure_mixed_reply(deps, full_response)
                mixed_payload = mixed_message_to_dict(mixed)
                image_urls = mixed.image_urls()
                await persist_chat_turn(
                    thread_id,
                    [],
                    full_response,
                    metadata={
                        **turn_meta,
                        "run_id": task_id,
                        "mixed_message": mixed_payload,
                        "image_urls": image_urls,
                    },
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

    if pending_complete and deps is not None:
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
                    "mixed_message": mixed_payload,
                    "image_urls": image_urls,
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
