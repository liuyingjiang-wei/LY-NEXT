from unittest.mock import AsyncMock, patch

import pytest

pytest.importorskip("qq_onebot")

from qq_onebot.bridge.call import call_onebot_action, normalize_action_name
from qq_onebot.bridge.session import OneBotSession


def test_normalize_action_name_accepts_napcat_extensions():
    assert normalize_action_name("get_login_info") == "get_login_info"
    assert normalize_action_name(".ocr_image") == ".ocr_image"
    assert normalize_action_name("_send_group_notice") == "_send_group_notice"
    assert normalize_action_name("ArkSharePeer") == "ArkSharePeer"
    with pytest.raises(ValueError):
        normalize_action_name("bad name")


@pytest.mark.asyncio
async def test_call_onebot_action_via_session():
    session = OneBotSession(websocket=AsyncMock())
    session.send_api_raw = AsyncMock(
        return_value={"status": "ok", "retcode": 0, "data": {"user_id": 1}}
    )

    with patch(
        "qq_onebot.bridge.call.list_sessions",
        return_value=[session],
    ):
        raw = await call_onebot_action("get_login_info", {})
    assert raw["status"] == "ok"
    session.send_api_raw.assert_awaited_once_with("get_login_info", {})
