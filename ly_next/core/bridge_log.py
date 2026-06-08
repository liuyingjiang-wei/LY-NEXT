"""Pretty console lines for QQ / Telegram bridge plugins."""

from __future__ import annotations

from ly_next.core.logger import LogColors, create_gradient_text, get_logger

_CHANNEL_LABEL = {
    "onebot11": ("QQ", ["#0ea5e9", "#0284c7"]),
    "telegram": ("TG", ["#38bdf8", "#0ea5e9"]),
}


def bridge_prefix(channel: str) -> str:
    label, colors = _CHANNEL_LABEL.get(channel, (channel.upper(), ["#94a3b8", "#64748b"]))
    badge = create_gradient_text(label, colors)
    return f"{badge} {LogColors.DIM}›{LogColors.RESET}"


def bridge_msg(channel: str, message: str) -> str:
    return f"{bridge_prefix(channel)} {message}"


def get_bridge_logger(name: str):
    return get_logger(name)


def blog(logger, channel: str, level: str, message: str, *args, **kwargs) -> None:
    text = bridge_msg(channel, message)
    fn = getattr(logger, level, logger.info)
    fn(text, *args, **kwargs)
