from __future__ import annotations

import re

from ly_next.rag.chunking import chunk_text

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+)$", re.MULTILINE)
_FENCE_RE = re.compile(r"^(`{3,}|~{3,}).*$", re.MULTILINE)


def _split_preserving_fences(text: str) -> list[tuple[str, bool]]:
    """Return (segment, is_code_fence_block) pieces."""
    lines = text.splitlines(keepends=True)
    if not lines:
        return []

    segments: list[tuple[str, bool]] = []
    buf: list[str] = []
    in_fence = False
    fence_mark = ""

    for line in lines:
        m = _FENCE_RE.match(line.rstrip("\r\n"))
        if m:
            mark = m.group(1)
            if not in_fence:
                if buf:
                    segments.append(("".join(buf), False))
                    buf = []
                in_fence = True
                fence_mark = mark[0] * len(mark)
                buf.append(line)
                continue
            if line.strip().startswith(fence_mark[: len(mark)]):
                buf.append(line)
                segments.append(("".join(buf), True))
                buf = []
                in_fence = False
                fence_mark = ""
                continue
        buf.append(line)

    if buf:
        segments.append(("".join(buf), in_fence))
    return segments


def _split_by_headings(text: str) -> list[str]:
    parts: list[str] = []
    last = 0
    for m in _HEADING_RE.finditer(text):
        if m.start() > last:
            piece = text[last : m.start()].strip()
            if piece:
                parts.append(piece)
        last = m.start()
    tail = text[last:].strip()
    if tail:
        parts.append(tail)
    return parts or [text.strip()]


def chunk_markdown(text: str, chunk_size: int, overlap: int) -> list[str]:
    """Split markdown by headings and code fences, then fixed-size sub-chunks."""
    text = (text or "").strip()
    if not text:
        return []
    if chunk_size <= 0:
        return [text]

    sections: list[str] = []
    for segment, is_code in _split_preserving_fences(text):
        segment = segment.strip()
        if not segment:
            continue
        if is_code:
            sections.append(segment)
            continue
        for sec in _split_by_headings(segment):
            sec = sec.strip()
            if sec:
                sections.append(sec)

    chunks: list[str] = []
    for sec in sections:
        if len(sec) <= chunk_size:
            chunks.append(sec)
        else:
            chunks.extend(chunk_text(sec, chunk_size, overlap))
    return [c for c in chunks if c.strip()]
