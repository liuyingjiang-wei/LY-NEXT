from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from ly_next.agent.chat_pipeline import ChatTurnRequest, prepare_chat_turn


@pytest.mark.asyncio
async def test_prepare_runs_vision_and_routing_in_parallel():
  calls: list[str] = []

  async def fake_vision(messages, *, skip_precaption=False):
    calls.append("vision")
    await asyncio.sleep(0.05)
    return messages

  async def fake_route(*args, **kwargs):
    calls.append("route")
    await asyncio.sleep(0.05)
    from ly_next.agent.model_router import ModelRoutingResult, TaskKind

    return ModelRoutingResult(
      provider="openai",
      model="gpt-4o-mini",
      task_kind=TaskKind.CHAT,
      via="test",
    )

  with (
    patch("ly_next.agent.chat_pipeline.prepare_messages_for_agent", new_callable=AsyncMock) as prep,
    patch("ly_next.agent.chat_pipeline.apply_vision_precaption_if_needed", side_effect=fake_vision),
    patch("ly_next.agent.chat_pipeline.resolve_model_routing", side_effect=fake_route),
    patch("ly_next.agent.chat_pipeline.augment_messages_async", new_callable=AsyncMock) as aug,
    patch("ly_next.agent.chat_pipeline.persist_chat_turn", new_callable=AsyncMock),
  ):
    prep.return_value = ("tid", [{"role": "user", "content": "hi"}], [{"role": "user", "content": "hi"}])
    aug.side_effect = lambda m, **kw: m
    await prepare_chat_turn(
      ChatTurnRequest(
        client_messages=[{"role": "user", "content": "hi"}],
        parallel_prep=True,
        persist_user_async=False,
        skip_augment=True,
      )
    )

  assert "vision" in calls and "route" in calls
  assert calls.index("vision") < 2 and calls.index("route") < 2
