from collections.abc import Callable
from typing import Any

from ly_next.core.config import config
from ly_next.core.http_url import ensure_http_base
from ly_next.core.logger import get_logger
from ly_next.models.base_llm import BaseLLMClient
from ly_next.models.openai_compat import openai_compat_from_provider_block
from ly_next.models.registry import ModelRegistry

logger = get_logger(__name__)


class LLMFactory:
    """Format factories + named model registry (see ``ModelRegistry``)."""

    _formats: dict[str, Callable[..., BaseLLMClient]] = {}
    _clients: dict[str, BaseLLMClient] = {}

    @classmethod
    def register_format(cls, name: str, factory_fn: Callable[..., BaseLLMClient]) -> None:
        cls._formats[name.lower()] = factory_fn
        logger.info("Registered LLM format: %s", name)

    @classmethod
    def register_provider(cls, name: str, factory_fn: Callable[..., BaseLLMClient]) -> None:
        """Alias for plugins — same as ``register_format``."""
        cls.register_format(name, factory_fn)

    @classmethod
    def list_formats(cls) -> list[str]:
        return list(cls._formats.keys())

    @classmethod
    def list_providers(cls) -> list[str]:
        """Registered model names (registry) plus format ids for backward compat."""
        ModelRegistry.ensure_loaded()
        names = ModelRegistry.list_names()
        if names:
            return names
        return cls.list_formats()

    @classmethod
    def has_format(cls, name: str) -> bool:
        return name.lower() in cls._formats

    @classmethod
    def has_provider(cls, name: str) -> bool:
        key = name.lower().strip()
        ModelRegistry.ensure_loaded()
        if ModelRegistry.get_entry(key):
            return True
        return key in cls._formats

    @classmethod
    def _legacy_block(cls, format_name: str) -> dict[str, Any]:
        block = config.get(f"{format_name}_llm", {}) or {}
        return block if isinstance(block, dict) else {}

    @classmethod
    def _client_from_entry(cls, entry: dict[str, Any], **overrides: Any) -> BaseLLMClient:
        fmt = str(entry.get("format") or "openai").strip().lower()
        factory = cls._formats.get(fmt)
        if not factory:
            raise ValueError(f"Unknown LLM format: {fmt}. Available: {cls.list_formats()}")
        merged = {**entry, **{k: v for k, v in overrides.items() if v is not None}}
        merged["provider"] = fmt
        if overrides.get("model"):
            merged["model"] = overrides["model"]
        return factory(merged)

    @classmethod
    def create_client(cls, **kwargs: Any) -> BaseLLMClient:
        ModelRegistry.ensure_loaded()

        registry_name = kwargs.get("registry_name") or kwargs.get("model_name")
        provider_hint = kwargs.get("provider")

        for candidate in (registry_name, provider_hint):
            if not candidate:
                continue
            entry = ModelRegistry.get_entry(str(candidate).strip())
            if entry:
                return cls._client_from_entry(entry, **kwargs)

        fmt = str(provider_hint or config.get("llm.default_provider") or "openai").strip().lower()
        if fmt in cls._formats:
            block = cls._legacy_block(fmt)
            merged = {**block, **kwargs, "provider": fmt, "format": fmt}
            return cls._client_from_entry(
                {
                    "name": fmt,
                    "format": fmt,
                    "model": merged.get("model", ""),
                    "api_key": merged.get("api_key", ""),
                    "base_url": merged.get("base_url", ""),
                    **{k: merged[k] for k in ("auth_mode", "auth_header_name", "token_field", "model_aliases", "headers", "path") if k in merged},
                },
                **kwargs,
            )

        default = ModelRegistry.default_name()
        entry = ModelRegistry.get_entry(default)
        if entry:
            return cls._client_from_entry(entry, **kwargs)

        raise ValueError(
            f"No valid LLM model found. Register models in llm.models or configure legacy *_llm blocks. "
            f"Formats: {cls.list_formats()}"
        )

    @classmethod
    def get_client(cls, name: str = "default", **kwargs: Any) -> BaseLLMClient:
        registry_name = kwargs.get("registry_name") or kwargs.get("model_name")
        if not registry_name and kwargs.get("provider"):
            prov = str(kwargs["provider"]).strip()
            if ModelRegistry.get_entry(prov):
                kwargs = {**kwargs, "registry_name": prov}

        prov = str(kwargs.get("provider") or registry_name or "default")
        mod = str(kwargs.get("model") or "").strip()
        t_raw = kwargs.get("timeout")
        timeout_part = "" if t_raw is None else str(t_raw)
        cache_key = f"{name}:{prov}:{mod}:{timeout_part}"
        if cache_key not in cls._clients:
            cls._clients[cache_key] = cls.create_client(**kwargs)
        return cls._clients[cache_key]

    @classmethod
    def clear_cache(cls) -> None:
        cls._clients.clear()


def _register_builtin_formats() -> None:
    from ly_next.models.anthropic import AnthropicLLMClient
    from ly_next.models.ollama import OllamaLLMClient

    LLMFactory.register_format("openai", lambda cfg: openai_compat_from_provider_block(cfg))
    LLMFactory.register_format("openai_compat", lambda cfg: openai_compat_from_provider_block(cfg))
    LLMFactory.register_format(
        "anthropic",
        lambda cfg: AnthropicLLMClient(
            model=cfg.get("model", "claude-3-5-haiku-20241022"),
            api_key=cfg.get("api_key", ""),
            base_url=ensure_http_base(cfg.get("base_url"), default="https://api.anthropic.com"),
            timeout=int(cfg.get("timeout") or config.get("llm.request_timeout", 60) or 60),
        ),
    )
    LLMFactory.register_format(
        "ollama",
        lambda cfg: OllamaLLMClient(
            model=cfg.get("model", "qwen2.5"),
            api_key=cfg.get("api_key", "not-needed"),
            base_url=ensure_http_base(cfg.get("base_url"), default="http://localhost:11434"),
            timeout=int(cfg.get("timeout") or config.get("llm.request_timeout", 120) or 120),
        ),
    )


_register_builtin_formats()
