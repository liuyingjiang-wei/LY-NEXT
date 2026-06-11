"""Track untrusted content in the agent turn and gate sensitive tools."""

from __future__ import annotations

from contextvars import ContextVar, Token
from dataclasses import dataclass
from typing import Any

from ly_next.agent.channel_tools import normalize_channel
from ly_next.core.config import config

_untrusted: ContextVar[bool] = ContextVar("ly_content_untrusted", default=False)
_reasons: ContextVar[tuple[str, ...]] = ContextVar("ly_content_untrusted_reasons", default=())

_DEFAULT_UNTRUSTED_TOOLS = frozenset(
    {
        "web_fetch",
        "web_search",
        "web_scrape",
        "http_fetch",
    }
)
_DEFAULT_SENSITIVE_TOOLS = frozenset(
    {
        "host_read_file",
        "host_write_file",
        "host_delete_path",
        "host_list_dir",
        "host_run_command",
        "grep_code",
    }
)
_DEFAULT_UNTRUSTED_CHANNELS = frozenset({"qq", "telegram"})
_MUTATING_HTTP_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


@dataclass(frozen=True)
class ContentTrustState:
    untrusted_token: Token
    reasons_token: Token


def agent_policy_config() -> dict[str, Any]:
    sec = config.get("security") or {}
    block = sec.get("agent_policy") if isinstance(sec, dict) else {}
    return block if isinstance(block, dict) else {}


def agent_policy_enabled() -> bool:
    return bool(agent_policy_config().get("enabled", True))


def _untrusted_tool_names() -> frozenset[str]:
    raw = agent_policy_config().get("untrusted_tools")
    if isinstance(raw, list) and raw:
        return frozenset(str(x).strip() for x in raw if str(x).strip())
    return _DEFAULT_UNTRUSTED_TOOLS


def _sensitive_tool_names() -> frozenset[str]:
    raw = agent_policy_config().get("sensitive_tools")
    if isinstance(raw, list) and raw:
        return frozenset(str(x).strip() for x in raw if str(x).strip())
    return _DEFAULT_SENSITIVE_TOOLS


def _untrusted_channels() -> frozenset[str]:
    raw = agent_policy_config().get("untrusted_channels")
    if isinstance(raw, list) and raw:
        return frozenset(str(x).strip().lower() for x in raw if str(x).strip())
    return _DEFAULT_UNTRUSTED_CHANNELS


def reset_content_trust() -> ContentTrustState:
    return ContentTrustState(
        untrusted_token=_untrusted.set(False),
        reasons_token=_reasons.set(()),
    )


def restore_content_trust(state: ContentTrustState) -> None:
    _untrusted.reset(state.untrusted_token)
    _reasons.reset(state.reasons_token)


def mark_content_untrusted(reason: str) -> None:
    if not agent_policy_enabled():
        return
    text = str(reason or "").strip()
    if not text:
        text = "external"
    _untrusted.set(True)
    prev = _reasons.get()
    if text not in prev:
        _reasons.set(prev + (text,))


def content_is_untrusted() -> bool:
    return bool(_untrusted.get())


def untrusted_reasons() -> tuple[str, ...]:
    return _reasons.get()


def seed_untrusted_from_channel(channel: str | None) -> None:
    if not agent_policy_enabled():
        return
    ch = normalize_channel(channel)
    if ch and ch in _untrusted_channels():
        mark_content_untrusted(f"channel:{ch}")


def maybe_mark_tool_output_untrusted(tool_name: str) -> None:
    if tool_name in _untrusted_tool_names():
        mark_content_untrusted(f"tool:{tool_name}")


def _policy_block_message(name: str, detail: str) -> str:
    reasons = ", ".join(untrusted_reasons()) or "external content"
    return (
        f"Tool '{name}' blocked: {detail} ({reasons}). "
        "Complete the task without host or mutating network tools, or start a new thread."
    )


def _mutating_http_blocked(name: str, arguments: dict[str, Any] | None) -> str | None:
    if not agent_policy_config().get("block_mutating_http_when_untrusted", True):
        return None
    if name != "http_fetch" or not content_is_untrusted():
        return None
    method = str((arguments or {}).get("method") or "GET").upper()
    if method not in _MUTATING_HTTP_METHODS:
        return None
    return _policy_block_message(name, "mutating HTTP not allowed in untrusted context")


def tool_blocked_by_policy(tool_name: str, arguments: dict[str, Any] | None = None) -> str | None:
    if not agent_policy_enabled():
        return None
    if not content_is_untrusted():
        return None

    name = str(tool_name or "").strip()
    mutating = _mutating_http_blocked(name, arguments)
    if mutating:
        return mutating

    if not agent_policy_config().get("block_sensitive_tools_when_untrusted", True):
        return None
    if name not in _sensitive_tool_names():
        return None
    return _policy_block_message(name, "untrusted content in context")
