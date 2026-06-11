from __future__ import annotations

from pathlib import Path

import pytest

from ly_next.rag import document_retriever as dr
from ly_next.rag.document_retriever import DocumentRetriever


def test_configure_reindexes_when_chunk_size_changes(monkeypatch, tmp_path: Path):
    knowledge = tmp_path / "knowledge"
    knowledge.mkdir()
    (knowledge / "a.md").write_text("same corpus", encoding="utf-8")
    chunk_sizes = [200, 400]

    def fake_get(key: str, default=None):
        if key == "agent.rag.documents_path":
            return str(knowledge)
        if key == "agent.rag.chunk_size":
            return chunk_sizes[0]
        if key == "agent.rag.chunk_overlap":
            return 0
        if key == "agent.rag.chunk_strategy":
            return "markdown"
        if key == "agent.rag.contextual_chunks":
            return False
        return default

    monkeypatch.setattr(dr.config, "get", fake_get)
    monkeypatch.setattr(dr, "get_project_root", lambda: tmp_path)
    monkeypatch.setattr(dr, "get_data_root", lambda: tmp_path)

    retriever = DocumentRetriever()
    retriever.configure()
    first_count = len(retriever._chunks)
    chunk_sizes[0] = 400
    retriever.configure()
    assert len(retriever._chunks) != first_count or retriever._vectors is None


def test_configure_skips_reload_when_corpus_unchanged(monkeypatch, tmp_path: Path):
    knowledge = tmp_path / "knowledge"
    knowledge.mkdir()
    (knowledge / "a.md").write_text("stable corpus content", encoding="utf-8")

    def fake_get(key: str, default=None):
        if key == "agent.rag.documents_path":
            return str(knowledge)
        return default

    monkeypatch.setattr(dr.config, "get", fake_get)
    monkeypatch.setattr(dr, "get_project_root", lambda: tmp_path)
    monkeypatch.setattr(dr, "get_data_root", lambda: tmp_path)

    retriever = DocumentRetriever()
    retriever.configure()
    first_sig = retriever._corpus_sig
    first_chunks = list(retriever._chunks)
    retriever._vectors = [[0.1, 0.2]]
    retriever.configure()
    assert retriever._corpus_sig == first_sig
    assert retriever._chunks == first_chunks
    assert retriever._vectors == [[0.1, 0.2]]


@pytest.mark.asyncio
async def test_pick_for_query_lexical_hybrid_without_embeddings(monkeypatch, tmp_path: Path):
    knowledge = tmp_path / "knowledge"
    knowledge.mkdir()
    (knowledge / "a.md").write_text(
        "PostgreSQL pgvector stores RAG embeddings for hybrid retrieval.",
        encoding="utf-8",
    )
    (knowledge / "b.md").write_text("Unrelated cooking recipes and pasta.", encoding="utf-8")

    def fake_get(key: str, default=None):
        mapping = {
            "agent.rag.enabled": True,
            "agent.rag.documents_path": str(knowledge),
            "agent.rag.top_k": 2,
            "agent.rag.chunk_size": 200,
            "agent.rag.chunk_overlap": 0,
            "agent.rag.chunk_strategy": "markdown",
            "agent.rag.min_similarity": 0.0,
            "agent.rag.use_embeddings": False,
            "agent.rag.hybrid_enabled": True,
            "agent.rag.rrf_k": 60,
            "agent.rag.mmr_enabled": False,
            "agent.rag.retrieve_multiplier": 3,
            "agent.rag.query_rewrite": {"enabled": False},
            "agent.rag.rerank": {"enabled": False},
        }
        return mapping.get(key, default)

    monkeypatch.setattr(dr.config, "get", fake_get)
    monkeypatch.setattr(dr, "get_project_root", lambda: tmp_path)
    monkeypatch.setattr(dr, "get_data_root", lambda: tmp_path)

    retriever = DocumentRetriever()
    retriever.configure()
    picked = await retriever._pick_for_query("pgvector RAG hybrid")
    assert picked
    assert "pgvector" in picked[0][1].lower()


@pytest.mark.asyncio
async def test_l1_hybrid_uses_full_bm25(monkeypatch):
    retriever = DocumentRetriever()
    retriever._chunks = ["alpha only", "beta pgvector exact"]
    retriever._embed_texts = list(retriever._chunks)
    retriever._sources = ["a.md", "b.md"]

    async def fake_dense(_query: str):
        return ([(0.2, "alpha only")], [0.1, 0.2, 0.3])

    monkeypatch.setattr(retriever, "_rank_embedding_with_query_vec", fake_dense)

    def fake_get(key: str, default=None):
        mapping = {
            "agent.rag.top_k": 1,
            "agent.rag.min_similarity": 0.0,
            "agent.rag.use_embeddings": True,
            "agent.rag.hybrid_enabled": True,
            "agent.rag.rrf_k": 60,
            "agent.rag.mmr_enabled": False,
            "agent.rag.retrieve_multiplier": 5,
            "agent.rag.query_rewrite": {"enabled": False},
            "agent.rag.rerank": {"enabled": False},
        }
        return mapping.get(key, default)

    monkeypatch.setattr(dr.config, "get", fake_get)
    ranked, _ = await retriever._l1_hybrid_recall(
        "pgvector",
        pool_n=5,
        use_emb=True,
        hybrid=True,
        rrf_k=60,
        expand=False,
    )
    chunks = [ch for _s, ch in ranked]
    assert "beta pgvector exact" in chunks


@pytest.mark.asyncio
async def test_rerank_integration_reorders(monkeypatch):
    retriever = DocumentRetriever()
    retriever._chunks = ["alpha", "beta pgvector"]
    retriever._sources = ["a.md", "b.md"]

    async def fake_rerank(query, ranked, *, top_k):
        assert query
        # Force beta first regardless of input scores
        by_text = {ch: sc for sc, ch in ranked}
        return [(0.99, "beta pgvector"), (by_text.get("alpha", 0.1), "alpha")][:top_k]

    monkeypatch.setattr(dr, "rerank_chunks", fake_rerank)

    def fake_get(key: str, default=None):
        mapping = {
            "agent.rag.top_k": 2,
            "agent.rag.min_similarity": 0.0,
            "agent.rag.use_embeddings": False,
            "agent.rag.hybrid_enabled": False,
            "agent.rag.mmr_enabled": False,
            "agent.rag.retrieve_multiplier": 5,
            "agent.rag.query_rewrite": {"enabled": False},
            "agent.rag.rerank": {"enabled": True, "top_n": 5},
        }
        return mapping.get(key, default)

    monkeypatch.setattr(dr.config, "get", fake_get)
    picked = await retriever._pick_for_query("pgvector")
    assert picked[0][1].startswith("beta")


def test_rag_injection_mode_tool(monkeypatch):
    from ly_next.agent import prompt_augment as pa

    def fake_get(key: str, default=None):
        if key == "agent.rag.enabled":
            return True
        if key == "agent.rag.mode":
            return "tool"
        return default

    monkeypatch.setattr(pa.config, "get", fake_get)
    assert pa._rag_injection_enabled(skip_rag=False) is False
    assert pa._rag_injection_enabled(skip_rag=True) is False


def test_rag_injection_mode_both(monkeypatch):
    from ly_next.agent import prompt_augment as pa

    def fake_get(key: str, default=None):
        if key == "agent.rag.enabled":
            return True
        if key == "agent.rag.mode":
            return "both"
        return default

    monkeypatch.setattr(pa.config, "get", fake_get)
    assert pa._rag_injection_enabled(skip_rag=False) is True
