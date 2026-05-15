from __future__ import annotations

import httpx
import pytest

from ly_next.core.run_telemetry import begin_run, end_run, get_public_snapshot
from ly_next.models.openai_compat import OpenAICompatibleLLMClient


@pytest.mark.asyncio
async def test_chat_records_usage_and_returns_body():
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "hello"}}],
                "usage": {"prompt_tokens": 3, "completion_tokens": 4, "total_tokens": 7},
            },
        )

    transport = httpx.MockTransport(handler)
    client = OpenAICompatibleLLMClient(
        model="m1",
        api_key="sk-test",
        base_url="http://example.test/v1",
        timeout=15,
    )
    client._client = httpx.AsyncClient(
        transport=transport,
        base_url="http://example.test/v1",
        headers={"Authorization": "Bearer sk-test"},
    )
    tok = begin_run("t-openai")
    try:
        out = await client.chat([{"role": "user", "content": "hi"}], stream=False)
        assert out["choices"][0]["message"]["content"] == "hello"
        snap = get_public_snapshot()
        assert snap is not None
        assert snap["llm_calls"] == 1
        assert snap["total_tokens"] == 7
    finally:
        end_run(tok)
        await client.close()


@pytest.mark.asyncio
async def test_chat_invalid_json_raises_with_snippet():
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, content=b"not-json", headers={"content-type": "application/json"}
        )

    transport = httpx.MockTransport(handler)
    client = OpenAICompatibleLLMClient(
        model="m1",
        api_key="sk-test",
        base_url="http://example.test/v1",
        timeout=15,
    )
    client._client = httpx.AsyncClient(
        transport=transport,
        base_url="http://example.test/v1",
        headers={"Authorization": "Bearer sk-test"},
    )
    with pytest.raises(RuntimeError, match="invalid JSON"):
        await client.chat([{"role": "user", "content": "hi"}], stream=False)
    await client.close()
