"""System readiness checks for onboarding UI and dependency status."""

from __future__ import annotations

import os
import re
import time
from typing import Any

from ly_next.core.config import config
from ly_next.core.thread_persistence import persistence_active, persistence_enabled

_LLM_PROVIDER_BLOCKS: dict[str, str] = {
    "openai": "openai_llm",
    "anthropic": "anthropic_llm",
    "ollama": "ollama_llm",
    "openai_compat": "openai_compat_llm",
}

_PLACEHOLDER_RE = re.compile(r"\$\{\w+")


def show_full_api_key() -> bool:
    return os.environ.get("LY_NEXT_SHOW_FULL_API_KEY", "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def mask_api_key(key: str, *, show_full: bool | None = None) -> str:
    raw = str(key or "").strip()
    if not raw:
        return "—"
    if show_full if show_full is not None else show_full_api_key():
        return raw
    if len(raw) <= 12:
        return f"{raw[:2]}…{raw[-2:]}"
    return f"{raw[:4]}…{raw[-4:]}"


def _is_unset_secret(value: str) -> bool:
    s = str(value or "").strip()
    if not s:
        return True
    if _PLACEHOLDER_RE.search(s):
        return True
    return False


def llm_provider_status(provider: str | None = None) -> dict[str, Any]:
    prov = str(provider or config.get("llm.default_provider") or "openai").strip().lower()
    block_key = _LLM_PROVIDER_BLOCKS.get(prov, f"{prov}_llm")
    block = config.get(block_key, {}) or {}
    if not isinstance(block, dict):
        block = {}

    api_key = str(block.get("api_key") or "").strip()
    base_url = str(block.get("base_url") or "").strip()
    model = str(block.get("model") or "").strip()

    if prov == "ollama":
        ok = bool(model)
        hint = None if ok else "请在「模型网关」配置 Ollama 模型名，并确认 Ollama 服务可访问"
        return {"ok": ok, "provider": prov, "model": model, "base_url": base_url, "hint": hint}

    if prov == "openai_compat" and api_key.lower() in ("not-needed", "not_needed"):
        ok = bool(base_url)
        hint = None if ok else "请在「模型网关」填写 OpenAI 兼容网关的 base_url"
        return {"ok": ok, "provider": prov, "model": model, "base_url": base_url, "hint": hint}

    ok = not _is_unset_secret(api_key)
    hint = None if ok else f"请在「模型网关」为 {prov} 填写 API 密钥，或设置对应环境变量"
    return {"ok": ok, "provider": prov, "model": model, "base_url": base_url, "hint": hint}


async def probe_database() -> dict[str, Any]:
    from ly_next.core.database import db

    out: dict[str, Any] = {"connected": False, "error": None}
    try:
        await db.connect()
        out["connected"] = db._engine is not None
    except Exception as e:
        out["error"] = str(e)
    return out


async def probe_redis() -> dict[str, Any]:
    from ly_next.core.cache import cache

    out: dict[str, Any] = {"connected": False, "error": None}
    try:
        await cache.connect()
        if cache._client is not None:
            await cache._client.ping()
            out["connected"] = True
    except Exception as e:
        out["error"] = str(e)
    return out


def _degraded_features(*, db_connected: bool, redis_connected: bool) -> list[dict[str, str]]:
    degraded: list[dict[str, str]] = []
    if not persistence_enabled():
        degraded.append(
            {
                "id": "thread_persistence",
                "label": "会话持久化",
                "impact": "agent.persistence.enabled 为 false，跨轮会话不会写入数据库",
            }
        )
    elif not persistence_active() or not db_connected:
        degraded.append(
            {
                "id": "thread_persistence",
                "label": "会话持久化",
                "impact": "未连接 PostgreSQL，thread_id 与历史消息无法跨重启保留",
            }
        )
    if not db_connected:
        degraded.append(
            {
                "id": "task_persistence",
                "label": "任务持久化",
                "impact": "任务列表仅存内存，重启后清空",
            }
        )
    if not redis_connected:
        degraded.append(
            {
                "id": "cache",
                "label": "Redis 缓存",
                "impact": "部分缓存与配额统计退化为进程内或不可用",
            }
        )
    if config.get("agent.rag.enabled", False) and not db_connected:
        degraded.append(
            {
                "id": "rag_vector",
                "label": "向量检索",
                "impact": "RAG 可能回退为词法检索，效果受限",
            }
        )
    return degraded


_READINESS_CACHE: tuple[float, dict[str, Any]] | None = None
_READINESS_CACHE_TTL_SEC = 5.0


async def gather_readiness(*, force_refresh: bool = False) -> dict[str, Any]:
    global _READINESS_CACHE
    now = time.monotonic()
    if (
        not force_refresh
        and _READINESS_CACHE is not None
        and now - _READINESS_CACHE[0] < _READINESS_CACHE_TTL_SEC
    ):
        return _READINESS_CACHE[1]
    auth_key = str(config.get("auth.api_key") or "").strip()
    auth_ok = bool(auth_key) or not config.get("auth.enabled", True)

    llm = llm_provider_status()
    db_probe = await probe_database()
    redis_probe = await probe_redis()

    db_connected = bool(db_probe.get("connected"))
    redis_connected = bool(redis_probe.get("connected"))
    degraded = _degraded_features(db_connected=db_connected, redis_connected=redis_connected)

    ready_for_chat = bool(llm.get("ok"))

    suggestions: list[str] = []
    if not llm.get("ok") and llm.get("hint"):
        suggestions.append(str(llm["hint"]))
    if not db_connected:
        suggestions.append(
            "可选：运行 install 脚本或 docker compose 启用 PostgreSQL，以持久化会话与任务"
        )
    if not redis_connected:
        suggestions.append("可选：启动 Redis 以启用缓存（非对话必需）")
    if auth_ok and ready_for_chat and not suggestions:
        suggestions.append("配置就绪，可在「智能对话」发送第一条消息")

    payload = {
        "ready_for_chat": ready_for_chat,
        "checks": {
            "auth": {
                "ok": auth_ok,
                "enabled": bool(config.get("auth.enabled", True)),
                "hint": None if auth_ok else "服务鉴权已开启但未配置 API 密钥",
            },
            "llm": llm,
            "postgres": {
                "ok": db_connected,
                "connected": db_connected,
                "persistence_enabled": persistence_enabled(),
                "persistence_active": persistence_active() and db_connected,
                "error": db_probe.get("error"),
                "hint": None
                if db_connected
                else "PostgreSQL 未连接（可选，但影响会话/任务持久化）",
            },
            "redis": {
                "ok": redis_connected,
                "connected": redis_connected,
                "error": redis_probe.get("error"),
                "hint": None if redis_connected else "Redis 未连接（可选）",
            },
        },
        "degraded": degraded,
        "suggestions": suggestions,
    }
    _READINESS_CACHE = (now, payload)
    return payload
