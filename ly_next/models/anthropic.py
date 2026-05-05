import json
from collections.abc import AsyncIterator
from typing import Any

import httpx

from ly_next.core.http_url import ensure_http_base
from ly_next.models.base_llm import BaseLLMClient


class AnthropicLLMClient(BaseLLMClient):
    def __init__(
        self,
        model: str = "claude-3-5-haiku-20241022",
        api_key: str = "",
        base_url: str = "https://api.anthropic.com",
        timeout: int = 60,
        **kwargs,
    ):
        bu = ensure_http_base(base_url, default="https://api.anthropic.com")
        super().__init__(model, api_key, bu, timeout, **kwargs)
        self._client: httpx.AsyncClient | None = None
        self.api_version = kwargs.get("api_version", "2023-06-01")

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.base_url.rstrip("/"),
                headers={
                    "x-api-key": self.api_key,
                    "anthropic-version": self.api_version,
                    "Content-Type": "application/json",
                },
                timeout=self.timeout,
            )
        return self._client

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    async def chat(
        self,
        messages: list[dict[str, Any]],
        temperature: float = 0.7,
        max_tokens: int = 2048,
        stream: bool = False,
        **kwargs,
    ):
        client = await self._get_client()
        anthropic_messages = [
            {
                "role": "user" if m.get("role") != "system" else "user",
                "content": m.get("content", ""),
            }
            for m in messages
            if m.get("role") != "system"
        ]
        body = {
            "model": self.model,
            "messages": anthropic_messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": stream,
        }
        body.update({k: v for k, v in kwargs.items() if v is not None})
        response = await client.post("/v1/messages", json=body)
        response.raise_for_status()
        if stream:
            return self._stream_response(response)
        return response.json()

    async def _stream_response(self, response: httpx.Response) -> AsyncIterator[dict[str, Any]]:
        async for line in response.aiter_lines():
            if line.startswith("data: "):
                data = line[6:]
                if data.strip() == "[DONE]":
                    break
                try:
                    yield json.loads(data)
                except json.JSONDecodeError:
                    continue

    async def chat_complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | None = None,
        **kwargs,
    ):
        client = await self._get_client()
        anthropic_messages = [
            {
                "role": "user" if m.get("role") != "system" else "user",
                "content": m.get("content", ""),
            }
            for m in messages
            if m.get("role") != "system"
        ]
        body = {
            "model": self.model,
            "messages": anthropic_messages,
            "temperature": kwargs.get("temperature", 0.7),
            "max_tokens": kwargs.get("max_tokens", 2048),
        }
        if tools:
            body["tools"] = tools
        body.update(
            {
                k: v
                for k, v in kwargs.items()
                if v is not None and k not in ["temperature", "max_tokens"]
            }
        )
        response = await client.post("/v1/messages", json=body)
        response.raise_for_status()
        return response.json()

    @property
    def provider_name(self) -> str:
        return "anthropic"
