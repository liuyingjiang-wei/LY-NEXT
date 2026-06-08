from __future__ import annotations

import pytest

from ly_next.agent.chat_model import resolve_chat_model
from ly_next.models.registry import ModelRegistry


@pytest.fixture(autouse=True)
def seed_registry():
    ModelRegistry._entries = {
        "main": {
            "name": "main",
            "format": "openai_compat",
            "model": "gpt-4o-mini",
            "api_key": "sk-x",
            "base_url": "https://api.example.com/v1",
        }
    }
    ModelRegistry._loaded = True
    yield
    ModelRegistry._loaded = False
    ModelRegistry._entries = {}


def test_resolve_default_model(monkeypatch):
    monkeypatch.setattr(
        "ly_next.agent.chat_model.ModelRegistry.default_name",
        staticmethod(lambda: "main"),
    )
    sel = resolve_chat_model()
    assert sel.name == "main"
    assert sel.format == "openai_compat"
    assert sel.via == "default"


def test_resolve_manual_override():
    sel = resolve_chat_model(request_name="main", request_model="custom-id")
    assert sel.name == "main"
    assert sel.model == "custom-id"
    assert sel.via == "manual"
