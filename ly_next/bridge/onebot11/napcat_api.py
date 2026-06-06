from __future__ import annotations

import keyword
import re
from typing import Any

from ly_next.bridge.onebot11.call import call_onebot_action, call_onebot_action_data
from ly_next.bridge.onebot11.napcat_actions import NAPCAT_ACTION_NAMES

_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def is_bindable_action_name(action: str) -> bool:
    return bool(_IDENT.match(action)) and not keyword.iskeyword(action)


def _merge_params(params: dict[str, Any] | None, kwargs: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    if params:
        out.update(params)
    if kwargs:
        out.update(kwargs)
    return out


class NapCatV11:
    def __init__(
        self,
        *,
        self_id: int | None = None,
        timeout: float | None = None,
    ) -> None:
        self._self_id = self_id
        self._timeout = timeout

    async def invoke(
        self,
        action: str,
        params: dict[str, Any] | None = None,
        /,
        **kwargs: Any,
    ) -> Any:
        merged = _merge_params(params, kwargs)
        return await call_onebot_action_data(
            action,
            merged,
            self_id=self._self_id,
            timeout=self._timeout,
        )

    async def invoke_raw(
        self,
        action: str,
        params: dict[str, Any] | None = None,
        /,
        **kwargs: Any,
    ) -> dict[str, Any]:
        merged = _merge_params(params, kwargs)
        return await call_onebot_action(
            action,
            merged,
            self_id=self._self_id,
            timeout=self._timeout,
        )

    async def send_private_text(
        self,
        user_id: int | str,
        message: str,
        *,
        auto_escape: bool = True,
        **extra: Any,
    ) -> Any:
        return await self.send_private_msg(
            user_id=user_id,
            message=message,
            auto_escape=auto_escape,
            **extra,
        )

    async def send_group_text(
        self,
        group_id: int | str,
        message: str,
        *,
        auto_escape: bool = True,
        **extra: Any,
    ) -> Any:
        return await self.send_group_msg(
            group_id=group_id,
            message=message,
            auto_escape=auto_escape,
            **extra,
        )


def _make_bound_method(action: str):
    async def method(
        self: NapCatV11,
        params: dict[str, Any] | None = None,
        /,
        **kwargs: Any,
    ) -> Any:
        return await self.invoke(action, params, **kwargs)

    method.__name__ = action
    method.__qualname__ = f"NapCatV11.{action}"
    return method


for _action in NAPCAT_ACTION_NAMES:
    if is_bindable_action_name(_action):
        setattr(NapCatV11, _action, _make_bound_method(_action))


def napcat(*, self_id: int | None = None, timeout: float | None = None) -> NapCatV11:
    return NapCatV11(self_id=self_id, timeout=timeout)
