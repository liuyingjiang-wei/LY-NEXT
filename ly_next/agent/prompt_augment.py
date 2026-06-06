from __future__ import annotations

import asyncio
import json
from typing import Any

from ly_next.agent.startup_memory import get_startup_memory_block
from ly_next.core.config import config
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
    prefix = "【上下文】\n" + context_block + "\n\n结合用户问题作答；无关则忽略。\n\n"

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


async def augment_messages_async(
    messages: list[dict[str, Any]],
    *,
    skip_rag: bool = False,
    skip_context: bool = False,
    skip_memory: bool = False,
) -> list[dict[str, Any]]:
    if not messages:
        return messages

    if not skip_memory:
        memory_block = get_startup_memory_block()
        if memory_block:
            messages = merge_system_context(messages, memory_block)

    query = last_user_query(messages)
    if not query:
        return messages

    rag_on = bool(config.get("agent.rag.enabled", False)) and not skip_rag
    ctx_on = bool(config.get("agent.context.enabled", True)) and not skip_context
    if not rag_on and not ctx_on:
        return messages

    parts: list[str] = []

    async def _examples() -> str | None:
        try:
            ex_block = await get_example_selector().select_formatted(query)
            if ex_block:
                return "## 相似示例\n" + ex_block
        except Exception as e:
            logger.warning("[prompt_augment] Example selection failed: %s", e)
        return None

    async def _rag() -> str | None:
        try:
            rag_block = await get_document_retriever().retrieve_formatted(query)
            if rag_block:
                return "## 知识库片段\n" + rag_block
        except Exception as e:
            logger.warning("[prompt_augment] RAG retrieve failed: %s", e)
        return None

    tasks: list[tuple[str, asyncio.Task[str | None]]] = []
    if ctx_on:
        tasks.append(("ctx", asyncio.create_task(_examples())))
    if rag_on:
        tasks.append(("rag", asyncio.create_task(_rag())))
    if tasks:
        results = await asyncio.gather(*(t for _, t in tasks), return_exceptions=True)
        for (label, _), result in zip(tasks, results, strict=True):
            if isinstance(result, Exception):
                logger.warning("[prompt_augment] %s failed: %s", label, result)
                continue
            if result:
                parts.append(result)

    logger.debug(
        "[prompt_augment] ctx_on=%s rag_on=%s parts=%s ex=%s rag=%s",
        ctx_on,
        rag_on,
        len(parts),
        any(p.startswith("## 相似示例") for p in parts),
        any(p.startswith("## 知识库片段") for p in parts),
    )

    if not parts:
        return messages
    return merge_system_context(messages, "\n\n".join(parts))
