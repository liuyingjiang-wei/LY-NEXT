from __future__ import annotations

import pytest

from ly_next.agent.deps import AgentDeps


@pytest.mark.asyncio
async def test_iter_response_stream_parses_openai_delta():
    deps = AgentDeps(llm_client=object())

    async def fake_stream():
        yield {"choices": [{"delta": {"content": "你好"}}]}
        yield {"choices": [{"delta": {"reasoning_content": "思考中"}}]}

    chunks: list[dict] = []
    async for piece in deps._iter_response_stream(fake_stream()):
        chunks.append(piece)

    assert {"type": "chunk", "content": "你好"} in chunks
    assert {"type": "think", "content": "思考中"} in chunks
