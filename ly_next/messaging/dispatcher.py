from __future__ import annotations

from typing import Any, Protocol

from ly_next.core.config import config
from ly_next.core.logger import get_logger
from ly_next.messaging.models import MixedMessage, mixed_message_to_dict

logger = get_logger(__name__)


class _QQSender(Protocol):
    async def send_mixed_message(
        self,
        *,
        message_type: str,
        user_id: int | None,
        group_id: int | None,
        mixed: MixedMessage,
    ) -> None: ...


async def dispatch_mixed_message(
    channel: str,
    mixed: MixedMessage,
    *,
    qq_session: _QQSender | None = None,
    message_type: str = "private",
    user_id: int | None = None,
    group_id: int | None = None,
) -> dict[str, Any]:
    """
    Route a MixedMessage to the target channel.

    - qq: requires qq_session (OneBotSession)
    - web / api: returns JSON payload for clients
    """
    ch = (channel or "web").strip().lower()
    payload = mixed_message_to_dict(mixed)

    if ch == "qq":
        if qq_session is None:
            raise ValueError("qq channel requires qq_session")
        await qq_session.send_mixed_message(
            message_type=message_type,
            user_id=user_id,
            group_id=group_id,
            mixed=mixed,
        )
        return {"channel": "qq", "sent": True, **payload}

    return {"channel": ch, "sent": False, **payload}


def image_loading_text() -> str:
    return str(
        config.get("tools.image.loading_text")
        or config.get("IMAGE_LOADING_TEXT")
        or "正在为你创作图片，稍等一下哦~"
    )
