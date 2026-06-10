from __future__ import annotations

from ly_next.rag.chunking import chunk_text
from ly_next.rag.markdown_chunker import chunk_markdown


def chunk_document(
    text: str,
    *,
    strategy: str,
    chunk_size: int,
    overlap: int,
) -> list[str]:
    mode = (strategy or "fixed").strip().lower()
    if mode == "markdown":
        return chunk_markdown(text, chunk_size, overlap)
    return chunk_text(text, chunk_size, overlap)
