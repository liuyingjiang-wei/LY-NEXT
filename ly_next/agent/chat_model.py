"""Resolve which registered LLM model to use for a chat turn."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ly_next.core.config import config
from ly_next.models.registry import ModelRegistry


@dataclass(frozen=True)
class ChatModelSelection:
    """Selected model for one chat turn."""

    name: str
    format: str
    model: str | None
    via: str

    @property
    def provider(self) -> str:
        """Backward-compatible alias used by AgentDeps."""
        return self.name


def selection_payload(result: ChatModelSelection) -> dict[str, Any]:
    return {
        "name": result.name,
        "format": result.format,
        "provider": result.name,
        "model": result.model,
        "via": result.via,
    }


def resolve_chat_model(
    *,
    request_name: str | None = None,
    request_model: str | None = None,
) -> ChatModelSelection:
    ModelRegistry.ensure_loaded()

    if request_name:
        key = str(request_name).strip()
        entry = ModelRegistry.get_entry(key)
        if entry:
            override = str(request_model).strip() if request_model else ""
            model_id = override or str(entry.get("model") or "").strip() or None
            return ChatModelSelection(
                name=entry["name"],
                format=str(entry.get("format") or "openai"),
                model=model_id,
                via="manual",
            )

    default = ModelRegistry.default_name()
    entry = ModelRegistry.get_entry(default)
    if entry:
        override = str(request_model).strip() if request_model else ""
        model_id = override or str(entry.get("model") or "").strip() or None
        return ChatModelSelection(
            name=entry["name"],
            format=str(entry.get("format") or "openai"),
            model=model_id,
            via="default",
        )

    prov = str(config.get("llm.default_provider") or "openai").strip().lower()
    block = config.get(f"{prov}_llm", {}) or {}
    mod = block.get("model") if isinstance(block, dict) else None
    return ChatModelSelection(
        name=prov,
        format=prov,
        model=str(mod).strip() if mod else None,
        via="legacy",
    )
