from __future__ import annotations

from ly_next.bridge.onebot11.session import OneBotSession

_sessions: dict[int, OneBotSession] = {}


def register_session(self_id: int, session: OneBotSession) -> None:
    _sessions[self_id] = session


async def unregister_session(session: OneBotSession) -> None:
    if session.self_id is not None and _sessions.get(session.self_id) is session:
        _sessions.pop(session.self_id, None)


def get_session(self_id: int) -> OneBotSession | None:
    return _sessions.get(self_id)


def list_sessions() -> list[OneBotSession]:
    return list(_sessions.values())
