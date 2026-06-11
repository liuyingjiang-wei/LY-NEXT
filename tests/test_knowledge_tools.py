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
async def test_knowledge_search_returns_formatted_text(monkeypatch):
    async def fake_retrieve_results(query: str, *, top_k: int | None = None):
        return {
            "enabled": True,
            "documents_path": "data/knowledge",
            "chunks_loaded": 3,
            "hits": [
                {
                    "rank": 1,
                    "score": 0.9,
                    "source": "a.md",
                    "text": "hello rag",
                    "preview": "hello rag",
                }
            ],
        }

    monkeypatch.setattr(
        "ly_next.tools.knowledge_tools.config.get",
        lambda key, default=None: True if key == "agent.rag.enabled" else default,
    )

    class _FakeRetriever:
        retrieve_results = staticmethod(fake_retrieve_results)

    monkeypatch.setattr(
        "ly_next.tools.knowledge_tools.get_document_retriever",
        lambda: _FakeRetriever(),
    )
    result = await knowledge_search(query="rag")
    assert result.success is True
    payload = result.result or {}
    assert "知识库检索" in str(payload.get("text") or "")
    assert payload.get("hits")


@pytest.mark.asyncio
async def test_knowledge_search_empty_query(monkeypatch):
    monkeypatch.setattr(
        "ly_next.tools.knowledge_tools.config.get",
        lambda key, default=None: True if key == "agent.rag.enabled" else default,
    )
    result = await knowledge_search(query="  ")
    assert result.success is False
