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


def test_settings_effects_telegram_allowlist_hot_only():
    effects = _settings_effects(
        {
            "bridge": {
                "telegram": {
                    "dm_policy": "allowlist",
                    "allow_from": [6537629878],
                    "allowed_user_ids": [6537629878],
                }
            }
        }
    )
    assert "Telegram 白名单/私聊策略/自动回复" in effects["hot_reload"]
    assert "bridge（QQ / Telegram 消息桥接）" not in effects["restart_required"]


def test_settings_effects_onebot_bridge_restart():
    effects = _settings_effects({"bridge": {"onebot11": {"enabled": True}}})
    assert "QQ OneBot 桥接（onebot11）" in effects["restart_required"]
