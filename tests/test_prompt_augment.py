from __future__ import annotations

import pytest

from ly_next.agent.prompt_augment import augment_messages_async, merge_system_context


def test_merge_system_context_inserts_prefix():
    msgs = [{"role": "user", "content": "Q"}]
    out = merge_system_context(msgs, "CTX")
    assert out[0]["role"] == "system"
    assert "CTX" in out[0]["content"]
    assert out[-1]["role"] == "user"
    assert out[-1]["content"] == "Q"


def test_merge_system_context_merges_existing_system():
    msgs = [{"role": "system", "content": "base"}, {"role": "user", "content": "Q"}]
    out = merge_system_context(msgs, "extra")
    assert len(out) == 2
    assert out[0]["role"] == "system"
    assert "extra" in out[0]["content"]
    assert "base" in out[0]["content"]


@pytest.mark.asyncio
async def test_augment_empty_messages():
    assert await augment_messages_async([]) == []


@pytest.mark.asyncio
async def test_augment_no_user_query_returns_early(monkeypatch):
    from ly_next.core.config import config as global_config

    real_get = global_config.get

    def fake_get(key: str, default=None):
        if key == "agent.context.enabled":
            return False
        if key == "agent.rag.enabled":
            return False
        return real_get(key, default)

    monkeypatch.setattr("ly_next.agent.prompt_augment.config.get", fake_get)
    monkeypatch.setattr("ly_next.agent.prompt_augment.get_startup_memory_block", lambda: "")
    msgs = [{"role": "system", "content": "s"}]
    out = await augment_messages_async(list(msgs))
    assert out == msgs
