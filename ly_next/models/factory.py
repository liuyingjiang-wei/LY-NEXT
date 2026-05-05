from collections.abc import Callable
from typing import Any

from ly_next.core.config import config
from ly_next.core.http_url import ensure_http_base
from ly_next.core.logger import get_logger
from ly_next.models.base_llm import BaseLLMClient
from ly_next.models.openai_compat import openai_compat_from_provider_block

logger = get_logger(__name__)


class LLMFactory:
    _providers: dict[str, Callable[..., BaseLLMClient]] = {}
    _clients: dict[str, BaseLLMClient] = {}

    @classmethod
    def register_provider(cls, name: str, factory_fn: Callable[..., BaseLLMClient]) -> None:
        cls._providers[name.lower()] = factory_fn
        logger.info(f"Registered LLM provider: {name}")

    @classmethod
    def list_providers(cls) -> list[str]:
        return list(cls._providers.keys())

    @classmethod
    def has_provider(cls, name: str) -> bool:
        return name.lower() in cls._providers

    @classmethod
    def _resolve_provider(cls, input_config: dict[str, Any]) -> str | None:
        for candidate in [
            input_config.get("provider"),
            input_config.get("model"),
            input_config.get("llm"),
            input_config.get("profile"),
            input_config.get("default_provider"),
            config.get("llm.default_provider"),
        ]:
            key = candidate.strip().lower() if candidate else None
            if key and cls.has_provider(key):
                return key
        return None

    @classmethod
    def _get_provider_config(cls, provider: str) -> dict[str, Any]:
        key = provider.lower()
        config_key = f"{key}_llm"
        provider_config = config.get(config_key, {})
        if isinstance(provider_config, dict) and provider_config:
            return provider_config
        return config.get(f"{key}_llm", {})

    @classmethod
    def create_client(cls, **kwargs) -> BaseLLMClient:
        provider = cls._resolve_provider(kwargs)
        if not provider:
            raise ValueError(f"No valid LLM provider found. Available: {cls.list_providers()}")
        provider_config = cls._get_provider_config(provider)
        merged = {**provider_config, **kwargs, "provider": provider}
        factory = cls._providers.get(provider)
        if not factory:
            raise ValueError(f"Provider factory not found: {provider}")
        try:
            return factory(merged)
        except Exception as e:
            logger.error(f"Failed to create LLM client: {e}")
            raise

    @classmethod
    def get_client(cls, name: str = "default", **kwargs) -> BaseLLMClient:
        cache_key = f"{name}:{kwargs.get('provider', 'default')}"
        if cache_key not in cls._clients:
            cls._clients[cache_key] = cls.create_client(**kwargs)
        return cls._clients[cache_key]

    @classmethod
    def clear_cache(cls) -> None:
        cls._clients.clear()


def _register_builtin_providers() -> None:
    from ly_next.models.anthropic import AnthropicLLMClient
    from ly_next.models.ollama import OllamaLLMClient

    LLMFactory.register_provider("openai", lambda cfg: openai_compat_from_provider_block(cfg))
    LLMFactory.register_provider(
        "openai_compat", lambda cfg: openai_compat_from_provider_block(cfg)
    )
    LLMFactory.register_provider(
        "anthropic",
        lambda cfg: AnthropicLLMClient(
            model=cfg.get("model", "claude-3-5-haiku-20241022"),
            api_key=cfg.get("api_key", ""),
            base_url=ensure_http_base(cfg.get("base_url"), default="https://api.anthropic.com"),
            timeout=cfg.get("timeout", 60),
        ),
    )
    LLMFactory.register_provider(
        "ollama",
        lambda cfg: OllamaLLMClient(
            model=cfg.get("model", "qwen2.5"),
            api_key=cfg.get("api_key", "not-needed"),
            base_url=ensure_http_base(cfg.get("base_url"), default="http://localhost:11434"),
            timeout=cfg.get("timeout", 120),
        ),
    )


_register_builtin_providers()
