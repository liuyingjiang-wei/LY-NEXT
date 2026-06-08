from __future__ import annotations

import pytest

from ly_next.core.llm_probe import probe_llm_connectivity
from ly_next.models.registry import ModelRegistry


@pytest.fixture(autouse=True)
def reset_registry():
    ModelRegistry._loaded = False
    ModelRegistry._entries = {}
    yield
    ModelRegistry._loaded = False
    ModelRegistry._entries = {}


@pytest.mark.asyncio
async def test_probe_llm_unregistered():
    ModelRegistry._entries = {}
    ModelRegistry._loaded = True
    result = await probe_llm_connectivity(provider="missing")
    assert result["ok"] is False
    assert "未注册" in result["error"]


@pytest.mark.asyncio
async def test_probe_llm_success():
    ModelRegistry._entries = {
        "main": {
            "name": "main",
            "format": "openai",
            "model": "gpt-4o-mini",
            "api_key": "sk-test",
            "base_url": "",
        }
    }
    ModelRegistry._loaded = True

    class FakeClient:
        model = "gpt-4o-mini"
        base_url = "https://api.example.com/v1"

        async def chat_complete(self, messages, **kwargs):
            return {"choices": [{"message": {"content": "OK"}}]}

        async def close(self):
            pass

    from ly_next.models.factory import LLMFactory

    LLMFactory.create_client = staticmethod(lambda **kwargs: FakeClient())  # type: ignore[method-assign]

    result = await probe_llm_connectivity(provider="main")
    assert result["ok"] is True
    assert result["provider"] == "main"
    assert result["reply"] == "OK"


@pytest.mark.asyncio
async def test_probe_llm_mask_keeps_saved_key():
    ModelRegistry._entries = {
        "main": {
            "name": "main",
            "format": "openai",
            "model": "saved-model",
            "api_key": "sk-saved",
            "base_url": "",
        }
    }
    ModelRegistry._loaded = True
    captured: dict = {}

    class FakeClient:
        model = "gpt-4o-mini"
        base_url = ""

        async def chat_complete(self, messages, **kwargs):
            return {"choices": [{"message": {"content": "OK"}}]}

        async def close(self):
            pass

    def fake_create(**kwargs):
        captured.update(kwargs)
        return FakeClient()

    from ly_next.models.factory import LLMFactory

    LLMFactory.create_client = staticmethod(fake_create)  # type: ignore[method-assign]

    result = await probe_llm_connectivity(
        provider="main",
        overrides={"model": "draft-model", "api_key": "***"},
    )
    assert result["ok"] is True
    assert captured["api_key"] == "sk-saved"
    assert captured["model"] == "draft-model"
