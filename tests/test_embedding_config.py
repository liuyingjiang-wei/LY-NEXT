from __future__ import annotations

from ly_next.rag.embedding_config import resolve_embedding_http_config


def test_embedding_base_url_override():
    cfg = {
        "model": "custom-embed",
        "config_ref": "rag_embedding_llm",
        "base_url": "http://localhost:11434/v1",
    }

    def _get(key: str):
        if key == "rag_embedding_llm":
            return {"model": "text-embedding-3-small", "base_url": "https://api.openai.com/v1"}
        return None

    out = resolve_embedding_http_config(cfg, _get)
    assert out["base_url"] == "http://localhost:11434/v1"
    assert out["model"] == "custom-embed"
