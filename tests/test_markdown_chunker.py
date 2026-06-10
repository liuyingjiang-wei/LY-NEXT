from __future__ import annotations

from ly_next.rag.markdown_chunker import chunk_markdown


def test_chunk_markdown_preserves_code_block():
    text = "# Title\n\nintro\n\n```python\nprint('hi')\n```\n\n## Sub\n\nbody text"
    chunks = chunk_markdown(text, chunk_size=200, overlap=0)
    assert any("print('hi')" in c for c in chunks)
    assert any(c.startswith("# Title") or "Title" in c for c in chunks)


def test_chunk_markdown_splits_long_section():
    body = "word " * 400
    text = f"# Section\n\n{body}"
    chunks = chunk_markdown(text, chunk_size=120, overlap=10)
    assert len(chunks) >= 2
