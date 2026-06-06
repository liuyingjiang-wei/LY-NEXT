from __future__ import annotations

from ly_next.bridge.onebot11.commands import OneBotCommand, parse_onebot_command
from ly_next.bridge.onebot11.memory import onebot_history_limit


def test_parse_new_chat_commands():
    assert parse_onebot_command("/新对话") == OneBotCommand.NEW_CHAT
    assert parse_onebot_command("/new") == OneBotCommand.NEW_CHAT
    assert parse_onebot_command("  #新对话 ") == OneBotCommand.NEW_CHAT
    assert parse_onebot_command("你好") == OneBotCommand.NONE


def test_parse_help_command():
    assert parse_onebot_command("/帮助") == OneBotCommand.HELP
    assert parse_onebot_command("/help") == OneBotCommand.HELP


def test_onebot_history_limit_default():
    assert onebot_history_limit() >= 4


def test_onebot_auto_reply_default_mode_react():
    from ly_next.bridge.onebot11.config import get_onebot11_settings

    settings = get_onebot11_settings()
    assert settings.auto_reply.mode == "react"
