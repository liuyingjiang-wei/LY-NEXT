from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from ly_next.core.config import config
from ly_next.core.database import db


def persistence_enabled() -> bool:
    return bool(config.get("agent.persistence.enabled", True))


def max_messages_per_thread() -> int:
    return int(config.get("agent.persistence.max_messages_per_thread", 200))


def db_available() -> bool:
    return db._engine is not None


def persistence_active() -> bool:
    return persistence_enabled() and db_available()


def _content_to_storage(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    return json.dumps(content, ensure_ascii=False)


def _content_from_storage(raw: str) -> Any:
    if not raw:
        return ""
    stripped = raw.lstrip()
    if stripped.startswith(("{", "[")):
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            pass
    return raw


def message_row_to_chat(row: Any) -> dict[str, Any]:
    return {"role": row.role, "content": _content_from_storage(row.content)}


def message_row_to_dict(row: Any) -> dict[str, Any]:
    meta = row.metadata_ if isinstance(getattr(row, "metadata_", None), dict) else {}
    return {**message_row_to_chat(row), "metadata": meta}


def _parse_uuid(value: str | UUID | None) -> UUID | None:
    if value is None:
        return None
    if isinstance(value, UUID):
        return value
    try:
        return UUID(str(value).strip())
    except (ValueError, TypeError):
        return None


def _thread_title_from_messages(messages: list[dict[str, Any]]) -> str:
    for msg in reversed(messages):
        if str(msg.get("role", "")).lower() != "user":
            continue
        content = msg.get("content")
        if isinstance(content, str) and content.strip():
            text = content.strip().replace("\n", " ")
            return (text[:80] + "…") if len(text) > 80 else text
        if content is not None:
            return "Conversation"
    return "New conversation"


def _session_to_api(row: Any) -> dict[str, Any]:
    meta = row.metadata_ if isinstance(getattr(row, "metadata_", None), dict) else {}
    sid = str(row.id)
    return {
        "thread_id": sid,
        "id": sid,
        "name": row.name,
        "status": row.status,
        "metadata": meta,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


async def create_thread(name: str | None = None, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
    if not persistence_active():
        raise RuntimeError("Thread persistence requires a connected database")
    session = await db.create_session(name=name or "New conversation", metadata=metadata or {})
    return _session_to_api(session)


async def get_thread(thread_id: str) -> dict[str, Any] | None:
    uid = _parse_uuid(thread_id)
    if uid is None:
        return None
    row = await db.get_session(uid)
    if row is None:
        return None
    return _session_to_api(row)


async def list_threads(limit: int = 100, status: str | None = "active") -> list[dict[str, Any]]:
    if not persistence_active():
        return []
    rows = await db.list_sessions(limit=limit, status=status)
    return [_session_to_api(r) for r in rows]


async def delete_thread(thread_id: str) -> bool:
    uid = _parse_uuid(thread_id)
    if uid is None:
        return False
    return await db.delete_session(uid)


async def list_thread_messages(
    thread_id: str,
    *,
    limit: int | None = None,
    include_metadata: bool = False,
) -> list[dict[str, Any]]:
    uid = _parse_uuid(thread_id)
    if uid is None:
        return []
    cap = limit if limit is not None else max_messages_per_thread()
    rows = await db.get_messages_chronological(uid, limit=cap)
    if include_metadata:
        return [message_row_to_dict(r) for r in rows]
    return [message_row_to_chat(r) for r in rows]


def _same_message(a: dict[str, Any], b: dict[str, Any]) -> bool:
    return str(a.get("role")) == str(b.get("role")) and _content_to_storage(
        a.get("content")
    ) == _content_to_storage(b.get("content"))


def merge_thread_messages(
    stored: list[dict[str, Any]], incoming: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    if not incoming:
        return list(stored)
    if not stored:
        return list(incoming)
    if len(incoming) == 1 and str(incoming[0].get("role", "")).lower() == "user":
        if stored and _same_message(stored[-1], incoming[0]):
            return list(stored)
        return stored + incoming

    n = min(len(stored), len(incoming))
    if (
        n > 0
        and len(incoming) >= len(stored)
        and all(_same_message(stored[i], incoming[i]) for i in range(n))
    ):
        return list(incoming)

    for msg in reversed(incoming):
        if str(msg.get("role", "")).lower() == "user":
            return stored + [msg]
    return stored + incoming


def extract_new_user_messages(
    stored: list[dict[str, Any]], incoming: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    merged = merge_thread_messages(stored, incoming)
    if len(merged) <= len(stored):
        return []
    return [
        m
        for m in merged[len(stored) :]
        if str(m.get("role", "")).lower() == "user"
    ]


async def resolve_thread_id(
    thread_id: str | None, *, seed_messages: list[dict[str, Any]]
) -> str:
    if thread_id:
        uid = _parse_uuid(thread_id)
        if uid is None:
            raise ValueError(f"Invalid thread_id: {thread_id}")
        if await db.get_session(uid) is None:
            raise ValueError(f"Thread not found: {thread_id}")
        return str(uid)
    row = await create_thread(name=_thread_title_from_messages(seed_messages))
    return row["thread_id"]


async def prepare_messages_for_agent(
    thread_id: str | None, client_messages: list[dict[str, Any]]
) -> tuple[str | None, list[dict[str, Any]], list[dict[str, Any]]]:
    if not persistence_active():
        return thread_id, list(client_messages), []

    tid = await resolve_thread_id(thread_id, seed_messages=client_messages)
    stored = await list_thread_messages(tid)
    merged = merge_thread_messages(stored, client_messages)
    to_persist = extract_new_user_messages(stored, client_messages)
    return tid, merged, to_persist


async def persist_user_messages(
    thread_id: str,
    messages: list[dict[str, Any]],
    *,
    metadata: dict[str, Any] | None = None,
) -> None:
    if not messages or not persistence_active():
        return
    uid = _parse_uuid(thread_id)
    if uid is None:
        return
    meta = metadata or {}
    for msg in messages:
        if str(msg.get("role", "")).lower() != "user":
            continue
        row_meta = dict(meta)
        if isinstance(msg.get("metadata"), dict):
            row_meta.update(msg["metadata"])
        await db.create_message(
            uid,
            role="user",
            content=_content_to_storage(msg.get("content")),
            metadata=row_meta,
        )


async def persist_assistant_reply(
    thread_id: str,
    content: str,
    *,
    metadata: dict[str, Any] | None = None,
) -> None:
    if not content or not persistence_active():
        return
    uid = _parse_uuid(thread_id)
    if uid is None:
        return
    await db.create_message(
        uid,
        role="assistant",
        content=content,
        metadata=metadata or {},
    )


async def persist_chat_turn(
    thread_id: str | None,
    user_messages: list[dict[str, Any]],
    assistant_text: str | None,
    *,
    metadata: dict[str, Any] | None = None,
) -> None:
    if not thread_id:
        return
    meta = metadata or {}
    if user_messages:
        await persist_user_messages(thread_id, user_messages, metadata=meta)
    if assistant_text:
        await persist_assistant_reply(thread_id, assistant_text, metadata=meta)
