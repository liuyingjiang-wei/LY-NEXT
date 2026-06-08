import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from ly_next.agent.llm_text import (
    content_from_stream_delta,
    reasoning_from_stream_delta,
    text_from_chat_response,
    text_from_stream_delta,
)
from ly_next.core.config import config
from ly_next.core.logger import get_logger
from ly_next.messaging.models import MixedMessage
from ly_next.models.base_llm import BaseLLMClient
from ly_next.models.factory import LLMFactory
from ly_next.models.registry import ModelRegistry

logger = get_logger(__name__)


def _stream_tokens_enabled() -> bool:
    if config.get("agent.stream_tokens") is not None:
        return bool(config.get("agent.stream_tokens"))
    return bool(config.get("agent.stream_output", True))


@dataclass
class AgentDeps:
    llm_client: BaseLLMClient | None = None
    provider: str = "openai"
    model: str | None = None
    max_tools: int = 40
    tool_registry: Any | None = None
    max_steps: int = 6
    temperature: float = 0.7
    max_tokens: int = 2048
    verbose: bool = False
    reasoning_mode: str = "react"
    stream_callback: Callable[[dict[str, Any]], Awaitable[None]] | None = None
    _custom_llm_call: Callable[..., Awaitable[str]] | None = field(default=None, repr=False)
    scratchpad_max_chars: int = 12000
    scratchpad_compress_enabled: bool = True
    scratchpad_compress_target_chars: int = 4500
    scratchpad_compress_max_tokens: int = 1024
    loop_max_repeat_same_tool: int = 3
    loop_max_consecutive_tool_failures: int = 4
    tool_allow_tools: list[str] | None = None
    tool_deny_tools: list[str] = field(default_factory=list)
    tool_allow_categories: list[str] | None = None
    tool_max_tier: str = "network"
    native_tool_calls: bool = True
    tool_call_mode: str = "auto"
    stop_event: asyncio.Event | None = None
    thread_id: str | None = None
    collected_tool_results: list[dict[str, Any]] = field(default_factory=list)
    last_mixed_message: MixedMessage | None = None
    _filtered_tools_cache: tuple[list[Any], list[str]] | None = field(default=None, repr=False)
    _openai_tools_cache: tuple[list[dict[str, Any]], list[str], list[Any]] | None = field(
        default=None, repr=False
    )

    def __post_init__(self):
        if self.llm_client is None:
            try:
                kw: dict[str, Any] = {}
                if self.model:
                    kw["model"] = self.model
                ModelRegistry.ensure_loaded()
                name = str(self.provider or "").strip()
                entry = ModelRegistry.get_entry(name) if name else None
                if entry:
                    kw = ModelRegistry.build_client_kwargs(
                        entry["name"], model_override=self.model
                    )
                elif name:
                    kw["provider"] = name
                self.llm_client = LLMFactory.get_client(**kw)
            except Exception as e:
                logger.warning("Failed to create default LLM client: %s", e)

    @property
    def use_tools(self) -> bool:
        return self.tool_registry is not None and len(self.tool_registry.list_tools()) > 0

    async def call_llm(self, prompt: str) -> str:
        if self._custom_llm_call:
            return await self._custom_llm_call(prompt)

        if self.llm_client is None:
            raise RuntimeError("No LLM client configured")

        messages = [{"role": "user", "content": prompt}]

        if self.verbose:
            logger.debug(f"[agent] Calling LLM with prompt length: {len(prompt)}")

        response = await self.llm_client.chat(
            messages=messages,
            temperature=self.temperature,
            max_tokens=self.max_tokens,
            stream=False,
        )

        if isinstance(response, dict):
            text = text_from_chat_response(response)
            if text:
                return text

        return str(response)

    async def chat_with_tools(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        *,
        tool_choice: str | None = None,
    ) -> dict[str, Any]:
        if self._custom_llm_call:
            raise RuntimeError("Tool calling requires a standard LLM client")

        if self.llm_client is None:
            raise RuntimeError("No LLM client configured")

        if self.verbose:
            logger.debug(
                "[agent] chat_with_tools messages=%s tools=%s", len(messages), len(tools or [])
            )

        return await self.llm_client.chat_complete(
            messages=messages,
            tools=tools,
            tool_choice=tool_choice,
            temperature=self.temperature,
            max_tokens=self.max_tokens,
        )

    async def _iter_response_stream(self, response):
        async for chunk in response:
            if self.stop_event and self.stop_event.is_set():
                break
            content = ""
            reasoning = ""
            if isinstance(chunk, dict):
                choices = chunk.get("choices") or [{}]
                delta = choices[0].get("delta", {}) if choices else {}
                if isinstance(delta, dict):
                    content = content_from_stream_delta(delta)
                    reasoning = reasoning_from_stream_delta(delta)
            else:
                content = str(chunk)
            if reasoning:
                if self.stream_callback:
                    await self.stream_callback({"content": reasoning, "kind": "think", "done": False})
                yield {"type": "think", "content": reasoning}
            if content:
                if self.stream_callback:
                    await self.stream_callback({"content": content, "kind": "chunk", "done": False})
                yield {"type": "chunk", "content": content}
        if self.stream_callback:
            await self.stream_callback({"content": "", "done": True})

    async def iter_messages_stream(self, messages: list[dict[str, Any]]):
        if self._custom_llm_call:
            text = await self._custom_llm_call(
                "\n".join(f"{m.get('role')}: {m.get('content')}" for m in messages)
            )
            if text:
                yield {"type": "chunk", "content": text}
            return

        if self.llm_client is None:
            raise RuntimeError("No LLM client configured")

        response = await self.llm_client.chat(
            messages=messages,
            temperature=self.temperature,
            max_tokens=self.max_tokens,
            stream=True,
        )
        async for piece in self._iter_response_stream(response):
            yield piece

    async def iter_chat_with_tools(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        *,
        tool_choice: str | None = None,
    ):
        if self._custom_llm_call:
            raise RuntimeError("Tool calling requires a standard LLM client")
        if self.llm_client is None:
            raise RuntimeError("No LLM client configured")

        stream_fn = getattr(self.llm_client, "stream_chat_complete", None)
        if _stream_tokens_enabled() and callable(stream_fn):
            async for item in stream_fn(
                messages=messages,
                tools=tools,
                tool_choice=tool_choice,
                temperature=self.temperature,
                max_tokens=self.max_tokens,
            ):
                if self.stop_event and self.stop_event.is_set():
                    break
                kind = item.get("kind")
                if kind == "reasoning":
                    text = str(item.get("text") or "")
                    if text:
                        if self.stream_callback:
                            await self.stream_callback({"content": text, "kind": "think", "done": False})
                        yield {"type": "think_chunk", "content": text}
                elif kind == "content":
                    text = str(item.get("text") or "")
                    if text:
                        if self.stream_callback:
                            await self.stream_callback({"content": text, "done": False})
                        yield {"type": "chunk", "content": text}
                elif kind == "done":
                    if self.stream_callback:
                        await self.stream_callback({"content": "", "done": True})
                    yield {"type": "completion", "response": item.get("response") or {}}
            return

        resp = await self.chat_with_tools(
            messages, tools, tool_choice=tool_choice
        )
        yield {"type": "completion", "response": resp}

    async def call_llm_limited(
        self, prompt: str, *, max_tokens: int, temperature: float = 0.25
    ) -> str:
        if self._custom_llm_call:
            return await self._custom_llm_call(prompt)

        if self.llm_client is None:
            raise RuntimeError("No LLM client configured")

        messages = [{"role": "user", "content": prompt}]
        if self.verbose:
            logger.debug("[agent] LLM limited call max_tokens=%s", max_tokens)

        response = await self.llm_client.chat(
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            stream=False,
        )

        if isinstance(response, dict):
            text = text_from_chat_response(response)
            if text:
                return text

        return str(response)

    async def iter_llm_stream(self, prompt: str):
        if self.llm_client is None:
            raise RuntimeError("No LLM client configured")

        messages = [{"role": "user", "content": prompt}]
        async for piece in self.iter_messages_stream(messages):
            if isinstance(piece, dict):
                if piece.get("type") == "chunk":
                    yield str(piece.get("content") or "")
            elif isinstance(piece, str):
                yield piece

    async def call_llm_stream(self, prompt: str) -> str:
        parts: list[str] = []
        async for chunk in self.iter_llm_stream(prompt):
            parts.append(chunk)
        return "".join(parts)


def create_agent_deps(
    provider: str | None = None,
    model: str | None = None,
    tools: Any | None = None,
    **kwargs,
) -> AgentDeps:
    policy = config.get("agent.tool_policy", {}) or {}
    if not isinstance(policy, dict):
        policy = {}

    allow_tools_raw = policy.get("allow_tools")
    if allow_tools_raw is None:
        tool_allow_tools: list[str] | None = None
    elif isinstance(allow_tools_raw, list):
        tool_allow_tools = [str(x).strip() for x in allow_tools_raw if str(x).strip()]
    else:
        tool_allow_tools = None

    deny_raw = policy.get("deny_tools") or []
    tool_deny_tools = (
        [str(x).strip() for x in deny_raw if isinstance(x, str) and str(x).strip()]
        if isinstance(deny_raw, list)
        else []
    )

    allow_cat_raw = policy.get("allow_categories")
    if allow_cat_raw is None:
        tool_allow_categories = None
    elif isinstance(allow_cat_raw, list):
        tool_allow_categories = [str(x).strip().lower() for x in allow_cat_raw if str(x).strip()]
        if not tool_allow_categories:
            tool_allow_categories = None
    else:
        tool_allow_categories = None

    tool_max_tier = str(policy.get("max_tier") or "network").strip().lower()

    native_tool_calls = bool(
        kwargs.get("native_tool_calls", config.get("agent.native_tool_calls", True))
    )
    tool_call_mode = (
        str(kwargs.get("tool_call_mode", config.get("agent.tool_call_mode", "auto")) or "auto")
        .strip()
        .lower()
    )
    if tool_call_mode not in ("auto", "native", "compat"):
        tool_call_mode = "auto"

    resolved_model = model if model is not None else kwargs.get("model")
    if resolved_model is not None:
        sm = str(resolved_model).strip()
        resolved_model = sm if sm else None

    sp = config.get("agent.scratchpad", {}) or {}
    if not isinstance(sp, dict):
        sp = {}
    lg = config.get("agent.loop_guard", {}) or {}
    if not isinstance(lg, dict):
        lg = {}

    resolved_provider = str(provider).strip() if provider else ""
    if not resolved_provider:
        ModelRegistry.ensure_loaded()
        resolved_provider = ModelRegistry.default_name()

    return AgentDeps(
        provider=resolved_provider,
        model=resolved_model,
        max_steps=kwargs.get("max_steps", config.get("agent.max_steps", 6)),
        max_tools=kwargs.get("max_tools", config.get("agent.max_tools", 40)),
        temperature=kwargs.get("temperature", 0.7),
        max_tokens=kwargs.get("max_tokens", 2048),
        verbose=kwargs.get("verbose", config.get("agent.verbose", False)),
        reasoning_mode=kwargs.get("reasoning_mode", config.get("agent.reasoning_mode", "react")),
        tool_registry=tools,
        scratchpad_max_chars=max(2000, int(sp.get("max_chars", 12000) or 12000)),
        scratchpad_compress_enabled=bool(sp.get("compress_enabled", True)),
        scratchpad_compress_target_chars=max(
            800, int(sp.get("compress_target_chars", 4500) or 4500)
        ),
        scratchpad_compress_max_tokens=max(128, int(sp.get("compress_max_tokens", 1024) or 1024)),
        loop_max_repeat_same_tool=max(1, int(lg.get("max_repeat_same_tool", 3) or 3)),
        loop_max_consecutive_tool_failures=max(
            1, int(lg.get("max_consecutive_tool_failures", 4) or 4)
        ),
        tool_allow_tools=tool_allow_tools,
        tool_deny_tools=tool_deny_tools,
        tool_allow_categories=tool_allow_categories,
        tool_max_tier=tool_max_tier,
        native_tool_calls=native_tool_calls,
        tool_call_mode=tool_call_mode,
        stop_event=kwargs.get("stop_event"),
    )
