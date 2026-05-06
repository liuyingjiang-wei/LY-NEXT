"""Agent Dependencies."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from ly_next.core.config import config
from ly_next.core.logger import get_logger
from ly_next.models.base_llm import BaseLLMClient
from ly_next.models.factory import LLMFactory

logger = get_logger(__name__)


@dataclass
class AgentDeps:
    """Agent Dependencies Container."""

    llm_client: BaseLLMClient | None = None
    provider: str = "openai"
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

    def __post_init__(self):
        if self.llm_client is None:
            try:
                self.llm_client = LLMFactory.get_client(provider=self.provider)
            except Exception as e:
                logger.warning(f"Failed to create default LLM client: {e}")

    @property
    def use_tools(self) -> bool:
        """Whether to use tools."""
        return self.tool_registry is not None and len(self.tool_registry.list_tools()) > 0

    async def call_llm(self, prompt: str) -> str:
        """Call LLM with prompt."""
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
            choices = response.get("choices", [])
            if choices:
                return choices[0].get("message", {}).get("content", "")

        return str(response)

    async def call_llm_limited(
        self, prompt: str, *, max_tokens: int, temperature: float = 0.25
    ) -> str:
        """Single-shot LLM call with an explicit token budget (summaries, guards)."""
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
            choices = response.get("choices", [])
            if choices:
                return choices[0].get("message", {}).get("content", "")

        return str(response)

    async def call_llm_stream(self, prompt: str) -> Awaitable[str]:
        """Call LLM with streaming."""
        if self.llm_client is None:
            raise RuntimeError("No LLM client configured")

        messages = [{"role": "user", "content": prompt}]

        if self.verbose:
            logger.debug("[agent] Streaming LLM call")

        response = await self.llm_client.chat(
            messages=messages,
            temperature=self.temperature,
            max_tokens=self.max_tokens,
            stream=True,
        )

        full_response = ""
        async for chunk in response:
            content = ""
            if isinstance(chunk, dict):
                delta = chunk.get("choices", [{}])[0].get("delta", {})
                content = delta.get("content", "")
            else:
                content = str(chunk)

            full_response += content

            if self.stream_callback:
                await self.stream_callback({"content": content, "done": False})

        if self.stream_callback:
            await self.stream_callback({"content": "", "done": True})

        return full_response


def create_agent_deps(
    provider: str | None = None,
    model: str | None = None,
    tools: Any | None = None,
    **kwargs,
) -> AgentDeps:
    """Create AgentDeps with config defaults."""
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
    else:
        tool_allow_categories = None

    tool_max_tier = str(policy.get("max_tier") or "network").strip().lower()

    sp = config.get("agent.scratchpad", {}) or {}
    if not isinstance(sp, dict):
        sp = {}
    lg = config.get("agent.loop_guard", {}) or {}
    if not isinstance(lg, dict):
        lg = {}

    return AgentDeps(
        provider=provider or config.get("llm.default_provider", "openai"),
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
    )
