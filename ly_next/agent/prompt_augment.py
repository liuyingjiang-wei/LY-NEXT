from __future__ import annotations

import asyncio
import json
import re
from typing import Any

from ly_next.agent.skills_loader import format_skills_summary, skills_enabled
from ly_next.agent.startup_memory import get_startup_memory_block
from ly_next.core.config import config
from ly_next.core.logger import get_logger
from ly_next.rag.document_retriever import get_document_retriever
from ly_next.rag.example_selector import get_example_selector

logger = get_logger(__name__)

_CHAT_GREETING = re.compile(
    r"^(你好|您好|hi\b|hello\b|嗨|在吗|早上好|晚上好|thanks|thank you|ok\b|okay\b)[\s!！。.?？]*$",
    re.IGNORECASE,
)

_TOOL_INTENT = re.compile(
    r"(?:"
    r"搜索|查一下|查询|联网|搜一下|网上|最新|新闻|天气|股价|汇率|"
    r"search|look\s*up|web\s*search|browse|news|weather|"
    r"生成|制作|导出|写一份|整理成|做成|"
    r"word|docx?|excel|xlsx|pptx?|表格|文档|演示|报告|幻灯片"
    r")",
    re.IGNORECASE,
)

_DIRECT_CHAT = re.compile(
    r"(?:"
    r"解释|说明|介绍|什么是|是什么|啥是|什么意思|何谓|"
    r"用.{0,8}句话|简述|概括|总结|梳理|讲讲|聊聊|谈谈|"
    r"如何理解|怎么理解|有什么区别|区别是什么|优缺点|"
    r"explain|what\s+is|what's|describe|summarize|overview|in\s+\d+\s+sentences?"
    r")",
    re.IGNORECASE,
)


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


def _prompt_augment_cfg() -> dict[str, Any]:
    cfg = config.get("agent.prompt_augment", {}) or {}
    return cfg if isinstance(cfg, dict) else {}


def is_tool_intent_query(query: str) -> bool:
    """Queries that should use tools (search / office export) instead of RAG/context."""
    q = (query or "").strip()
    if not q:
        return False
    if _prompt_augment_cfg().get("skip_tool_intents", True) is False:
        return False
    return bool(_TOOL_INTENT.search(q))


def is_direct_chat_query(query: str) -> bool:
    """Conceptual Q&A that should not pay ReAct tool-schema or retrieval costs."""
    q = (query or "").strip()
    if not q or is_tool_intent_query(q):
        return False
    if _prompt_augment_cfg().get("auto_direct_chat", True) is False:
        return False
    if not _DIRECT_CHAT.search(q):
        return False
    if re.search(r"[A-Za-z]", q):
        return False
    return True


def is_fast_chat_query(query: str) -> bool:
    """Single-pass chat mode: no tool schemas, no ReAct loop (OpenClaw/Cursor-style)."""
    q = (query or "").strip()
    if not q or is_tool_intent_query(q):
        return False
    if _prompt_augment_cfg().get("auto_direct_chat", True) is False:
        return False
    if is_direct_chat_query(q):
        return True
    cfg = _prompt_augment_cfg()
    if cfg.get("skip_greetings", True) and _CHAT_GREETING.match(q):
        return True
    max_chars = max(0, int(cfg.get("fast_chat_max_chars", 120) or 120))
    if max_chars and len(q) <= max_chars:
        if re.search(r"[A-Za-z]", q):
            return False
        return True
    return False


def should_skip_retrieval_augment(query: str) -> bool:
    """Skip embedding/RAG/example retrieval for greetings and very short queries."""
    q = (query or "").strip()
    if not q:
        return True
    if is_tool_intent_query(q):
        return True
    if is_direct_chat_query(q):
        return True
    cfg = _prompt_augment_cfg()
    min_len = max(0, int(cfg.get("min_query_chars", 12) or 12))
    if min_len and len(q) < min_len:
        return True
    if cfg.get("skip_greetings", True) and _CHAT_GREETING.match(q):
        return True
    return False


def should_skip_skills_augment(query: str) -> bool:
    """Skip skills manifest on fast chat turns (large static prefix)."""
    q = (query or "").strip()
    if not q:
        return True
    if _prompt_augment_cfg().get("auto_skip_skills_on_fast_path", True) is False:
        return False
    return is_fast_chat_query(q) or is_tool_intent_query(q) or should_skip_retrieval_augment(q)


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
    skip_skills: bool = False,
) -> list[dict[str, Any]]:
    if not messages:
        return messages

    if not skip_memory:
        memory_block = get_startup_memory_block()
        if memory_block:
            messages = merge_system_context(messages, memory_block)

    query = last_user_query(messages)
    if query and not skip_skills:
        skip_skills = should_skip_skills_augment(query)

    skills_cfg = config.get("agent.skills", {}) or {}
    if (
        not skip_skills
        and skills_enabled()
        and isinstance(skills_cfg, dict)
        and skills_cfg.get("inject_summary", True)
    ):
        summary = format_skills_summary()
        if summary:
            messages = merge_system_context(messages, summary)

    if not query:
        return messages

    rag_on = bool(config.get("agent.rag.enabled", False)) and not skip_rag
    ctx_on = bool(config.get("agent.context.enabled", True)) and not skip_context
    if should_skip_retrieval_augment(query):
        rag_on = False
        ctx_on = False
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
