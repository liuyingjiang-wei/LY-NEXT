"""Explicit knowledge-base search tool (agent-driven RAG)."""

from __future__ import annotations

from ly_next.core.config import config
from ly_next.rag.document_retriever import get_document_retriever
from ly_next.tools.base import ToolResult, tool


def _rag_enabled() -> bool:
    return bool(config.get("agent.rag.enabled", False))


@tool(
    name="knowledge_search",
    description=(
        "Search indexed project docs (agent.rag.documents_path). "
        "Use for LY-NEXT config, architecture, plugins, deployment. "
        "Not for agent playbooks (list_skills/read_skill) or live web (web_search)."
    ),
    category="general",
    parameters={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Natural-language search query",
            },
            "top_k": {
                "type": "integer",
                "description": "Maximum number of snippets to return (default from agent.rag.top_k)",
                "minimum": 1,
                "maximum": 20,
            },
        },
        "required": ["query"],
    },
)
async def knowledge_search(query: str, top_k: int | None = None) -> ToolResult:
    if not _rag_enabled():
        return ToolResult(
            success=False,
            error="Knowledge base is disabled (agent.rag.enabled=false)",
        )
    q = (query or "").strip()
    if not q:
        return ToolResult(success=False, error="query is required")

    tk: int | None = None
    if top_k is not None:
        try:
            tk = max(1, min(20, int(top_k)))
        except (TypeError, ValueError):
            return ToolResult(success=False, error="top_k must be an integer between 1 and 20")

    payload = await get_document_retriever().retrieve_results(q, top_k=tk)
    if not payload.get("enabled"):
        return ToolResult(success=False, error=str(payload.get("hint") or "RAG disabled"))
    hits = payload.get("hits") or []
    if not hits:
        return ToolResult(
            success=True,
            result={
                "query": q,
                "hits": [],
                "chunks_loaded": payload.get("chunks_loaded", 0),
                "documents_path": payload.get("documents_path", ""),
                "hint": payload.get("hint") or "No matching snippets",
            },
        )
    return ToolResult(
        success=True,
        result={
            "query": q,
            "hits": hits,
            "chunks_loaded": payload.get("chunks_loaded", 0),
            "documents_path": payload.get("documents_path", ""),
        },
    )
