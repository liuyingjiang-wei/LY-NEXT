from __future__ import annotations

import pytest

from ly_next.core.thread_persistence import (
    extract_new_user_messages,
    merge_thread_messages,
    message_row_to_dict,
)


class _FakeRow:
    def __init__(self, role: str, content: str, metadata: dict | None = None) -> None:
        self.role = role
        self.content = content
        self.metadata_ = metadata or {}


def test_merge_empty_stored_uses_incoming():
    incoming = [{"role": "user", "content": "hi"}]
    assert merge_thread_messages([], incoming) == incoming


def test_merge_last_user_only_appends():
    stored = [
        {"role": "user", "content": "first"},
        {"role": "assistant", "content": "reply"},
    ]
    incoming = [{"role": "user", "content": "second"}]
    merged = merge_thread_messages(stored, incoming)
    assert len(merged) == 3
    assert merged[-1]["content"] == "second"


def test_merge_full_history_when_prefix_matches():
    stored = [
        {"role": "user", "content": "a"},
        {"role": "assistant", "content": "b"},
    ]
    incoming = stored + [{"role": "user", "content": "c"}]
    assert merge_thread_messages(stored, incoming) == incoming


def test_extract_new_user_messages_single_turn():
    stored = [{"role": "user", "content": "a"}, {"role": "assistant", "content": "b"}]
    incoming = [{"role": "user", "content": "c"}]
    new = extract_new_user_messages(stored, incoming)
    assert len(new) == 1
    assert new[0]["content"] == "c"


def test_merge_skips_duplicate_user_retry():
    stored = [{"role": "user", "content": "hello"}]
    incoming = [{"role": "user", "content": "hello"}]
    assert merge_thread_messages(stored, incoming) == stored
    assert extract_new_user_messages(stored, incoming) == []


def test_extract_ignores_assistant_in_suffix():
    stored = [{"role": "user", "content": "a"}]
    incoming = [
        {"role": "user", "content": "a"},
        {"role": "assistant", "content": "draft"},
        {"role": "user", "content": "b"},
    ]
    new = extract_new_user_messages(stored, incoming)
    assert len(new) == 1
    assert new[0]["content"] == "b"


def test_message_row_json_content():
    row = _FakeRow("user", '{"type":"text","text":"x"}')
    msg = message_row_to_dict(row)
    assert isinstance(msg["content"], dict)
    assert msg["content"]["text"] == "x"


def test_is_external_thread_key():
    from ly_next.core.thread_persistence import is_external_thread_key

    assert is_external_thread_key("onebot:private:123")
    assert is_external_thread_key("onebot:group:456")
    assert not is_external_thread_key("not-a-uuid")
    assert not is_external_thread_key("550e8400-e29b-41d4-a716-446655440000")


@pytest.mark.asyncio
async def test_resolve_external_onebot_thread(monkeypatch):
    from uuid import uuid4

    from ly_next.core import thread_persistence as tp

    session_id = uuid4()
    stored_key: list[str] = []

    class _Session:
        def __init__(self, sid):
            self.id = sid

    async def find_session_by_external_key(key: str):
        return _Session(session_id) if key in stored_key else None

    async def create_session(name: str, metadata: dict | None = None):
        meta = metadata or {}
        stored_key.append(str(meta.get("external_key")))
        return _Session(session_id)

    monkeypatch.setattr(tp, "persistence_active", lambda: True)
    monkeypatch.setattr(tp.db, "find_session_by_external_key", find_session_by_external_key)
    monkeypatch.setattr(tp.db, "create_session", create_session)

    tid = await tp.resolve_thread_id(
        "onebot:private:2131500477",
        seed_messages=[{"role": "user", "content": "hi"}],
    )
    assert tid == str(session_id)
    assert stored_key == ["onebot:private:2131500477"]

    tid2 = await tp.resolve_thread_id(
        "onebot:private:2131500477",
        seed_messages=[{"role": "user", "content": "again"}],
    )
    assert tid2 == str(session_id)
    assert len(stored_key) == 1


@pytest.mark.asyncio
async def test_prepare_messages_without_db(monkeypatch):
    from ly_next.core import thread_persistence as tp

    monkeypatch.setattr(tp, "persistence_active", lambda: False)
    tid, merged, to_save = await tp.prepare_messages_for_agent(
        None, [{"role": "user", "content": "hello"}]
    )
    assert tid is None
    assert merged == [{"role": "user", "content": "hello"}]
    assert to_save == []
