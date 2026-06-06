from __future__ import annotations

import re
from typing import Any

from ly_next.bridge.onebot11.manager import get_session, list_sessions
from ly_next.bridge.onebot11.napcat_actions import NAPCAT_ACTION_SET
from ly_next.bridge.onebot11.session import OneBotApiError, OneBotSession

_ACTION_NAME_RE = re.compile(r"^[A-Za-z_.][A-Za-z0-9_.]{0,127}$")


def normalize_action_name(action: str) -> str:
    name = str(action or "").strip()
    if not name or not _ACTION_NAME_RE.match(name):
        raise ValueError(f"无效的 action 名称: {action!r}")
    return name


def resolve_session(self_id: int | None) -> OneBotSession:
    sessions = list_sessions()
    if not sessions:
        raise RuntimeError("NapCat 未连接：请在 NapCat WebUI 配置反向 WebSocket 客户端")
    if self_id is not None:
        session = get_session(int(self_id))
        if session is None:
            raise RuntimeError(f"未找到 self_id={self_id} 的 NapCat 连接")
        return session
    if len(sessions) == 1:
        return sessions[0]
    ids = [s.self_id for s in sessions if s.self_id is not None]
    raise RuntimeError(f"当前有 {len(sessions)} 个 NapCat 连接，请指定 self_id（已连接: {ids}）")


async def call_onebot_action(
    action: str,
    params: dict[str, Any] | None = None,
    *,
    self_id: int | None = None,
    timeout: float | None = None,
    allow_unknown_action: bool = True,
) -> dict[str, Any]:
    name = normalize_action_name(action)
    if not allow_unknown_action and name not in NAPCAT_ACTION_SET:
        raise ValueError(f"action 不在目录中: {name}")
    session = resolve_session(self_id)
    kwargs: dict[str, Any] = {}
    if timeout is not None:
        kwargs["timeout"] = float(timeout)
    raw = await session.send_api_raw(name, params, **kwargs)
    return raw


async def call_onebot_action_data(
    action: str,
    params: dict[str, Any] | None = None,
    *,
    self_id: int | None = None,
    timeout: float | None = None,
) -> Any:
    raw = await call_onebot_action(
        action, params, self_id=self_id, timeout=timeout, allow_unknown_action=True
    )
    if raw.get("status") != "ok" and int(raw.get("retcode", -1)) not in (0, 1):
        wording = str(raw.get("wording") or raw.get("message") or "API failed")
        raise OneBotApiError(int(raw.get("retcode", -1)), wording, raw)
    return raw.get("data")
