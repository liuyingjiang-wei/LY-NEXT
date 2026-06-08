"""Probe LLM connectivity via the model registry."""

from __future__ import annotations

import time
from typing import Any

from ly_next.agent.llm_text import text_from_chat_response
from ly_next.agent.vision_precaption import _extract_assistant_text
from ly_next.models.factory import LLMFactory
from ly_next.models.registry import ModelRegistry

_SETTINGS_MASK = "***"


def _reply_snippet(resp: Any) -> str:
    if not isinstance(resp, dict):
        return str(resp or "").strip()[:120]
    text = text_from_chat_response(resp)
    if not text:
        text = _extract_assistant_text(resp)
    text = (text or "").strip()
    if len(text) > 120:
        return text[:119] + "…"
    return text or "(空回复)"


async def probe_llm_connectivity(
    *,
    provider: str | None = None,
    overrides: dict[str, Any] | None = None,
    timeout: int | None = None,
) -> dict[str, Any]:
    ModelRegistry.ensure_loaded()
    name = str(provider or ModelRegistry.default_name()).strip()
    entry = ModelRegistry.get_entry(name)

    if overrides and entry:
        merged = dict(entry)
        for k, v in overrides.items():
            if k == "api_key" and v == _SETTINGS_MASK:
                continue
            if v is not None and v != "":
                merged[k] = v
        try:
            entry = ModelRegistry.merge_update(
                name,
                format=str(merged.get("format") or "openai"),
                api_key=str(merged.get("api_key") or ""),
                base_url=str(merged.get("base_url") or ""),
                model=str(merged.get("model") or ""),
            )
        except ValueError as e:
            return {"ok": False, "provider": name, "error": str(e)}
    elif not entry:
        return {"ok": False, "provider": name, "error": f"模型 '{name}' 未注册"}

    kw: dict[str, Any] = {"registry_name": name}
    if timeout is not None:
        kw["timeout"] = timeout
    if overrides and overrides.get("model"):
        kw["model"] = overrides["model"]

    t0 = time.perf_counter()
    client = None
    try:
        if overrides and entry:
            client = LLMFactory.create_client(**{**entry, **kw})
        else:
            client = LLMFactory.create_client(**kw)
        resp = await client.chat_complete(
            [{"role": "user", "content": "Reply with exactly: OK"}],
            temperature=0,
            max_tokens=16,
        )
        latency_ms = int((time.perf_counter() - t0) * 1000)
        return {
            "ok": True,
            "provider": name,
            "format": entry.get("format"),
            "model": getattr(client, "model", entry.get("model")),
            "base_url": getattr(client, "base_url", entry.get("base_url")),
            "latency_ms": latency_ms,
            "reply": _reply_snippet(resp),
        }
    except Exception as e:
        latency_ms = int((time.perf_counter() - t0) * 1000)
        return {
            "ok": False,
            "provider": name,
            "model": entry.get("model"),
            "base_url": entry.get("base_url"),
            "latency_ms": latency_ms,
            "error": str(e),
        }
    finally:
        if client is not None:
            close_fn = getattr(client, "close", None)
            if callable(close_fn):
                try:
                    await close_fn()
                except Exception:
                    pass
