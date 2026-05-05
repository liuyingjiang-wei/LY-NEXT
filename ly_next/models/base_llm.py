from abc import ABC, abstractmethod
from typing import Any


class BaseLLMClient(ABC):
    def __init__(
        self, model: str, api_key: str, base_url: str | None = None, timeout: int = 60, **kwargs
    ):
        self.model = model
        self.api_key = api_key
        self.base_url = base_url
        self.timeout = timeout
        self.extra_kwargs = kwargs

    @abstractmethod
    async def chat(
        self,
        messages: list[dict[str, Any]],
        temperature: float = 0.7,
        max_tokens: int = 2048,
        stream: bool = False,
        **kwargs,
    ):
        pass

    @abstractmethod
    async def chat_complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | None = None,
        **kwargs,
    ):
        pass

    @property
    @abstractmethod
    def provider_name(self) -> str:
        pass

    def to_dict(self) -> dict[str, Any]:
        return {"provider": self.provider_name, "model": self.model, "base_url": self.base_url}
