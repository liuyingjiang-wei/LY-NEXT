from __future__ import annotations

from typing import Any
from uuid import UUID

from ly_next.core.config import config
from ly_next.core.database import db
from ly_next.core.logger import get_logger
from ly_next.core.thread_persistence import (
    _thread_title_from_messages,
    persistence_active,
)

logger = get_logger(__name__)

_BINDER_KIND = "onebot_binder"
_CONV_KIND = "onebot_conversation"


def onebot_history_limit() -> int:
    raw = config.get("bridge.onebot11.memory.max_messages", 40)
    try:
        return max(4, int(raw))
    except (TypeError, ValueError):
        return 40


def onebot_include_global_memory() -> bool:
    return bool(config.get("bridge.onebot11.memory.include_global_memory", False))


async def resolve_active_onebot_thread(
    scope_key: str,
    *,
    seed_messages: list[dict[str, Any]] | None = None,
) -> str:
    """Map QQ 私聊/群 scope 到当前活跃对话会话 UUID（无库时返回 scope_key）。"""
    seeds = seed_messages or []
    if not persistence_active():
        return scope_key

    binder = await db.find_session_by_external_key(scope_key)
    if binder is not None and (binder.metadata_ or {}).get("kind") == _BINDER_KIND:
        active = str((binder.metadata_ or {}).get("active_thread_id") or "").strip()
        if active:
            uid = UUID(active) if _valid_uuid(active) else None
            if uid is not None and await db.get_session(uid) is not None:
                return active
        child_id = await _create_conversation(scope_key, seeds)
        await db.patch_session_metadata(
            binder.id,
            {"active_thread_id": child_id, "kind": _BINDER_KIND},
        )
        return child_id

    legacy = binder
    if legacy is not None:
        child_id = await _migrate_legacy_session(legacy, scope_key)
        await _ensure_binder(scope_key, child_id)
        return child_id

    child_id = await _create_conversation(scope_key, seeds)
    await _ensure_binder(scope_key, child_id)
    return child_id


async def start_new_onebot_conversation(
    scope_key: str,
    *,
    seed_messages: list[dict[str, Any]] | None = None,
) -> str:
    if not persistence_active():
        return scope_key
    child_id = await _create_conversation(scope_key, seed_messages or [])
    await _ensure_binder(scope_key, child_id)
    logger.info("[onebot11] new conversation scope=%s thread=%s", scope_key, child_id)
    return child_id


def _valid_uuid(value: str) -> bool:
    try:
        UUID(str(value))
        return True
    except (ValueError, TypeError):
        return False


async def _create_conversation(
    scope_key: str, seed_messages: list[dict[str, Any]]
) -> str:
    title = _thread_title_from_messages(seed_messages) or "QQ 对话"
    row = await db.create_session(
        name=title,
        metadata={
            "kind": _CONV_KIND,
            "onebot_scope": scope_key,
            "channel": "onebot",
        },
    )
    return str(row.id)


async def _ensure_binder(scope_key: str, active_thread_id: str) -> None:
    binder = await db.find_session_by_external_key(scope_key)
    meta = {
        "external_key": scope_key,
        "kind": _BINDER_KIND,
        "active_thread_id": active_thread_id,
        "channel": "onebot",
    }
    if binder is None:
        await db.create_session(name="QQ 会话", metadata=meta)
        return
    if (binder.metadata_ or {}).get("kind") == _BINDER_KIND:
        await db.patch_session_metadata(
            binder.id,
            {"active_thread_id": active_thread_id},
        )
        return
    await db.patch_session_metadata(binder.id, meta, replace=True)


async def _migrate_legacy_session(legacy: Any, scope_key: str) -> str:
    """将旧版 external_key=scope 的单会话升级为对话子会话。"""
    meta = dict(legacy.metadata_ or {})
    meta.pop("external_key", None)
    meta["kind"] = _CONV_KIND
    meta["onebot_scope"] = scope_key
    meta["channel"] = "onebot"
    await db.patch_session_metadata(legacy.id, meta, replace=True)
    logger.info("[onebot11] migrated legacy thread %s scope=%s", legacy.id, scope_key)
    return str(legacy.id)
