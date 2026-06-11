from __future__ import annotations

from ly_next.rag.query_rewrite import expand_queries, extract_identifiers, extract_keywords


def test_expand_queries_keeps_original_and_keywords():
    variants = expand_queries("如何配置 agent.rag.enabled 参数？")
    assert variants[0] == "如何配置 agent.rag.enabled 参数？"
    assert any("agent.rag.enabled" in v for v in variants)


def test_extract_identifiers_finds_dotted_names():
    ids = extract_identifiers("检查 openai_compat_llm.api_key 和 /images/generations")
    assert "openai_compat_llm.api_key" in ids or "openai_compat_llm" in " ".join(ids)


def test_extract_keywords_drops_stopwords():
    words = extract_keywords("请帮我解释 PostgreSQL pgvector 检索流程")
    assert "postgresql" in words or "pgvector" in words
    assert "请" not in words
