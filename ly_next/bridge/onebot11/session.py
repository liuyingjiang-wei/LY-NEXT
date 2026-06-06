from __future__ import annotations

import asyncio
import json
import uuid
from typing import Any

from fastapi import WebSocket
from starlette.websockets import WebSocketState

from ly_next.core.logger import get_logger
from ly_next.messaging.models import MixedMessage
from ly_next.messaging.onebot_media import image_segment

logger = get_logger(__name__)

_DEFAULT_API_TIMEOUT = 60.0


class OneBotApiError(Exception):
    def __init__(self, retcode: int, message: str, raw: dict[str, Any] | None = None):
        super().__init__(message)
        self.retcode = retcode
        self.raw = raw or {}


class OneBotSession:
    def __init__(self, websocket: WebSocket) -> None:
        self.websocket = websocket
        self.self_id: int | None = None
        self.nickname: str = ""
        self._echo: dict[str, asyncio.Future[dict[str, Any]]] = {}
        self._recv_task: asyncio.Task | None = None
        self._closed = False

    async def start(self) -> None:
        self._recv_task = asyncio.create_task(self._recv_loop())

    async def close(self) -> None:
        self._closed = True
        if self._recv_task is not None and not self._recv_task.done():
            self._recv_task.cancel()
            await asyncio.gather(self._recv_task, return_exceptions=True)
        for fut in list(self._echo.values()):
            if not fut.done():
                fut.set_exception(ConnectionError("OneBot session closed"))
        self._echo.clear()
        if self.websocket.client_state == WebSocketState.CONNECTED:
            await self.websocket.close()

    async def send_api_raw(
        self,
        action: str,
        params: dict[str, Any] | None = None,
        *,
        timeout: float = _DEFAULT_API_TIMEOUT,
    ) -> dict[str, Any]:
        echo = str(uuid.uuid4())
        loop = asyncio.get_running_loop()
        fut: asyncio.Future[dict[str, Any]] = loop.create_future()
        self._echo[echo] = fut
        payload = {"action": action, "params": params or {}, "echo": echo}
        try:
            await self.websocket.send_text(json.dumps(payload, ensure_ascii=False))
            return await asyncio.wait_for(fut, timeout=timeout)
        except asyncio.TimeoutError as e:
            self._echo.pop(echo, None)
            raise TimeoutError(f"OneBot API timeout: {action}") from e
        finally:
            self._echo.pop(echo, None)

    async def send_api(
        self,
        action: str,
        params: dict[str, Any] | None = None,
        *,
        timeout: float = _DEFAULT_API_TIMEOUT,
    ) -> dict[str, Any]:
        raw = await self.send_api_raw(action, params, timeout=timeout)
        status = str(raw.get("status") or "")
        retcode = int(raw.get("retcode", 0))
        if status != "ok" and retcode not in (0, 1):
            wording = str(raw.get("wording") or raw.get("message") or "API failed")
            raise OneBotApiError(retcode, wording, raw)
        data = raw.get("data")
        if isinstance(data, dict):
            return data
        if data is None:
            return {}
        return {"result": data}

    def _send_msg_action(
        self,
        *,
        message_type: str,
        user_id: int | None,
        group_id: int | None,
    ) -> tuple[str, dict[str, Any]]:
        params: dict[str, Any] = {}
        if message_type == "group" and group_id is not None:
            params["group_id"] = group_id
            return "send_group_msg", params
        if message_type == "private" and user_id is not None:
            params["user_id"] = user_id
            return "send_private_msg", params
        params["message_type"] = message_type
        if user_id is not None:
            params["user_id"] = user_id
        if group_id is not None:
            params["group_id"] = group_id
        return "send_msg", params

    @staticmethod
    def _mixed_to_onebot_segments(mixed: MixedMessage) -> list[dict[str, Any]]:
        segments: list[dict[str, Any]] = []
        for part in mixed.parts:
            if part.type == "text" and part.content:
                segments.append({"type": "text", "data": {"text": part.content}})
            elif part.type == "image" and part.content.strip():
                segments.append(image_segment(part.content.strip()))
        if not segments:
            segments.append({"type": "text", "data": {"text": mixed.plain_text or " "}})
        return segments

    async def send_text_message(
        self,
        *,
        message_type: str,
        user_id: int | None = None,
        group_id: int | None = None,
        text: str,
    ) -> int | None:
        action, params = self._send_msg_action(
            message_type=message_type, user_id=user_id, group_id=group_id
        )
        params["message"] = text
        params["auto_escape"] = True
        data = await self.send_api(action, params)
        mid = data.get("message_id")
        return int(mid) if mid is not None else None

    async def delete_message(self, message_id: int) -> None:
        await self.send_api("delete_msg", {"message_id": message_id})

    async def send_mixed_message(
        self,
        *,
        message_type: str,
        user_id: int | None = None,
        group_id: int | None = None,
        mixed: MixedMessage,
    ) -> int | None:
        from ly_next.messaging.dispatcher import image_loading_text

        loading_id: int | None = None
        if mixed.has_images:
            try:
                loading_id = await self.send_text_message(
                    message_type=message_type,
                    user_id=user_id,
                    group_id=group_id,
                    text=image_loading_text(),
                )
            except Exception as e:
                logger.debug("[onebot11] loading hint failed: %s", e)

        action, params = self._send_msg_action(
            message_type=message_type, user_id=user_id, group_id=group_id
        )
        params["message"] = self._mixed_to_onebot_segments(mixed)
        data = await self.send_api(action, params)
        mid = data.get("message_id")
        out = int(mid) if mid is not None else None

        if loading_id is not None:
            try:
                await self.delete_message(loading_id)
            except Exception as e:
                logger.debug("[onebot11] retract loading msg failed: %s", e)
        return out

    def dispatch_json(self, data: dict[str, Any]) -> None:
        echo = data.get("echo")
        if echo is not None:
            key = str(echo)
            fut = self._echo.get(key)
            if fut is not None and not fut.done():
                fut.set_result(data)
            return
        from ly_next.bridge.onebot11.handler import handle_onebot_event

        asyncio.create_task(handle_onebot_event(self, data))

    async def _recv_loop(self) -> None:
        try:
            while not self._closed:
                msg = await self.websocket.receive()
                if msg.get("type") == "websocket.disconnect":
                    break
                text = msg.get("text")
                if text is None and msg.get("bytes") is not None:
                    text = msg["bytes"].decode("utf-8", errors="replace")
                if not text:
                    continue
                try:
                    data = json.loads(text)
                except json.JSONDecodeError:
                    logger.warning("[onebot11] invalid JSON frame")
                    continue
                if isinstance(data, dict):
                    self.dispatch_json(data)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            if not self._closed:
                logger.debug("[onebot11] recv loop ended: %s", e, exc_info=True)
        finally:
            from ly_next.bridge.onebot11.manager import unregister_session

            await unregister_session(self)

    async def on_lifecycle_connect(self, data: dict[str, Any]) -> None:
        try:
            info = await self.send_api("get_login_info")
        except Exception as e:
            logger.warning("[onebot11] get_login_info failed: %s", e)
            info = {}
        self.self_id = int(data.get("self_id") or info.get("user_id") or 0) or None
        self.nickname = str(info.get("nickname") or "")
        if self.self_id:
            from ly_next.bridge.onebot11.manager import register_session

            register_session(self.self_id, self)
        logger.info(
            "[onebot11] connected self_id=%s nickname=%s",
            self.self_id,
            self.nickname or "-",
        )
        from ly_next.core.thread_persistence import (
            db_available,
            persistence_active,
            persistence_enabled,
        )

        if not persistence_active():
            if persistence_enabled() and not db_available():
                logger.warning("[onebot11] PostgreSQL 未连接，QQ 会话不会跨轮次保存（仅单轮回复）")
            elif not persistence_enabled():
                logger.info("[onebot11] agent.persistence.enabled=false，会话不写入数据库")
