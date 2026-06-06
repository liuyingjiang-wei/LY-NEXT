from __future__ import annotations

import pytest

from ly_next.core.config import config
from ly_next.core.system_readiness import (
    gather_readiness,
    llm_provider_status,
    mask_api_key,
    show_full_api_key,
)


def test_mask_api_key_short_and_long(monkeypatch):
    monkeypatch.delenv("LY_NEXT_SHOW_FULL_API_KEY", raising=False)
    assert mask_api_key("") == "—"
    assert "…" in mask_api_key("abcdefghijklmnop")
    assert mask_api_key("abcdefghijklmnop").startswith("abcd")
    assert mask_api_key("abcdefghijklmnop").endswith("mnop")


def test_mask_api_key_show_full_env(monkeypatch):
    monkeypatch.setenv("LY_NEXT_SHOW_FULL_API_KEY", "1")
    assert show_full_api_key() is True
    assert mask_api_key("secret-key-value") == "secret-key-value"


def test_llm_provider_status_openai_missing_key(monkeypatch):
    monkeypatch.setattr(
        config,
        "get",
        lambda key, default=None: {
            "llm.default_provider": "openai",
            "openai_llm": {"model": "gpt-4o-mini", "api_key": "", "base_url": ""},
        }.get(key, default),
    )
    status = llm_provider_status()
    assert status["ok"] is False
    assert status["provider"] == "openai"
    assert status["hint"]


def test_llm_provider_status_ollama_ok(monkeypatch):
    monkeypatch.setattr(
        config,
        "get",
        lambda key, default=None: {
            "llm.default_provider": "ollama",
            "ollama_llm": {"model": "qwen2.5", "base_url": "http://localhost:11434"},
        }.get(key, default),
    )
    status = llm_provider_status()
    assert status["ok"] is True


@pytest.mark.asyncio
async def test_gather_readiness_shape():
    result = await gather_readiness()
    assert "ready_for_chat" in result
    assert "checks" in result
    assert "auth" in result["checks"]
    assert "llm" in result["checks"]
    assert "postgres" in result["checks"]
    assert "redis" in result["checks"]
    assert isinstance(result["degraded"], list)
    assert isinstance(result["suggestions"], list)
