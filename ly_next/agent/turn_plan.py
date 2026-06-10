"""Early turn planning: intent, mode, and prep skips before heavy work."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ly_next.agent.prompt_augment import (
    is_fast_chat_query,
    is_tool_intent_query,
    last_user_query,
    should_skip_retrieval_augment,
    should_skip_skills_augment,
)
from ly_next.core.config import config


def pipeline_cfg(key: str, default: Any) -> Any:
    return config.get(f"agent.chat_pipeline.{key}", default)


def resolve_effective_mode(req: Any) -> str:
    """Downgrade react → chat for non-tool turns (single LLM pass, immediate streaming)."""
    requested = (getattr(req, "mode", None) or "").strip().lower()
    if requested == "react":
        return "react"
    if requested and requested not in ("",):
        return requested
    mode = (requested or config.get("agent.reasoning_mode") or "react").strip().lower()
    if mode not in ("react", ""):
        return mode or "react"
    if pipeline_cfg("auto_direct_chat_mode", True) is False:
        return "react"
    q = last_user_query(getattr(req, "client_messages", None) or [])
    if is_tool_intent_query(q):
        return "react"
    if is_fast_chat_query(q):
        return "chat"
    return "react"


def resolve_augment_skips(req: Any) -> tuple[bool, bool]:
    """Apply fast-path skips for tool-heavy turns (search, doc export, etc.)."""
    skip_rag = bool(getattr(req, "skip_rag", False))
    skip_context = bool(getattr(req, "skip_context", False))
    if skip_rag and skip_context:
        return skip_rag, skip_context
    if pipeline_cfg("auto_skip_tool_intents", True) is False:
        return skip_rag, skip_context
    q = last_user_query(getattr(req, "client_messages", None) or [])
    if is_tool_intent_query(q) or should_skip_retrieval_augment(q):
        return True, True
    return skip_rag, skip_context


@dataclass(frozen=True)
class TurnPlan:
    """Resolved execution plan for one user turn."""

    effective_mode: str
    requested_mode: str
    query: str
    fast_path: bool
    tool_intent: bool
    skip_rag: bool
    skip_context: bool
    skip_memory: bool
    skip_skills: bool
    skip_augment: bool


def build_turn_plan(req: Any, messages: list[dict[str, Any]] | None = None) -> TurnPlan:
    """Classify turn intent and prep skips from client messages or merged thread."""
    source = messages if messages is not None else (getattr(req, "client_messages", None) or [])
    query = last_user_query(source)
    requested = (getattr(req, "mode", None) or "react").strip().lower()
    effective = resolve_effective_mode(req)
    tool_intent = bool(query and is_tool_intent_query(query))
    fast_path = bool(query and is_fast_chat_query(query) and not tool_intent)

    skip_rag, skip_context = resolve_augment_skips(req)
    if effective == "react" and bool(pipeline_cfg("skip_rag_on_react", True)):
        skip_rag = True
    if fast_path:
        skip_rag, skip_context = True, True

    skip_memory = bool(getattr(req, "skip_memory", False))
    if not skip_memory and bool(pipeline_cfg("auto_skip_memory_on_fast_path", True)):
        if fast_path:
            skip_memory = True

    skip_skills = bool(query and should_skip_skills_augment(query))

    skip_augment = getattr(req, "skip_augment", None) is True
    if getattr(req, "skip_augment", None) is None and fast_path and bool(
        pipeline_cfg("skip_augment_on_fast_path", True)
    ):
        skip_augment = True

    if (
        tool_intent
        and requested == "react"
        and bool(pipeline_cfg("skip_augment_on_tool_intent", True))
    ):
        skip_augment = True
        skip_rag, skip_context = True, True
        if bool(pipeline_cfg("skip_memory_on_tool_intent", True)):
            skip_memory = True

    return TurnPlan(
        effective_mode=effective,
        requested_mode=requested,
        query=query,
        fast_path=fast_path,
        tool_intent=tool_intent,
        skip_rag=skip_rag,
        skip_context=skip_context,
        skip_memory=skip_memory,
        skip_skills=skip_skills,
        skip_augment=skip_augment,
    )
