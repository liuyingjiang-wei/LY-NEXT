"""NapCatV11 action binding and invoke tests."""

from unittest.mock import AsyncMock, patch

import pytest

pytest.importorskip("qq_onebot")

from qq_onebot.bridge.napcat_actions import NAPCAT_ACTION_NAMES
from qq_onebot.bridge.napcat_api import NapCatV11, is_bindable_action_name, napcat


def test_action_count_matches_napcat_doc():
    assert len(NAPCAT_ACTION_NAMES) == 128
    assert ".ocr_image" in NAPCAT_ACTION_NAMES
    assert "upload_file_stream" in NAPCAT_ACTION_NAMES
    assert "unknown" not in NAPCAT_ACTION_NAMES


def test_bindable_methods_on_class():
    for name in NAPCAT_ACTION_NAMES:
        if is_bindable_action_name(name):
            assert callable(getattr(NapCatV11, name))


def test_dot_prefixed_use_invoke_only():
    assert not is_bindable_action_name(".ocr_image")
    assert not hasattr(NapCatV11, ".ocr_image")


@pytest.mark.asyncio
async def test_invoke_delegates_to_session():
    api = napcat()
    with patch(
        "qq_onebot.bridge.napcat_api.call_onebot_action_data",
        new_callable=AsyncMock,
        return_value={"user_id": 1},
    ) as m:
        data = await api.invoke("get_login_info")
    assert data == {"user_id": 1}
    m.assert_awaited_once_with("get_login_info", {}, self_id=None, timeout=None)


@pytest.mark.asyncio
async def test_bound_method_send_private_msg():
    api = napcat()
    with patch(
        "qq_onebot.bridge.napcat_api.call_onebot_action_data",
        new_callable=AsyncMock,
        return_value={"message_id": 9},
    ) as m:
        data = await api.send_private_msg(user_id=123, message="hi")
    assert data["message_id"] == 9
    m.assert_awaited_once()
    assert m.await_args.args[0] == "send_private_msg"
    assert m.await_args.args[1]["user_id"] == 123


@pytest.mark.asyncio
async def test_dot_action_via_invoke():
    api = napcat()
    with patch(
        "qq_onebot.bridge.napcat_api.call_onebot_action_data",
        new_callable=AsyncMock,
        return_value={},
    ) as m:
        await api.invoke(".ocr_image", image="base64...")
    m.assert_awaited_once_with(".ocr_image", {"image": "base64..."}, self_id=None, timeout=None)
