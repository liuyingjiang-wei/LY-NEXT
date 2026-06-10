from __future__ import annotations

import pytest

from ly_next.tools.knowledge_tools import knowledge_search


@pytest.mark.asyncio
async def test_knowledge_search_disabled(monkeypatch):
    monkeypatch.setattr(
        "ly_next.tools.knowledge_tools.config.get",
        lambda key, default=None: False if key == "agent.rag.enabled" else default,
    )
    result = await knowledge_search(query="test")
    assert result.success is False
    assert "disabled" in (result.error or "").lower()


@pytest.mark.asyncio
async def test_knowledge_search_empty_query(monkeypatch):
    monkeypatch.setattr(
        "ly_next.tools.knowledge_tools.config.get",
        lambda key, default=None: True if key == "agent.rag.enabled" else default,
    )
    result = await knowledge_search(query="  ")
    assert result.success is False
