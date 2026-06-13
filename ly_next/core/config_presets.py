"""Workbench config presets for first-run onboarding."""

from __future__ import annotations

import copy
from typing import Any

from ly_next.core.config import config

PRESET_IDS = frozenset({"minimal", "standard", "full_stack"})


def _deep_merge(base: dict[str, Any], patch: dict[str, Any]) -> None:
    for key, val in patch.items():
        if isinstance(val, dict) and isinstance(base.get(key), dict):
            _deep_merge(base[key], val)
        else:
            base[key] = copy.deepcopy(val)


def list_config_presets() -> list[dict[str, Any]]:
    return [
        {
            "id": "minimal",
            "label": "极简聊天",
            "description": "仅对话，不依赖 PostgreSQL / Redis；适合 Ollama 或网关试跑。",
            "requires_postgres": False,
            "requires_redis": False,
        },
        {
            "id": "standard",
            "label": "标准助手",
            "description": "ReAct 工具助手 + 会话持久化（需 PostgreSQL）；Redis 可选。",
            "requires_postgres": True,
            "requires_redis": False,
        },
        {
            "id": "full_stack",
            "label": "完整栈",
            "description": "持久化 + RAG 知识库 + Run 观测；需 PostgreSQL，建议 pgvector。",
            "requires_postgres": True,
            "requires_redis": False,
        },
    ]


def _preset_patch(preset_id: str) -> dict[str, Any]:
    if preset_id == "minimal":
        return {
            "agent": {
                "reasoning_mode": "chat",
                "max_steps": 1,
                "max_tools": 1,
                "tool_policy": {
                    "max_tier": "safe",
                    "semantic_select": False,
                    "allow_tools": [],
                },
                "persistence": {"enabled": False},
                "rag": {"enabled": False},
                "observability": {"enabled": True, "persist": False},
            },
        }
    if preset_id == "standard":
        return {
            "agent": {
                "reasoning_mode": "react",
                "max_steps": 8,
                "max_tools": 20,
                "tool_policy": {
                    "max_tier": "network",
                    "semantic_select": True,
                },
                "persistence": {"enabled": True},
                "rag": {"enabled": False},
                "observability": {"enabled": True, "persist": True},
            },
        }
    if preset_id == "full_stack":
        return {
            "agent": {
                "reasoning_mode": "react",
                "max_steps": 8,
                "max_tools": 40,
                "tool_policy": {
                    "max_tier": "network",
                    "semantic_select": True,
                },
                "persistence": {"enabled": True},
                "rag": {"enabled": True},
                "observability": {"enabled": True, "persist": True},
            },
        }
    raise ValueError(f"未知预设: {preset_id}")


def apply_config_preset(preset_id: str) -> dict[str, Any]:
    key = str(preset_id or "").strip().lower().replace("-", "_")
    if key not in PRESET_IDS:
        raise ValueError(f"未知预设: {preset_id}，允许: {', '.join(sorted(PRESET_IDS))}")

    patch = _preset_patch(key)
    for root, fragment in patch.items():
        if not isinstance(fragment, dict):
            continue
        base = config.get(root, {})
        if not isinstance(base, dict):
            base = {}
        merged = copy.deepcopy(base)
        _deep_merge(merged, fragment)
        config.set(root, merged, save=False)

    config.save()
    config.load()

    from ly_next.core.system_readiness import invalidate_readiness_cache

    invalidate_readiness_cache()

    meta = next((p for p in list_config_presets() if p["id"] == key), None)
    return {
        "ok": True,
        "preset_id": key,
        "label": meta["label"] if meta else key,
        "applied_roots": sorted(patch.keys()),
    }
