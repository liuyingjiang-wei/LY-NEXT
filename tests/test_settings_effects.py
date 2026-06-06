from __future__ import annotations

from ly_next.api.ly_api import _settings_effects


def test_settings_effects_restart_roots():
    effects = _settings_effects({"server": {"port": 9000}, "database": {"host": "127.0.0.1"}})
    assert "server（监听地址/端口）" in effects["restart_required"]
    assert "database（PostgreSQL）" in effects["restart_required"]


def test_settings_effects_hot_reload_llm():
    effects = _settings_effects({"openai_llm": {"model": "gpt-4o-mini"}})
    assert "OpenAI" in effects["hot_reload"]
    assert not effects["restart_required"]


def test_settings_effects_mcp_remote_note():
    effects = _settings_effects({"tools": {"mcp": {"remote": {"enabled": True}}}})
    assert any("远程 MCP" in n for n in effects["notes"])


def test_settings_effects_auth_note():
    effects = _settings_effects({"auth": {"api_key": "***"}})
    assert any("Cookie" in n for n in effects["notes"])
