from __future__ import annotations

from ly_next.agent.channel_tools import (
    HOST_FILE_WRITE_TOOLS,
    apply_channel_tool_policy,
    channel_allow_file_write,
    normalize_channel,
)
from ly_next.agent.deps import AgentDeps


def test_normalize_channel_aliases():
    assert normalize_channel("OneBot11") == "qq"
    assert normalize_channel("tg") == "telegram"
    assert normalize_channel("workbench") == "web"


def test_apply_channel_tool_policy_denies_write_tools(monkeypatch):
    monkeypatch.setattr(
        "ly_next.agent.channel_tools.config.get",
        lambda key, default=None: (
            {
                "web": {"allow_file_write": False},
                "qq": {"allow_file_write": False},
                "telegram": {"allow_file_write": False},
            }
            if key == "agent.channel_tools"
            else default
        ),
    )
    deps = AgentDeps(provider="openai", model="m", tool_deny_tools=[])
    apply_channel_tool_policy(deps, "qq")
    for name in HOST_FILE_WRITE_TOOLS:
        assert name in deps.tool_deny_tools


def test_channel_allow_file_write_default_web(monkeypatch):
    monkeypatch.setattr(
        "ly_next.agent.channel_tools.config.get",
        lambda key, default=None: default if key == "agent.channel_tools" else default,
    )
    assert channel_allow_file_write("web") is True
    assert channel_allow_file_write("qq") is False
