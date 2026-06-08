from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from ly_next.agent.chat_model import ChatModelSelection
from ly_next.agent.chat_pipeline import PreparedChatTurn, build_agent_deps


@pytest.mark.asyncio
async def test_build_agent_deps_binds_registry_client(monkeypatch):
    routed = ChatModelSelection(
        name="mimo",
        format="openai_compat",
        model="mimo-v2.5-pro",
        via="default",
    )
    prepared = PreparedChatTurn(
        thread_id="t1",
        messages=[{"role": "user", "content": "hi"}],
        user_to_persist=[],
        routed=routed,
        turn_meta={"mode": "chat"},
        router_payload={},
        plan=None,
    )
    fake_client = MagicMock(name="llm_client")

    monkeypatch.setattr(
        "ly_next.models.registry.ModelRegistry.build_client_kwargs",
        lambda name, **_: {"registry_name": name, "model": "mimo-v2.5-pro"},
    )
    monkeypatch.setattr(
        "ly_next.models.factory.LLMFactory.get_client",
        lambda **_: fake_client,
    )

    deps = build_agent_deps(prepared, agent_mode="chat")

    assert deps.llm_client is fake_client
    assert deps.provider == "mimo"
    assert deps.model == "mimo-v2.5-pro"
