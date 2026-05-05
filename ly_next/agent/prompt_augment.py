from __future__ import annotations

import json
from typing import Any

from ly_next.core.logger import get_logger
from ly_next.rag.document_retriever import get_document_retriever
from ly_next.rag.example_selector import get_example_selector

logger = get_logger(__name__)


def _message_text(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, dict):
        return str(
            content.get("text") or content.get("content") or json.dumps(content, ensure_ascii=False)
        ).strip()
    return str(content).strip()


def last_user_query(messages: list[dict[str, Any]]) -> str:
    for m in reversed(messages or []):
        if (m.get("role") or "").strip().lower() == "user":
            t = _message_text(m.get("content"))
            if t:
                return t
    return ""


def merge_system_context(
    messages: list[dict[str, Any]], context_block: str
) -> list[dict[str, Any]]:
    context_block = (context_block or "").strip()
    if not context_block:
        return messages
    prefix = (
        "【检索与示例上下文】\n"
        + context_block
        + "\n\n请结合用户问题与工具能力作答；若上下文无关可忽略。\n\n"
    )

    out: list[dict[str, Any]] = []
    merged = False
    for m in messages:
        role = (m.get("role") or "user").strip().lower()
        if role == "system" and not merged:
            merged = True
            prev = _message_text(m.get("content"))
            out.append({"role": "system", "content": prefix + prev})
        else:
            out.append(dict(m))
    if not merged:
        out.insert(0, {"role": "system", "content": prefix.strip()})
    return out


async def augment_messages_async(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not messages:
        return messages
    query = last_user_query(messages)
    if not query:
        return messages

    parts: list[str] = []
    try:
        ex_block = await get_example_selector().select_formatted(query)
        if ex_block:
            parts.append("## 相似示例\n" + ex_block)
    except Exception as e:
        logger.warning("[prompt_augment] Example selection failed: %s", e)

    try:
        rag_block = await get_document_retriever().retrieve_formatted(query)
        if rag_block:
            parts.append("## 知识库片段\n" + rag_block)
    except Exception as e:
        logger.warning("[prompt_augment] RAG retrieve failed: %s", e)

    if not parts:
        return messages
    return merge_system_context(messages, "\n\n".join(parts))
