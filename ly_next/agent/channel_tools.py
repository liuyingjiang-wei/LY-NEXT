from __future__ import annotations

from ly_next.core.config import config

HOST_FILE_WRITE_TOOLS = (
    "host_write_file",
    "host_delete_path",
)

_CHANNEL_ALIASES = {
    "web": "web",
    "workbench": "web",
    "chat": "web",
    "qq": "qq",
    "onebot": "qq",
    "onebot11": "qq",
    "telegram": "telegram",
    "tg": "telegram",
}

_DEFAULT_ALLOW = {
    "web": True,
    "qq": False,
    "telegram": False,
}


def normalize_channel(channel: str | None) -> str | None:
    if channel is None:
        return None
    text = str(channel).strip().lower()
    if not text:
        return None
    return _CHANNEL_ALIASES.get(text, text)


def channel_allow_file_write(channel: str | None) -> bool:
    key = normalize_channel(channel) or "web"
    raw = config.get("agent.channel_tools", {}) or {}
    if not isinstance(raw, dict):
        raw = {}
    block = raw.get(key)
    if isinstance(block, dict) and "allow_file_write" in block:
        return bool(block.get("allow_file_write"))
    return bool(_DEFAULT_ALLOW.get(key, False))


def apply_channel_tool_policy(deps, channel: str | None) -> None:
    if channel_allow_file_write(channel):
        return
    deny = list(getattr(deps, "tool_deny_tools", None) or [])
    seen = set(deny)
    for name in HOST_FILE_WRITE_TOOLS:
        if name not in seen:
            deny.append(name)
            seen.add(name)
    deps.tool_deny_tools = deny
