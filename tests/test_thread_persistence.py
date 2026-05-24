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
