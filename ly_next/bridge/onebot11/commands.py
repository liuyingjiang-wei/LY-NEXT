from __future__ import annotations

from enum import Enum

from ly_next.core.config import config


class OneBotCommand(str, Enum):
    NONE = "none"
    NEW_CHAT = "new_chat"
    HELP = "help"


def _configured_commands(key: str, defaults: tuple[str, ...]) -> tuple[str, ...]:
    raw = config.get(f"bridge.onebot11.{key}", None)
    if raw is None:
        return defaults
    if isinstance(raw, str):
        s = raw.strip()
        return (s,) if s else defaults
    if isinstance(raw, (list, tuple)):
        out = [str(x).strip() for x in raw if str(x).strip()]
        return tuple(out) if out else defaults
    return defaults


def new_chat_commands() -> tuple[str, ...]:
    return _configured_commands(
        "new_chat_commands",
        ("/新对话", "/new", "#新对话", "新对话", "/重置", "/reset"),
    )


def help_commands() -> tuple[str, ...]:
    return _configured_commands("help_commands", ("/帮助", "/help", "#帮助"))


def new_chat_ack_message() -> str:
    return str(
        config.get(
            "bridge.onebot11.new_chat_reply",
            "已开始新对话。发送「/新对话」可清空当前上下文；历史对话仍保存在数据库中。",
        )
        or ""
    ).strip()


def help_message() -> str:
    cmds = "、".join(new_chat_commands()[:4])
    return str(
        config.get(
            "bridge.onebot11.help_reply",
            f"QQ 机器人命令：{cmds} — 开始新对话（不继承此前上下文）。",
        )
        or ""
    ).strip()


def _normalize_cmd(text: str) -> str:
    t = text.strip()
    if not t:
        return ""
    if t.startswith("<") and t.endswith(">"):
        t = t[1:-1].strip()
    return t.casefold()


def parse_onebot_command(text: str) -> OneBotCommand:
    raw = text.strip()
    if not raw:
        return OneBotCommand.NONE
    norm = _normalize_cmd(raw)
    for cmd in new_chat_commands():
        if norm == _normalize_cmd(cmd):
            return OneBotCommand.NEW_CHAT
    for cmd in help_commands():
        if norm == _normalize_cmd(cmd):
            return OneBotCommand.HELP
    return OneBotCommand.NONE
