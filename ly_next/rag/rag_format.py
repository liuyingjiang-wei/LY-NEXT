"""Human-readable formatting for knowledge-base search results."""

from __future__ import annotations

from typing import Any


def format_knowledge_search_text(
    *,
    query: str,
    hits: list[dict[str, Any]],
    documents_path: str = "",
    chunks_loaded: int = 0,
) -> str:
    q = (query or "").strip()
    bar = "─" * 42
    lines = [
        bar,
        "知识库检索",
        f"问题：{q}",
        f"语料：{chunks_loaded} 片段",
        bar,
        "",
    ]
    if documents_path:
        lines.insert(3, f"路径：{documents_path}")
    if not hits:
        lines.append("（未命中相关片段，可换关键词或检查 documents_path）")
        return "\n".join(lines)
    for hit in hits:
        rank = hit.get("rank", 0)
        score = hit.get("score", 0)
        source = (hit.get("source") or "").strip()
        text = (hit.get("text") or hit.get("preview") or "").strip()
        head = f"[{rank}] 相关度 {score}"
        if source:
            head += f" · {source}"
        lines.append(head)
        if text:
            lines.append(text)
        lines.append("")
    lines.append("引用时请标注来源路径。")
    return "\n".join(lines).rstrip()
