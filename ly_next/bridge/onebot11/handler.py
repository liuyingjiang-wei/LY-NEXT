from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import Any

from ly_next.bridge.onebot11.agent_reply import build_thread_id, run_onebot_chat_turn
from ly_next.bridge.onebot11.commands import (
    OneBotCommand,
    help_message,
    new_chat_ack_message,
    parse_onebot_command,
)
from ly_next.bridge.onebot11.config import get_onebot11_settings
from ly_next.bridge.onebot11.cq import (
    apply_prefix_trigger,
    is_at_self,
    normalize_user_message_text,
)
from ly_next.bridge.onebot11.memory import (
    resolve_active_onebot_thread,
    start_new_onebot_conversation,
)
from ly_next.bridge.onebot11.session import OneBotSession
from ly_next.core.config import config
from ly_next.core.logger import get_logger
from ly_next.messaging.image_handler import build_mixed_message

logger = get_logger(__name__)

_reply_semaphore: asyncio.Semaphore | None = None
_scope_locks: defaultdict[str, asyncio.Lock] = defaultdict(asyncio.Lock)


def _reply_semaphore() -> asyncio.Semaphore:
    global _reply_semaphore
    if _reply_semaphore is None:
        raw = config.get("bridge.onebot11.max_concurrent_replies", 8)
        try:
            limit = max(1, int(raw))
        except (TypeError, ValueError):
            limit = 8
        _reply_semaphore = asyncio.Semaphore(limit)
    return _reply_semaphore


async def handle_onebot_event(session: OneBotSession, data: dict[str, Any]) -> None:
    post_type = data.get("post_type")
    if not post_type:
        return

    if post_type == "meta_event":
        await _handle_meta(session, data)
        return

    if post_type == "message":
        asyncio.create_task(_handle_message_concurrent(session, data))
        return

    return


async def _handle_message_concurrent(session: OneBotSession, data: dict[str, Any]) -> None:
    scope_key = _scope_key_from_event(session, data)
    if not scope_key:
        return
    async with _scope_locks[scope_key], _reply_semaphore():
        await _handle_message(session, data, scope_key=scope_key)


def _scope_key_from_event(session: OneBotSession, data: dict[str, Any]) -> str | None:
    message_type = str(data.get("message_type") or "")
    user_id = int(data.get("user_id") or 0)
    group_id = data.get("group_id")
    gid = int(group_id) if group_id is not None else None
    if message_type == "group" and gid is not None:
        return build_thread_id("group", user_id=user_id, group_id=gid)
    if message_type == "private":
        return build_thread_id("private", user_id=user_id)
    return None


async def _handle_meta(session: OneBotSession, data: dict[str, Any]) -> None:
    meta_type = data.get("meta_event_type")
    if meta_type == "lifecycle" and data.get("sub_type") == "connect":
        await session.on_lifecycle_connect(data)


async def _send_text(
    session: OneBotSession,
    *,
    message_type: str,
    user_id: int,
    group_id: int | None,
    text: str,
) -> None:
    if message_type == "group" and group_id is not None:
        await session.send_text_message(message_type="group", group_id=group_id, text=text)
    else:
        await session.send_text_message(message_type="private", user_id=user_id, text=text)


async def _handle_message(session: OneBotSession, data: dict[str, Any], *, scope_key: str) -> None:
    settings = get_onebot11_settings()
    if not settings.auto_reply.enabled:
        return

    message_type = str(data.get("message_type") or "")
    user_id = int(data.get("user_id") or 0)
    group_id = data.get("group_id")
    gid = int(group_id) if group_id is not None else None
    self_id = session.self_id or int(data.get("self_id") or 0)

    if settings.triggers.ignore_self and user_id == self_id:
        return

    raw_message = data.get("message")
    trig = settings.triggers

    if message_type == "private":
        if not trig.private:
            return
    elif message_type == "group":
        if not trig.group:
            return
        if trig.group_at_only and not is_at_self(raw_message, self_id):
            return
    else:
        return

    text = normalize_user_message_text(raw_message, self_id)
    if not text:
        return

    triggered = apply_prefix_trigger(text, trig.prefixes)
    if triggered is None:
        return

    cmd = parse_onebot_command(triggered)
    if cmd == OneBotCommand.NEW_CHAT:
        await start_new_onebot_conversation(scope_key, seed_messages=[])
        ack = new_chat_ack_message() or "已开始新对话。"
        try:
            await _send_text(
                session,
                message_type=message_type,
                user_id=user_id,
                group_id=gid,
                text=ack,
            )
        except Exception as e:
            logger.warning("[onebot11] new-chat ack failed: %s", e)
        return

    if cmd == OneBotCommand.HELP:
        try:
            await _send_text(
                session,
                message_type=message_type,
                user_id=user_id,
                group_id=gid,
                text=help_message(),
            )
        except Exception as e:
            logger.warning("[onebot11] help reply failed: %s", e)
        return

    thread_id = await resolve_active_onebot_thread(
        scope_key,
        seed_messages=[{"role": "user", "content": triggered}],
    )
    logger.info(
        "[onebot11] chat scope=%s thread=%s user=%s group=%s",
        scope_key,
        thread_id,
        user_id,
        gid,
    )

    try:
        chat_result = await run_onebot_chat_turn(
            user_text=triggered,
            thread_id=thread_id,
            scope_key=scope_key,
            auto=settings.auto_reply,
        )
    except Exception:
        logger.exception("[onebot11] chat turn failed scope=%s thread=%s", scope_key, thread_id)
        chat_result = None

    if chat_result is None:
        fallback = "处理消息时出错，请稍后再试。"
        try:
            await _send_text(
                session,
                message_type=message_type,
                user_id=user_id,
                group_id=gid,
                text=fallback,
            )
        except Exception as e:
            logger.warning("[onebot11] send error reply failed: %s", e)
        return

    mixed = chat_result.mixed
    if not mixed.parts and (chat_result.text or "").strip():
        mixed = build_mixed_message(chat_result.text)
    if not mixed.parts:
        return

    try:
        if message_type == "group" and gid is not None:
            await session.send_mixed_message(message_type="group", group_id=gid, mixed=mixed)
        else:
            await session.send_mixed_message(message_type="private", user_id=user_id, mixed=mixed)
    except Exception as e:
        logger.warning("[onebot11] send reply failed: %s", e)
