import json
from collections.abc import AsyncIterator
from typing import Any

import httpx

from ly_next.core.http_url import ensure_http_base
from ly_next.models.base_llm import BaseLLMClient
from ly_next.models.openai_chat_body import attach_tools, build_openai_chat_completions_body
from ly_next.models.openai_compat_auth import (
    merge_optional_headers,
    openai_compat_auth_headers,
    require_remote_api_key,
)


def _normalize_chat_path(raw: str | None) -> str:
    p = (raw or "").strip() or "/chat/completions"
    if not p.startswith("/"):
        p = "/" + p
    return p


class OpenAICompatibleLLMClient(BaseLLMClient):
    """HTTP client for OpenAI-compatible Chat Completions APIs."""

    def __init__(
        self,
        model: str = "gpt-4o-mini",
        api_key: str = "not-needed",
        base_url: str = "https://api.openai.com/v1",
        timeout: int | float = 60,
        *,
        auth_mode: str | None = None,
        auth_header_name: str | None = None,
        headers: dict[str, Any] | None = None,
        path: str | None = None,
        **kwargs: Any,
    ):
        bu = ensure_http_base(base_url, default="https://api.openai.com/v1")
        to_int = int(timeout) if isinstance(timeout, (int, float)) else 60
        super().__init__(model, api_key, bu, to_int, **kwargs)
        self._timeout_sec = float(timeout) if isinstance(timeout, (int, float)) else 60.0
        am = auth_mode if auth_mode is not None else kwargs.get("authMode")
        self._auth_mode = (str(am).strip() if am else "") or "bearer"
        ah = auth_header_name if auth_header_name is not None else kwargs.get("authHeaderName")
        self._auth_header_name = str(ah).strip() if ah else None
        self._extra_headers = dict(headers) if isinstance(headers, dict) else {}
        self._chat_path = _normalize_chat_path(path or kwargs.get("path"))
        self._cfg: dict[str, Any] = dict(kwargs)
        self._cfg["model"] = model
        self._cfg["base_url"] = bu
        self._cfg["timeout"] = timeout
        self._cfg["auth_mode"] = self._auth_mode
        self._cfg["auth_header_name"] = self._auth_header_name
        if headers:
            self._cfg["headers"] = headers
        tf = self._cfg.get("token_field") or self._cfg.get("tokenField")
        if tf:
            self._cfg["token_field"] = str(tf).strip().lower()
        self._client: httpx.AsyncClient | None = None

    def _merged_runtime_config(self) -> dict[str, Any]:
        base = dict(self._cfg)
        base["model"] = self.model
        base["base_url"] = self.base_url
        return base

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            auth = openai_compat_auth_headers(
                self.api_key,
                auth_mode=self._auth_mode,
                auth_header_name=self._auth_header_name,
            )
            h = merge_optional_headers(auth, self._extra_headers)
            h.setdefault("Content-Type", "application/json")
            self._client = httpx.AsyncClient(
                base_url=self.base_url.rstrip("/"),
                headers=h,
                timeout=httpx.Timeout(self._timeout_sec),
            )
        return self._client

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    def _raise_with_body(self, response: httpx.Response) -> None:
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError:
            try:
                text = response.text
            except Exception:
                text = ""
            msg = (
                f"Client error '{response.status_code} {response.reason_phrase}' "
                f"for url '{response.request.url!s}'"
            )
            if text:
                msg = f"{msg}\n{text[:4000]}"
            raise RuntimeError(msg) from None

    async def chat(
        self,
        messages: list[dict[str, Any]],
        temperature: float = 0.7,
        max_tokens: int = 2048,
        stream: bool = False,
        **kwargs: Any,
    ):
        require_remote_api_key(
            self.api_key,
            self.base_url,
            auth_mode=self._auth_mode,
            auth_header_name=self._auth_header_name,
        )
        client = await self._get_client()
        cfg = self._merged_runtime_config()
        overrides: dict[str, Any] = {
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": stream,
        }
        overrides.update({k: v for k, v in kwargs.items() if v is not None})
        body = build_openai_chat_completions_body(
            messages,
            cfg,
            overrides,
            default_model=self.model,
        )
        if stream:
            return self._stream_chat(body)

        response = await client.post(self._chat_path, json=body)
        self._raise_with_body(response)
        return response.json()

    async def _stream_chat(self, body: dict[str, Any]):
        body["stream"] = True
        client = await self._get_client()
        async with client.stream("POST", self._chat_path, json=body) as response:
            self._raise_with_body(response)
            async for ev in self._stream_response(response):
                yield ev

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
        **kwargs: Any,
    ):
        require_remote_api_key(
            self.api_key,
            self.base_url,
            auth_mode=self._auth_mode,
            auth_header_name=self._auth_header_name,
        )
        client = await self._get_client()
        cfg = self._merged_runtime_config()
        overrides = {k: v for k, v in kwargs.items() if v is not None}
        body = build_openai_chat_completions_body(
            messages,
            cfg,
            overrides,
            default_model=self.model,
        )
        body.pop("stream", None)
        pt = overrides.get("parallel_tool_calls")
        if pt is None:
            pt = cfg.get("parallel_tool_calls")
        if pt is None:
            pt = cfg.get("parallelToolCalls")
        attach_tools(body, tools, tool_choice, pt if isinstance(pt, bool) else None)
        response = await client.post(self._chat_path, json=body)
        self._raise_with_body(response)
        return response.json()

    @property
    def provider_name(self) -> str:
        p = self._cfg.get("provider")
        if isinstance(p, str) and p.strip():
            return p.strip().lower()
        return "openai_compat"


def openai_compat_from_provider_block(cfg: dict[str, Any]) -> OpenAICompatibleLLMClient:
    c = dict(cfg)
    model = str(c.get("model") or "gpt-4o-mini")
    api_key = str(c.get("api_key") or "")
    base_url = str(c.get("base_url") or c.get("baseUrl") or "https://api.openai.com/v1")
    timeout = c.get("timeout", 60)
    auth_mode = c.get("auth_mode") or c.get("authMode")
    auth_header_name = c.get("auth_header_name") or c.get("authHeaderName")
    headers = c.get("headers") if isinstance(c.get("headers"), dict) else None
    path = c.get("path")
    rest = {
        k: v
        for k, v in c.items()
        if k
        not in (
            "model",
            "api_key",
            "base_url",
            "baseUrl",
            "timeout",
            "auth_mode",
            "authMode",
            "auth_header_name",
            "authHeaderName",
            "headers",
            "path",
        )
    }
    return OpenAICompatibleLLMClient(
        model=model,
        api_key=api_key,
        base_url=base_url,
        timeout=int(timeout) if timeout is not None else 60,
        auth_mode=str(auth_mode) if auth_mode else None,
        auth_header_name=str(auth_header_name) if auth_header_name else None,
        headers=headers,
        path=str(path) if path else None,
        **rest,
    )
