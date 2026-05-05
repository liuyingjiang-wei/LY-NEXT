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
    return AgentDeps(
        provider=provider or config.get("llm.default_provider", "openai"),
        max_steps=kwargs.get("max_steps", config.get("agent.max_steps", 6)),
        max_tools=kwargs.get("max_tools", config.get("agent.max_tools", 40)),
        temperature=kwargs.get("temperature", 0.7),
        max_tokens=kwargs.get("max_tokens", 2048),
        verbose=kwargs.get("verbose", config.get("agent.verbose", False)),
        reasoning_mode=kwargs.get("reasoning_mode", config.get("agent.reasoning_mode", "react")),
        tool_registry=tools,
    )
