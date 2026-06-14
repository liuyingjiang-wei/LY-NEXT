"""Bot persona load/save and prompt assembly."""

from __future__ import annotations

import pytest

from ly_next.agent.persona import (
    BotPersona,
    PersonaOverride,
    combine_native_system_prefix,
    load_persona,
    merge_persona_layers,
    persona_file_path,
    persona_to_prompt_text,
    save_persona,
)


def test_persona_to_prompt_text_includes_name_and_examples():
    p = BotPersona(
        enabled=True,
        bot_name="小LY",
        persona="性格友善",
        example_dialogues="用户：你好\n助手：嗨～",
    )
    text = persona_to_prompt_text(p)
    assert "小LY" in text
    assert "性格友善" in text
    assert "示例对话" in text


def test_merge_persona_layers_append_and_replace():
    base = BotPersona(enabled=True, bot_name="A", persona="全局", example_dialogues="")
    ov = PersonaOverride(enabled=True, persona="渠道补充", replace=False)
    merged = merge_persona_layers(base, ov)
    assert "全局" in merged.persona
    assert "渠道补充" in merged.persona

    ov_replace = PersonaOverride(enabled=True, persona="仅渠道", replace=True)
    merged2 = merge_persona_layers(base, ov_replace)
    assert merged2.persona == "仅渠道"


def test_save_and_load_persona_roundtrip(monkeypatch, tmp_path):
    monkeypatch.setattr("ly_next.agent.persona.get_data_root", lambda: tmp_path)
    monkeypatch.setattr(
        "ly_next.agent.persona._config_persona_defaults",
        lambda: {
            "enabled": True,
            "bot_name": "小LY",
            "trigger_names": "",
            "persona": "默认人设",
            "example_dialogues": "",
        },
    )
    data = BotPersona(
        enabled=True,
        bot_name="测试Bot",
        persona="临时人设内容",
        example_dialogues="",
    )
    save_persona(data)
    path = persona_file_path()
    assert path.is_file()
    loaded = load_persona()
    assert loaded.bot_name == "测试Bot"
    assert "临时人设内容" in loaded.persona


def test_combine_native_system_prefix_orders_persona_first():
    combined = combine_native_system_prefix("人设段")
    assert combined.startswith("## Bot 人设（最高优先级）")
    assert "人设段" in combined
    assert "helpful assistant" in combined.lower() or "function tools" in combined.lower()


@pytest.mark.asyncio
async def test_resolve_persona_system_prefix_request_override(monkeypatch, tmp_path):
    from ly_next.agent.persona import resolve_persona_system_prefix

    monkeypatch.setattr("ly_next.agent.persona.get_data_root", lambda: tmp_path)
    monkeypatch.setattr(
        "ly_next.agent.persona._config_persona_defaults",
        lambda: {
            "enabled": True,
            "bot_name": "小LY",
            "trigger_names": "",
            "persona": "全局人设",
            "example_dialogues": "",
        },
    )
    save_persona(BotPersona(enabled=True, bot_name="小LY", persona="全局人设"))
    text = await resolve_persona_system_prefix(
        persona_override={"enabled": True, "persona": "临时角色"},
    )
    assert "全局人设" in text
    assert "临时角色" in text
