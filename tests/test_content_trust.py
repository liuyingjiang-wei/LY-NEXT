import pytest

from ly_next.agent.content_trust import (
    content_is_untrusted,
    mark_content_untrusted,
    reset_content_trust,
    restore_content_trust,
    seed_untrusted_from_channel,
    tool_blocked_by_policy,
    untrusted_reasons,
)
from ly_next.tools.base import BaseTool, ToolDefinition, ToolResult
from ly_next.tools.registry import ToolRegistry


class _FakeTool(BaseTool):
    def __init__(self, name: str, category: str = "general") -> None:
        self._definition = ToolDefinition(
            name=name,
            description="test",
            parameters={"type": "object", "properties": {}},
            category=category,
        )

    @property
    def definition(self) -> ToolDefinition:
        return self._definition

    async def execute(self, **kwargs: object) -> ToolResult:
        return ToolResult(success=True, result=None)


def _policy_cfg(**overrides):
    base = {
        "enabled": True,
        "block_sensitive_tools_when_untrusted": True,
        "untrusted_channels": ["qq", "telegram"],
        "untrusted_tools": ["web_fetch", "http_fetch"],
        "sensitive_tools": ["host_read_file", "host_run_command"],
    }
    base.update(overrides)
    return base


@pytest.fixture(autouse=True)
def _reset_trust():
    token = reset_content_trust()
    yield
    restore_content_trust(token)


def test_seed_untrusted_from_bridge_channel(monkeypatch):
    monkeypatch.setattr(
        "ly_next.agent.content_trust.agent_policy_config",
        lambda: _policy_cfg(),
    )
    seed_untrusted_from_channel("qq")
    assert content_is_untrusted()
    assert "channel:qq" in untrusted_reasons()


def test_seed_untrusted_normalizes_onebot_alias(monkeypatch):
    monkeypatch.setattr(
        "ly_next.agent.content_trust.agent_policy_config",
        lambda: _policy_cfg(),
    )
    seed_untrusted_from_channel("OneBot11")
    assert content_is_untrusted()
    assert "channel:qq" in untrusted_reasons()


def test_web_channel_not_auto_untrusted(monkeypatch):
    monkeypatch.setattr(
        "ly_next.agent.content_trust.agent_policy_config",
        lambda: _policy_cfg(),
    )
    seed_untrusted_from_channel("web")
    assert not content_is_untrusted()


def test_blocks_sensitive_tool_when_untrusted(monkeypatch):
    monkeypatch.setattr(
        "ly_next.agent.content_trust.agent_policy_config",
        lambda: _policy_cfg(),
    )
    mark_content_untrusted("tool:web_fetch")
    err = tool_blocked_by_policy("host_read_file", {})
    assert err is not None
    assert "host_read_file" in err


def test_allows_sensitive_tool_when_trusted(monkeypatch):
    monkeypatch.setattr(
        "ly_next.agent.content_trust.agent_policy_config",
        lambda: _policy_cfg(),
    )
    assert tool_blocked_by_policy("host_read_file", {}) is None


def test_http_get_allowed_when_untrusted(monkeypatch):
    monkeypatch.setattr(
        "ly_next.agent.content_trust.agent_policy_config",
        lambda: _policy_cfg(),
    )
    mark_content_untrusted("tool:web_fetch")
    assert tool_blocked_by_policy("http_fetch", {"method": "GET"}) is None
    assert tool_blocked_by_policy("http_fetch", {"method": "POST"}) is not None


def test_reset_content_trust_clears_state(monkeypatch):
    monkeypatch.setattr(
        "ly_next.agent.content_trust.agent_policy_config",
        lambda: _policy_cfg(),
    )
    mark_content_untrusted("tool:web_fetch")
    reset_content_trust()
    assert not content_is_untrusted()
    assert untrusted_reasons() == ()


def test_restore_content_trust_reverts_outer_scope(monkeypatch):
    monkeypatch.setattr(
        "ly_next.agent.content_trust.agent_policy_config",
        lambda: _policy_cfg(),
    )
    mark_content_untrusted("tool:web_fetch")
    state = reset_content_trust()
    assert not content_is_untrusted()
    restore_content_trust(state)
    assert content_is_untrusted()
    assert "tool:web_fetch" in untrusted_reasons()


@pytest.mark.asyncio
async def test_registry_blocks_sensitive_tool(monkeypatch):
    monkeypatch.setattr(
        "ly_next.agent.content_trust.agent_policy_config",
        lambda: _policy_cfg(),
    )
    monkeypatch.setattr("ly_next.core.audit_log.audit_enabled", lambda: False)

    reg = ToolRegistry()
    reg.register(_FakeTool("host_read_file", "host"))
    mark_content_untrusted("channel:telegram")

    out = await reg.call_tool("host_read_file", {})
    assert out["success"] is False
    assert "blocked" in out["error"].lower()


@pytest.mark.asyncio
async def test_registry_marks_untrusted_after_fetch(monkeypatch):
    monkeypatch.setattr(
        "ly_next.agent.content_trust.agent_policy_config",
        lambda: _policy_cfg(),
    )
    monkeypatch.setattr("ly_next.core.audit_log.audit_enabled", lambda: False)

    reg = ToolRegistry()
    reg.register(_FakeTool("http_fetch", "network"))
    reg.register(_FakeTool("host_read_file", "host"))

    await reg.call_tool("http_fetch", {"url": "https://example.com"})
    assert content_is_untrusted()

    out = await reg.call_tool("host_read_file", {})
    assert out["success"] is False
