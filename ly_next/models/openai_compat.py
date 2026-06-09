import asyncio
import contextlib
import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

import httpx

from ly_next.core.config import config
from ly_next.core.http_url import ensure_http_base
from ly_next.core.logger import get_logger
from ly_next.core.run_telemetry import (
    record_llm_call_failed,
    record_llm_call_start,
    record_llm_usage_from_chat_response,
)
from ly_next.models.base_llm import BaseLLMClient
from ly_next.models.openai_chat_body import attach_tools, build_openai_chat_completions_body
from ly_next.models.openai_compat_auth import (
    merge_optional_headers,
    openai_compat_auth_headers,
    require_remote_api_key,
)
from ly_next.models.stream_assemble import (
    accumulate_tool_call_delta,
    build_chat_completion_from_stream,
)
from ly_next.agent.llm_text import (
    content_from_stream_delta,
    reasoning_from_stream_delta,
    text_from_stream_delta,
)

logger = get_logger(__name__)


def _http_response_text(response: httpx.Response, limit: int = 500) -> str:
    with contextlib.suppress(Exception):
        return (response.text or "")[:limit]
    return ""


def _error_recovery_cfg() -> dict[str, Any]:
    raw = config.get("agent.error_recovery", {})
    return raw if isinstance(raw, dict) else {}


def _retry_on_timeout(rec: dict[str, Any]) -> bool:
    return bool(rec.get("retry_on_timeout", False))


def _retry_status_codes(rec: dict[str, Any]) -> set[int]:
    raw = rec.get("retry_status_codes") or rec.get("retry_on_status") or [429, 502, 503, 504]
    if not isinstance(raw, list):
        return {429, 502, 503, 504}
    out: set[int] = set()
    for x in raw:
        try:
            out.add(int(x))
        except (TypeError, ValueError):
            continue
    return out or {429, 502, 503, 504}


async def _recovery_sleep(attempt: int, base_delay: float) -> None:
    await asyncio.sleep(min(12.0, base_delay * (2**attempt)))


def _normalize_chat_path(raw: str | None) -> str:
    p = (raw or "").strip() or "/chat/completions"
    if not p.startswith("/"):
        p = "/" + p
    return p


def _collect_model_aliases(*sources: Any) -> dict[str, str]:
    out: dict[str, str] = {}
    for src in sources:
        if not isinstance(src, dict):
            continue
        raw = src.get("model_aliases") or src.get("modelAliases")
        if not isinstance(raw, dict):
            continue
        for k, v in raw.items():
            if not isinstance(k, str) or not isinstance(v, str):
                continue
            ks, vs = k.strip(), v.strip()
            if ks and vs:
                out[ks] = vs
    return out


@dataclass(frozen=True, slots=True)
class _CompatPostLog:
    path: str
    model: str
    base_url: str
    timeout_sec: float

    def retry_http_status(self, status: int, attempt_idx: int, retry_cap: int) -> None:
        logger.warning(
            "[openai_compat] HTTP %s retry %s/%s path=%s model=%s base_url=%s",
            status,
            attempt_idx + 1,
            retry_cap,
            self.path,
            self.model,
            self.base_url,
        )

    def retry_timeout(self, attempt_idx: int, retry_cap: int, exc: BaseException) -> None:
        logger.warning(
            "[openai_compat] timeout retry %s/%s path=%s model=%s read_timeout_sec=%s error=%s: %s",
            attempt_idx + 1,
            retry_cap,
            self.path,
            self.model,
            self.timeout_sec,
            type(exc).__name__,
            exc,
        )

    def final_timeout(self, attempt_idx: int, exc: BaseException) -> None:
        logger.error(
            "[openai_compat] timeout exhausted path=%s model=%s base_url=%s "
            "read_timeout_sec=%s attempts=%s error=%s: %s",
            self.path,
            self.model,
            self.base_url,
            self.timeout_sec,
            attempt_idx + 1,
            type(exc).__name__,
            exc,
        )

    def retry_transport(self, attempt_idx: int, retry_cap: int, exc: BaseException) -> None:
        logger.warning(
            "[openai_compat] transport retry %s/%s path=%s model=%s error=%s: %s",
            attempt_idx + 1,
            retry_cap,
            self.path,
            self.model,
            type(exc).__name__,
            exc,
        )

    def final_transport(self, attempt_idx: int, exc: BaseException) -> None:
        logger.error(
            "[openai_compat] transport failed path=%s model=%s base_url=%s "
            "timeout_sec=%s attempts=%s error=%s: %s",
            self.path,
            self.model,
            self.base_url,
            self.timeout_sec,
            attempt_idx + 1,
            type(exc).__name__,
            exc,
        )


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

    def _apply_model_aliases(self, body: dict[str, Any]) -> None:
        m_raw = body.get("model")
        if not isinstance(m_raw, str):
            return
        m = m_raw.strip()
        if not m:
            return

        block = config.get("openai_compat_llm") or {}
        aliases = _collect_model_aliases(block if isinstance(block, dict) else {}, self._cfg)
        rep = aliases.get(m)
        if rep and rep != m:
            logger.info("[openai_compat] model_aliases: %s -> %s", m, rep)
            body["model"] = rep

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
            read_timeout = self._timeout_sec
            connect_timeout = min(10.0, read_timeout)
            self._client = httpx.AsyncClient(
                base_url=self.base_url.rstrip("/"),
                headers=h,
                timeout=httpx.Timeout(
                    connect=connect_timeout,
                    read=read_timeout,
                    write=min(30.0, read_timeout),
                    pool=5.0,
                ),
                limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
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

    async def _post_chat_completions_json(
        self, client: httpx.AsyncClient, body: dict[str, Any]
    ) -> dict[str, Any]:
        rec = _error_recovery_cfg()
        enabled = bool(rec.get("enabled", False))
        retries = max(0, int(rec.get("max_retries", 2) or 0)) if enabled else 0
        codes = _retry_status_codes(rec) if enabled else set()
        base_delay = max(0.05, float(rec.get("backoff_base_seconds", 0.8) or 0.8))

        log_ctx = _CompatPostLog(
            path=self._chat_path,
            model=str(body.get("model") or self.model or ""),
            base_url=self.base_url,
            timeout_sec=self._timeout_sec,
        )
        msgs = body.get("messages")
        record_llm_call_start(
            model=log_ctx.model,
            provider=self.provider_name,
            messages_count=len(msgs) if isinstance(msgs, list) else None,
            messages=msgs if isinstance(msgs, list) else None,
        )

        for attempt in range(retries + 1):
            try:
                response = await client.post(log_ctx.path, json=body)
                if enabled and response.status_code in codes and attempt < retries:
                    log_ctx.retry_http_status(response.status_code, attempt, retries)
                    await _recovery_sleep(attempt, base_delay)
                    continue
                if response.status_code >= 400:
                    record_llm_call_failed(
                        model=log_ctx.model,
                        error=f"HTTP {response.status_code}: {_http_response_text(response)}",
                    )
                self._raise_with_body(response)
                try:
                    data = response.json()
                except json.JSONDecodeError as e:
                    record_llm_call_failed(
                        model=log_ctx.model,
                        error=f"invalid JSON status={response.status_code}: {e!s}",
                    )
                    snippet = _http_response_text(response, 800)
                    raise RuntimeError(
                        f"openai_compat: invalid JSON from {log_ctx.path} "
                        f"status={response.status_code}: {e!s}\n{snippet}"
                    ) from e
                record_llm_usage_from_chat_response(data)
                return data
            except httpx.TimeoutException as e:
                if enabled and _retry_on_timeout(rec) and attempt < retries:
                    log_ctx.retry_timeout(attempt, retries, e)
                    await _recovery_sleep(attempt, base_delay)
                    continue
                log_ctx.final_timeout(attempt, e)
                record_llm_call_failed(model=log_ctx.model, error=f"timeout: {e!s}")
                raise
            except httpx.RequestError as e:
                if enabled and attempt < retries:
                    log_ctx.retry_transport(attempt, retries, e)
                    await _recovery_sleep(attempt, base_delay)
                    continue
                log_ctx.final_transport(attempt, e)
                record_llm_call_failed(model=log_ctx.model, error=f"transport: {e!s}")
                raise

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
        self._apply_model_aliases(body)
        logger.debug(
            "[openai_compat] POST %s model=%s",
            self._chat_path,
            body.get("model"),
        )
        if stream:
            return self._stream_chat(body)

        return await self._post_chat_completions_json(client, body)

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
        self._apply_model_aliases(body)
        body.pop("stream", None)
        pt = overrides.get("parallel_tool_calls")
        if pt is None:
            pt = cfg.get("parallel_tool_calls")
        if pt is None:
            pt = cfg.get("parallelToolCalls")
        attach_tools(body, tools, tool_choice, pt if isinstance(pt, bool) else None)
        return await self._post_chat_completions_json(client, body)

    async def stream_chat_complete(
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
        cfg = self._merged_runtime_config()
        overrides = {k: v for k, v in kwargs.items() if v is not None}
        body = build_openai_chat_completions_body(
            messages,
            cfg,
            overrides,
            default_model=self.model,
        )
        self._apply_model_aliases(body)
        pt = overrides.get("parallel_tool_calls")
        if pt is None:
            pt = cfg.get("parallel_tool_calls")
        if pt is None:
            pt = cfg.get("parallelToolCalls")
        attach_tools(body, tools, tool_choice, pt if isinstance(pt, bool) else None)
        body["stream"] = True

        content_parts: list[str] = []
        reasoning_parts: list[str] = []
        tool_calls: dict[int, dict[str, Any]] = {}
        finish_reason: str | None = None
        usage: dict[str, Any] | None = None
        tool_phase = False
        model_name = str(body.get("model") or self.model)
        record_llm_call_start(model=model_name, messages_count=len(messages), provider=self.provider_name)

        try:
            async for chunk in self._stream_chat(body):
                if not isinstance(chunk, dict):
                    continue
                usage_raw = chunk.get("usage")
                if isinstance(usage_raw, dict):
                    usage = usage_raw
                choices = chunk.get("choices") or []
                if not choices or not isinstance(choices[0], dict):
                    continue
                choice0 = choices[0]
                fr = choice0.get("finish_reason")
                if isinstance(fr, str) and fr:
                    finish_reason = fr
                delta = choice0.get("delta")
                if not isinstance(delta, dict):
                    continue
                tc_deltas = delta.get("tool_calls")
                if tc_deltas:
                    for tc in tc_deltas:
                        if isinstance(tc, dict):
                            accumulate_tool_call_delta(tool_calls, tc)
                    if any(
                        str(row.get("function", {}).get("name") or "").strip()
                        or str(row.get("function", {}).get("arguments") or "").strip()
                        for row in tool_calls.values()
                    ):
                        tool_phase = True
                reasoning = reasoning_from_stream_delta(delta)
                if reasoning and not tool_phase:
                    reasoning_parts.append(reasoning)
                    yield {"kind": "reasoning", "text": reasoning}
                text = content_from_stream_delta(delta)
                if text and not tool_phase:
                    content_parts.append(text)
                    yield {"kind": "content", "text": text}
        except Exception as e:
            record_llm_call_failed(model=model_name, error=str(e))
            raise

        response = build_chat_completion_from_stream(
            content="".join(content_parts),
            tool_calls=tool_calls,
            finish_reason=finish_reason,
            usage=usage,
        )
        record_llm_usage_from_chat_response(response)
        yield {"kind": "done", "response": response}

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
    timeout = c.get("timeout")
    if timeout is None:
        timeout = config.get("llm.request_timeout", 120)
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
