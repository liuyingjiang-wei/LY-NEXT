from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from ly_next.agent import vision_precaption as vp


@pytest.mark.asyncio
async def test_apply_vision_precaption_degrades_on_llm_error(monkeypatch):
    monkeypatch.setattr(
        vp.config,
        "get",
        lambda key, default=None: (
            {
                "enabled": True,
                "on_failure": "annotate",
                "model_name": "mimo",
            }
            if key == "agent.vision_precaption"
            else default
        ),
    )
    monkeypatch.setattr(vp, "_resolve_precaption_model", lambda: ("mimo", "openai_compat", "mimo-v2.5"))

    client = MagicMock()
    client.chat = AsyncMock(side_effect=RuntimeError("401 Unauthorized"))
    monkeypatch.setattr(vp.LLMFactory, "get_client", lambda *a, **k: client)

    messages = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "描述这张图"},
                {"type": "image_url", "image_url": {"url": "data:image/png;base64,abc"}},
            ],
        }
    ]

    out = await vp.apply_vision_precaption_if_needed(messages)

    assert out is not messages
    assert isinstance(out[0]["content"], str)
    assert "描述这张图" in out[0]["content"]
