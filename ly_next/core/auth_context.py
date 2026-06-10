"""Request-scoped principal for audit and handlers."""

from __future__ import annotations

from contextvars import ContextVar

from ly_next.core.auth_principal import Principal

_current_principal: ContextVar[Principal | None] = ContextVar("ly_auth_principal", default=None)


def set_principal(principal: Principal | None):
    return _current_principal.set(principal)


def reset_principal(token) -> None:
    _current_principal.reset(token)


def get_principal() -> Principal | None:
    return _current_principal.get()


bind_principal = set_principal
release_principal = reset_principal
