from typing import Any

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState

from ly_next.agent.deps import create_agent_deps
from ly_next.agent.factory import AgentFactory
from ly_next.agent.model_router import resolve_model_routing
from ly_next.agent.prompt_augment import augment_messages_async
from ly_next.agent.vision_precaption import apply_vision_precaption_if_needed
from ly_next.api.bridge import (
    SUPPORTED_CHANNELS,
    emit_channel_event,
    is_supported_channel,
    update_device_session,
)
from ly_next.api.websocket import get_task_broadcaster, get_ws_manager
from ly_next.core.auth_http import extract_api_key_from_websocket
from ly_next.core.config import config
from ly_next.core.logger import get_logger
from ly_next.core.stdin_journal import publish_stdin_line
from ly_next.core.task_manager import get_task_manager
from ly_next.tools import get_tool_registry

router = APIRouter(tags=["websocket"])
public_router = APIRouter(tags=["websocket"])

ws_manager = get_ws_manager()
logger = get_logger(__name__)


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
    except Exception:
        pass
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
                line = str(raw).replace("\r\n", "\n").replace("\r", "\n")
                src = str(data.get("source") or "ws").strip() or "ws"
                await publish_stdin_line(line, src, replay=False)
                await websocket.send_json({"type": "stdin_ack", "channel": channel, "ok": True})
                continue

            if channel == "device":
                if msg_type == "register_device":
                    device_id = str(data.get("device_id") or "").strip()
                    if not device_id:
                        await websocket.send_json(
                            {"type": "error", "message": "device_id required"}
                        )
                        continue
                    session = update_device_session(
                        device_id,
                        channel=channel,
                        status="online",
                        meta=data.get("meta") or {},
                    )
                    await websocket.send_json({"type": "device_registered", "session": session})
                    await emit_channel_event("device", "device_online", {"session": session})
                    continue
                if msg_type == "device_heartbeat":
                    device_id = str(data.get("device_id") or "").strip()
                    if device_id:
                        session = update_device_session(device_id, status="online")
                        await websocket.send_json(
                            {"type": "device_heartbeat_ack", "session": session}
                        )
                    continue
                if msg_type == "device_status":
                    device_id = str(data.get("device_id") or "").strip()
                    if device_id:
                        session = update_device_session(
                            device_id,
                            status=data.get("status", "online"),
                            state=data.get("state") or {},
                        )
                        await emit_channel_event("device", "device_status", {"session": session})
                    continue

            if msg_type == "publish":
                await emit_channel_event(
                    channel,
                    data.get("event", f"{channel}_event"),
                    {
                        "source": data.get("source", "ws"),
                        "payload": data.get("payload") or {},
                        "device_id": data.get("device_id"),
                    },
                )
                await websocket.send_json({"type": "published", "channel": channel})
                continue

            await websocket.send_json({"type": "error", "message": f"Unknown: {msg_type}"})
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        await ws_manager.disconnect(websocket)


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
    messages = data.get("messages", [])
    if not messages:
        await websocket.send_json({"type": "error", "message": "No messages"})
        return

    manager = get_task_manager()
    task_id = await manager.create_task(name="WebSocket Chat")
    await manager.update(task_id, status="running")

    broadcaster = get_task_broadcaster()
    await broadcaster.task_started(task_id, "WebSocket Chat")

    try:
        logger.debug(
            "[ws.chat] task=%s mode=%s stream=%s provider=%s model=%s",
            task_id,
            data.get("mode", "react"),
            data.get("stream"),
            data.get("provider"),
            data.get("model"),
        )
        messages = await apply_vision_precaption_if_needed(list(messages))
        routed = await resolve_model_routing(
            messages,
            request_provider=data.get("provider"),
            request_model=data.get("model"),
            router_hint=data.get("router_hint"),
            enabled_override=data.get("use_model_router"),
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
                "router": {
                    "task_kind": routed.task_kind.value,
                    "via": routed.via,
                    "provider": routed.provider,
                    "model": routed.model,
                },
            }
        )
        logger.info("[ws.chat] task=%s sent chat_started", task_id)
        messages = await augment_messages_async(messages)
        logger.info("[ws.chat] task=%s augment_messages done (messages=%s)", task_id, len(messages))
        deps = create_agent_deps(provider=routed.provider, model=routed.model)
        deps.temperature = data.get("temperature", 0.7)
        deps.max_tokens = data.get("max_tokens", 2048)
        deps.tool_registry = get_tool_registry()
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
        logger.info("[ws.chat] task=%s agent created mode=%s", task_id, data.get("mode", "react"))

        full_response = ""
        use_stream = data.get("stream")
        if use_stream is None:
            use_stream = bool(config.get("agent.stream_output", True))
        if use_stream:
            logger.info("[ws.chat] task=%s run_stream begin", task_id)
            async for event in agent.run_stream(messages):
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
                    logger.debug("[ws.chat] task=%s final_chars=%s", task_id, len(c))
        else:
            full_response = await agent.run(messages)

        await manager.complete(task_id, result=full_response)
        await broadcaster.task_completed(task_id, full_response)
        await websocket.send_json(
            {"type": "chat_complete", "task_id": task_id, "response": full_response}
        )
    except Exception as e:
        logger.exception("[ws.chat] task=%s failed: %s", task_id, e)
        await manager.fail(task_id, str(e))
        await broadcaster.task_failed(task_id, str(e))
        try:
            await websocket.send_json({"type": "chat_error", "task_id": task_id, "error": str(e)})
        except Exception as send_err:
            logger.warning(
                "[ws.chat] task=%s could not send chat_error to client: %s", task_id, send_err
            )
