import asyncio
import contextlib
from contextvars import Token
from typing import Any

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState

from ly_next.agent.chat_pipeline import ChatTurnRequest, await_user_persist
from ly_next.agent.chat_runtime import (
    bind_agent_deps,
    begin_chat_task,
    iter_turn_stream,
    prepare_turn,
    run_turn_blocking,
)
from ly_next.agent.image_reply import ensure_mixed_reply
from ly_next.api.websocket import get_task_broadcaster, get_ws_manager
from ly_next.core.auth_http import extract_api_key_from_websocket
from ly_next.core.chat_trace_log import chat_error as chat_trace_error
from ly_next.core.chat_trace_log import chat_info as chat_trace_info
from ly_next.core.chat_trace_log import chat_warn as chat_trace_warn
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


def _ws_is_connected(websocket: WebSocket) -> bool:
    state = getattr(websocket, "client_state", None)
    if not isinstance(state, WebSocketState):
        return True
    return state == WebSocketState.CONNECTED


def _is_ws_gone_error(exc: BaseException) -> bool:
    if isinstance(exc, WebSocketDisconnect):
        return True
    if isinstance(exc, RuntimeError):
        msg = str(exc).lower()
        return "websocket.send" in msg or "disconnect" in msg or "already completed" in msg
    return False


async def _send_chat_json(websocket: WebSocket, payload: dict[str, Any]) -> bool:
    """Send JSON to client. Returns False if the socket is closed (no exception raised)."""
    if not _ws_is_connected(websocket):
        return False
    try:
        await websocket.send_json(payload)
        return True
    except Exception as exc:
        if _is_ws_gone_error(exc):
            logger.debug(
                "[ws.chat] client gone, drop send type=%s",
                payload.get("type"),
            )
            return False
        if not isinstance(exc, (TypeError, ValueError)):
            raise
        logger.warning("[ws.chat] send_json failed, retrying minimal payload: %s", exc)
        minimal = {
            k: payload[k]
            for k in ("type", "task_id", "run_id", "thread_id", "response", "error", "partial")
            if k in payload
        }
        try:
            await websocket.send_json(minimal)
            return True
        except Exception as retry_exc:
            if _is_ws_gone_error(retry_exc):
                return False
            raise


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
    client = websocket.client.host if websocket.client else "-"
    chat_trace_info("ws_connect", client=client, group=group or "")
    logger.info("[ws] client=%s connected path=/api/ws group=%s", client, group or "")
    await ws_manager.connect(websocket, group=group)

    try:
        while True:
            data = await websocket.receive_json()
            msg_type = str(data.get("type") or "")
            if msg_type == "chat":
                chat_trace_info(
                    "ws_chat_frame",
                    client=client,
                    mode=data.get("mode"),
                    thread_id=data.get("thread_id"),
                    message_count=len(data.get("messages") or []),
                )
            await handle_ws_message(websocket, data)
    except WebSocketDisconnect:
        chat_trace_info("ws_disconnect", client=client)
    except RuntimeError as e:
        if _is_ws_gone_error(e):
            chat_trace_info("ws_disconnect", client=client)
        else:
            chat_trace_error("ws_loop_error", client=client, error=str(e))
            logger.exception("[ws] /ws loop ended: %s", e)
    except Exception as e:
        chat_trace_error("ws_loop_error", client=client, error=str(e))
        logger.exception("[ws] /ws loop ended: %s", e)
    finally:
        await ws_manager.disconnect(websocket)


async def _pump_chat_stream_prepared(
    prepared: Any,
    deps: Any,
    mode: str | None,
    queue: asyncio.Queue,
) -> None:
    how = "finished"
    try:
        async for event in iter_turn_stream(prepared, deps, mode=mode):
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
                if not await _send_chat_json(websocket, {"type": "pong"}):
                    return
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
        await _send_chat_json(websocket, {"type": "pong"})
    elif msg_type == "chat":
        try:
            await handle_chat(websocket, data)
        except Exception as e:
            if _is_ws_gone_error(e):
                logger.debug("[ws.chat] chat ended after client disconnect: %s", e)
                return
            chat_trace_error("chat_unhandled", error=str(e))
            logger.exception("[ws.chat] unhandled: %s", e)
            await _send_chat_json(
                websocket,
                {"type": "chat_error", "error": str(e) or "Internal chat error"},
            )
    elif msg_type == "join_group":
        group = data.get("group")
        if group:
            await ws_manager.join_group(websocket, group)
    elif msg_type == "leave_group":
        group = data.get("group")
        if group:
            await ws_manager.leave_group(websocket, group)
    else:
        await _send_chat_json(websocket, {"type": "error", "message": f"Unknown: {msg_type}"})


async def handle_chat(websocket: WebSocket, data: dict[str, Any]):
    client_messages = data.get("messages", [])
    if not client_messages:
        await _send_chat_json(websocket, {"type": "error", "message": "No messages"})
        return

    thread_id: str | None = data.get("thread_id")
    requested_mode = str(data.get("mode", "react"))

    manager = get_task_manager()
    handle = await begin_chat_task("WebSocket Chat")
    task_id = handle.task_id
    logger.info(
        "[ws.chat] recv task=%s mode=%s thread=%s messages=%s",
        task_id,
        requested_mode,
        thread_id or "-",
        len(client_messages),
    )

    broadcaster = get_task_broadcaster()
    await broadcaster.task_started(task_id, "WebSocket Chat")

    if not await _send_chat_json(websocket, {"type": "chat_ack", "task_id": task_id}):
        await manager.fail(task_id, "client disconnected before ack")
        return

    chat_trace_info(
        "recv",
        task_id=task_id,
        requested_mode=requested_mode,
        thread_id=thread_id or None,
        stream=data.get("stream"),
        channel=data.get("channel") or "web",
        client_messages=client_messages,
    )

    run_status = "ok"
    run_error: str | None = None
    run_snap: dict[str, Any] | None = None
    pending_complete = False
    pending_stopped: str | None = None
    telemetry_token: Token | None = None
    cancel_task: asyncio.Task | None = None
    pump_holder: dict[str, asyncio.Task | None] = {"task": None}
    deps = None
    mixed_payload: dict[str, Any] | None = None
    image_urls: list[str] = []

    def _abort_if_stopped() -> None:
        if manager.is_stopped(task_id):
            raise _ChatUserCancelError()

    prepared = None
    try:
        try:
            if not await _send_chat_json(
                websocket,
                {"type": "chat_status", "phase": "prep", "detail": "正在准备上下文…"},
            ):
                raise _ChatUserCancelError()
            chat_req = ChatTurnRequest(
                    client_messages=list(client_messages),
                    thread_id=thread_id,
                    mode=requested_mode,
                    temperature=float(data.get("temperature", 0.7)),
                    max_tokens=int(data.get("max_tokens", 2048)),
                    provider=data.get("provider"),
                    model=data.get("model"),
                    skip_vision_precaption=data.get("vision_precaption") is False,
                    tool_call_mode=data.get("tool_call_mode"),
                    channel=str(data.get("channel") or "web"),
                    turn_meta_extra={
                        "task_id": task_id,
                        "requested_mode": requested_mode,
                        "channel": "web",
                    },
                )
            prepared, mode = await prepare_turn(chat_req)
            chat_trace_info(
                "prepared",
                task_id=task_id,
                effective_mode=mode,
                requested_mode=prepared.turn_meta.get("requested_mode"),
                thread_id=prepared.thread_id,
                provider=prepared.routed.provider,
                model=prepared.routed.model,
                fast_path=prepared.turn_meta.get("fast_path"),
                plan=prepared.plan,
                messages=prepared.messages,
            )
        except Exception as e:
            chat_trace_warn("prepare_failed", task_id=task_id, error=str(e))
            await manager.fail(task_id, str(e))
            await _send_chat_json(
                websocket,
                {
                    "type": "chat_error",
                    "task_id": task_id,
                    "error": str(e) or "prepare failed",
                },
            )
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
            "[ws.chat] task=%s routed provider=%s model=%s format=%s via=%s",
            task_id,
            routed.provider,
            routed.model,
            routed.format,
            routed.via,
        )
        chat_trace_info(
            "started",
            task_id=task_id,
            effective_mode=mode,
            provider=routed.provider,
            model=routed.model,
            thread_id=thread_id,
        )
        if not await _send_chat_json(
            websocket,
            {
                "type": "chat_started",
                "task_id": task_id,
                "run_id": task_id,
                "thread_id": thread_id,
                "router": router_payload,
                "observability": {"ws_run_summary": ws_run_summary_enabled()},
            },
        ):
            raise _ChatUserCancelError()
        logger.debug("[ws.chat] task=%s sent chat_started", task_id)
        cancel_task = asyncio.create_task(
            _listen_cancel_ws(websocket, task_id, manager, pump_holder)
        )
        _abort_if_stopped()
        logger.debug("[ws.chat] task=%s prepare done (messages=%s)", task_id, len(messages))
        if not await _send_chat_json(
            websocket,
            {"type": "chat_status", "phase": "llm", "detail": "正在调用模型…"},
        ):
            raise _ChatUserCancelError()
        deps = bind_agent_deps(
            prepared,
            mode=mode,
            temperature=float(data.get("temperature", 0.7)),
            max_tokens=int(data.get("max_tokens", 2048)),
            tool_call_mode=data.get("tool_call_mode"),
            stop_event=manager.get_stop_event(task_id),
            channel=str(data.get("channel") or "web"),
        )
        _abort_if_stopped()
        logger.debug("[ws.chat] task=%s agent deps ready mode=%s", task_id, mode)

        full_response = ""
        use_stream = data.get("stream")
        if use_stream is None:
            use_stream = bool(config.get("agent.stream_output", True))
        chat_trace_info(
            "llm_invoke",
            task_id=task_id,
            effective_mode=mode,
            tools=len(deps.tool_registry.list_tools()) if deps.tool_registry else 0,
            tool_call_mode=deps.tool_call_mode,
            stream=use_stream,
        )
        if use_stream:
            logger.debug("[ws.chat] task=%s run_stream begin", task_id)
            q: asyncio.Queue = asyncio.Queue()
            pump_task = asyncio.create_task(_pump_chat_stream_prepared(prepared, deps, mode, q))
            pump_holder["task"] = pump_task
            end_reason = "finished"
            logged_first_token = False
            think_chars = 0
            out_chars = 0
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
                    if et == "error":
                        err = str(event.get("content") or "Agent error")
                        chat_trace_error("stream_error", task_id=task_id, error=err)
                        run_status = "error"
                        run_error = err
                        end_reason = "error"
                        if not await _send_chat_json(
                            websocket,
                            {"type": "chat_error", "task_id": task_id, "error": err},
                        ):
                            end_reason = "client_gone"
                        break
                    if et == "chunk":
                        content = event.get("content", "")
                        if content:
                            if not logged_first_token:
                                logged_first_token = True
                                chat_trace_info(
                                    "first_token",
                                    task_id=task_id,
                                    kind="content",
                                    preview=str(content)[:80],
                                )
                            out_chars += len(content)
                            full_response += content
                            if not await _send_chat_json(
                                websocket, {"type": "chat_chunk", "content": content}
                            ):
                                end_reason = "client_gone"
                                break
                    elif et == "think_chunk":
                        content = event.get("content", "")
                        if content:
                            if not logged_first_token:
                                logged_first_token = True
                                chat_trace_info(
                                    "first_token",
                                    task_id=task_id,
                                    kind="think",
                                    preview=str(content)[:80],
                                )
                            think_chars += len(content)
                            if not await _send_chat_json(
                                websocket, {"type": "chat_think_chunk", "content": content}
                            ):
                                end_reason = "client_gone"
                                break
                    elif et == "status":
                        if not await _send_chat_json(
                            websocket,
                            {
                                "type": "chat_status",
                                "phase": event.get("phase"),
                                "detail": event.get("detail"),
                                "iteration": event.get("iteration"),
                                "tool_names": event.get("tool_names"),
                            },
                        ):
                            end_reason = "client_gone"
                            break
                    elif et == "tool_start":
                        tool_name = event.get("tool") or "?"
                        chat_trace_info(
                            "tool_start",
                            task_id=task_id,
                            tool=tool_name,
                            iteration=event.get("iteration"),
                        )
                        if not await _send_chat_json(
                            websocket,
                            {
                                "type": "chat_tool_start",
                                "tool": event.get("tool"),
                                "call_id": event.get("call_id"),
                                "args_preview": event.get("args_preview"),
                                "iteration": event.get("iteration"),
                            },
                        ):
                            end_reason = "client_gone"
                            break
                    elif et == "tool_done":
                        if not await _send_chat_json(
                            websocket,
                            {
                                "type": "chat_tool_done",
                                "tool": event.get("tool"),
                                "call_id": event.get("call_id"),
                                "success": event.get("success"),
                                "result_preview": event.get("result_preview"),
                                "iteration": event.get("iteration"),
                            },
                        ):
                            end_reason = "client_gone"
                            break
                    elif et == "node":
                        if not await _send_chat_json(
                            websocket,
                            {
                                "type": "chat_node",
                                "node": event.get("node"),
                                "data": event.get("data"),
                            },
                        ):
                            end_reason = "client_gone"
                            break
                    elif et == "final":
                        c = event.get("content") or ""
                        if c:
                            full_response = c
                            if not event.get("chunked"):
                                if not await _send_chat_json(
                                    websocket, {"type": "chat_chunk", "content": c}
                                ):
                                    end_reason = "client_gone"
                                    break
            finally:
                if not pump_task.done():
                    pump_task.cancel()
                await asyncio.gather(pump_task, return_exceptions=True)

            if pump_task.done() and not pump_task.cancelled():
                pump_exc = pump_task.exception()
                if pump_exc is not None:
                    raise pump_exc

            if end_reason in ("cancelled", "client_gone") or manager.is_stopped(task_id):
                run_status = "cancelled"
                await manager.update(task_id, status="stopped", result=full_response)
                await broadcaster.task_stopped(task_id, full_response)
                pending_stopped = full_response
            elif end_reason == "error":
                await manager.fail(task_id, run_error or "Agent error")
                await broadcaster.task_failed(task_id, run_error or "Agent error")
            elif not logged_first_token and run_status == "ok":
                chat_trace_warn(
                    "no_stream_tokens",
                    task_id=task_id,
                    effective_mode=mode,
                    hint="LLM returned no content/thinking chunks; check model API key, model id, or provider",
                )
            else:
                chat_trace_info(
                    "stream_done",
                    task_id=task_id,
                    out_chars=out_chars,
                    think_chars=think_chars,
                    end_reason=end_reason,
                )
        else:
            run_task = asyncio.create_task(run_turn_blocking(prepared, deps, mode=mode))
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

        if pending_stopped is None and run_status == "ok" and deps is not None:
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
        chat_trace_error("failed", task_id=task_id, error=str(e))
        logger.exception("[ws.chat] task=%s failed: %s", task_id, e)
        await manager.fail(task_id, str(e))
        await broadcaster.task_failed(task_id, str(e))
    finally:
        if cancel_task is not None:
            if not cancel_task.done():
                cancel_task.cancel()
            await asyncio.gather(cancel_task, return_exceptions=True)

    if pending_stopped is not None:
        await _send_chat_json(
            websocket,
            attach_run_fields(
                {
                    "type": "chat_stopped",
                    "task_id": task_id,
                    "partial": pending_stopped,
                },
                None,
            ),
        )

    if telemetry_token is not None:
        run_snap = await finish_observed_run(
            telemetry_token, task_id, status=run_status, error=run_error
        )

    if pending_complete and deps is not None:
        chat_trace_info(
            "complete",
            task_id=task_id,
            thread_id=thread_id,
            out_chars=len(full_response or ""),
        )
        if run_snap:
            logger.info("[ws.chat] task=%s run_summary=%s", task_id, run_snap)
        await _send_chat_json(
            websocket,
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
            ),
        )
    elif run_error is not None:
        await _send_chat_json(
            websocket,
            attach_run_fields(
                {"type": "chat_error", "task_id": task_id, "error": run_error},
                run_snap,
            ),
        )
