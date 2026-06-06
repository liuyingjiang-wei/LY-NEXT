"""Configurable middleware hooks for the chat pipeline."""

from __future__ import annotations

import importlib
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from ly_next.core.config import config
from ly_next.core.logger import get_logger

logger = get_logger(__name__)


@runtime_checkable
class ChatMiddleware(Protocol):
    async def before_prepare(
        self,
        messages: list[dict[str, Any]],
        ctx: dict[str, Any],
    ) -> list[dict[str, Any]]: ...

    async def after_prepare(
        self,
        messages: list[dict[str, Any]],
        ctx: dict[str, Any],
    ) -> list[dict[str, Any]]: ...

    async def after_agent(
        self,
        reply: str,
        ctx: dict[str, Any],
    ) -> str: ...


class _NoOpMiddleware:
    async def before_prepare(
        self, messages: list[dict[str, Any]], ctx: dict[str, Any]
    ) -> list[dict[str, Any]]:
        return messages

    async def after_prepare(
        self, messages: list[dict[str, Any]], ctx: dict[str, Any]
    ) -> list[dict[str, Any]]:
        return messages

    async def after_agent(self, reply: str, ctx: dict[str, Any]) -> str:
        return reply


def _load_middleware(qualified: str) -> ChatMiddleware:
    if "." not in qualified:
        raise ImportError(f"Middleware must be a qualified module path: {qualified!r}")
    module_path, _, attr = qualified.rpartition(".")
    module = importlib.import_module(module_path)
    obj = getattr(module, attr)
    return obj() if callable(obj) and not isinstance(obj, ChatMiddleware) else obj


@dataclass
class ChatMiddlewareChain:
    middlewares: list[ChatMiddleware] = field(default_factory=list)

    @classmethod
    def from_config(cls) -> ChatMiddlewareChain:
        raw = config.get("agent.chat_pipeline.middleware") or []
        if not isinstance(raw, list):
            return cls()
        loaded: list[ChatMiddleware] = []
        for item in raw:
            name = str(item).strip()
            if not name:
                continue
            try:
                mw = _load_middleware(name)
                loaded.append(mw)
                logger.info("[ChatMiddleware] loaded %s", name)
            except Exception as e:
                logger.error("[ChatMiddleware] failed to load %s: %s", name, e)
        return cls(middlewares=loaded)

    async def before_prepare(
        self, messages: list[dict[str, Any]], ctx: dict[str, Any]
    ) -> list[dict[str, Any]]:
        out = list(messages)
        for mw in self.middlewares:
            hook = getattr(mw, "before_prepare", None)
            if hook is None:
                continue
            out = await hook(out, ctx)
        return out

    async def after_prepare(
        self, messages: list[dict[str, Any]], ctx: dict[str, Any]
    ) -> list[dict[str, Any]]:
        out = list(messages)
        for mw in self.middlewares:
            hook = getattr(mw, "after_prepare", None)
            if hook is None:
                continue
            out = await hook(out, ctx)
        return out

    async def after_agent(self, reply: str, ctx: dict[str, Any]) -> str:
        out = reply
        for mw in self.middlewares:
            hook = getattr(mw, "after_agent", None)
            if hook is None:
                continue
            out = await hook(out, ctx)
        return out


_default_chain: ChatMiddlewareChain | None = None


def get_chat_middleware_chain() -> ChatMiddlewareChain:
    global _default_chain
    if _default_chain is None:
        _default_chain = ChatMiddlewareChain.from_config()
    return _default_chain


def reset_chat_middleware_chain() -> None:
    global _default_chain
    _default_chain = None
