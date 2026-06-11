from __future__ import annotations

from ly_next.rag.rag_format import format_knowledge_search_text


def test_format_knowledge_search_text_with_hits():
    text = format_knowledge_search_text(
        query="RAG 配置",
        hits=[
            {
                "rank": 1,
                "score": 0.88,
                "source": "docs/rag.md",
                "text": "agent.rag.enabled 控制知识库检索。",
            }
        ],
        documents_path="data/ly_next/knowledge",
        chunks_loaded=12,
    )
    assert "知识库检索" in text
    assert "RAG 配置" in text
    assert "docs/rag.md" in text
    assert "agent.rag.enabled" in text


def test_format_knowledge_search_text_empty_hits():
    text = format_knowledge_search_text(query="missing topic", hits=[])
    assert "未命中" in text
