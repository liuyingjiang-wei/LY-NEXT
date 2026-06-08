from __future__ import annotations

import pytest

pytest.importorskip("qq_onebot")

from qq_onebot.bridge.commands import OneBotCommand, parse_onebot_command
from qq_onebot.bridge.memory import onebot_history_limit

_NEW = "\u65b0\u5bf9\u8bdd"  # ???
_HELP = "\u5e2e\u52a9"  # ??
_HELLO = "\u4f60\u597d"  # ??


def test_parse_new_chat_commands():
    assert parse_onebot_command(f"/{_NEW}") == OneBotCommand.NEW_CHAT
    assert parse_onebot_command("/new") == OneBotCommand.NEW_CHAT
    assert parse_onebot_command(f"  #{_NEW}") == OneBotCommand.NEW_CHAT
    assert parse_onebot_command(_HELLO) == OneBotCommand.NONE


def test_parse_help_command():
    assert parse_onebot_command(f"/{_HELP}") == OneBotCommand.HELP
    assert parse_onebot_command("/help") == OneBotCommand.HELP


def test_onebot_history_limit_default():
    assert onebot_history_limit() >= 4


def test_onebot_auto_reply_default_mode_react():
    from qq_onebot.bridge.config import get_onebot11_settings

    settings = get_onebot11_settings()
    assert settings.auto_reply.mode == "react"
