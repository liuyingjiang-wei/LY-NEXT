import json
from collections.abc import AsyncIterator
from typing import Any

import httpx

from ly_next.core.http_url import ensure_http_base
from ly_next.models.base_llm import BaseLLMClient


class OllamaLLMClient(BaseLLMClient):
    def __init__(
        self,
        model: str = "qwen2.5",
        api_key: str = "not-needed",
        base_url: str = "http://localhost:11434",
        timeout: int = 120,
        **kwargs,
    ):
        bu = ensure_http_base(base_url, default="http://localhost:11434")
        super().__init__(model, api_key, bu, timeout, **kwargs)
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.base_url.rstrip("/"), timeout=self.timeout
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
        ollama_messages = [
            {"role": m.get("role", "user"), "content": m.get("content", "")} for m in messages
        ]
        body = {
            "model": self.model,
            "messages": ollama_messages,
            "stream": stream,
            "options": {"temperature": temperature, "num_predict": max_tokens},
        }
        body["options"].update({k: v for k, v in kwargs.items() if v is not None})
        response = await client.post("/api/chat", json=body)
        response.raise_for_status()
        if stream:
            return self._stream_response(response)
        return response.json()

    async def _stream_response(self, response: httpx.Response) -> AsyncIterator[dict[str, Any]]:
        async for line in response.aiter_lines():
            if line.strip():
                try:
                    yield json.loads(line)
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
        ollama_messages = [
            {"role": m.get("role", "user"), "content": m.get("content", "")} for m in messages
        ]
        body = {
            "model": self.model,
            "messages": ollama_messages,
            "stream": False,
            "options": {
                "temperature": kwargs.get("temperature", 0.7),
                "num_predict": kwargs.get("max_tokens", 2048),
            },
        }
        if tools:
            tools_prompt = "\n".join(
                [
                    f"- {t.get('function', t).get('name')}: {t.get('function', t).get('description', '')}"
                    for t in tools
                ]
            )
            body["messages"].insert(
                0,
                {
                    "role": "system",
                    "content": f"You have access to the following tools:\n{tools_prompt}",
                },
            )
        response = await client.post("/api/chat", json=body)
        response.raise_for_status()
        return response.json()

    @property
    def provider_name(self) -> str:
        return "ollama"

    async def list_models(self) -> list[str]:
        client = await self._get_client()
        response = await client.get("/api/tags")
        response.raise_for_status()
        return [m["name"] for m in response.json().get("models", [])]
